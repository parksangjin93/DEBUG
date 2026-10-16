"""
여러 TC 를 묶어서 실행하고, 근거(evidence) 문맥을 관리한다.

책임
----
1. 로그 라인을 무장된(armed) TC 들에게 전달
2. 최근 N줄을 링버퍼로 보관 -> FAIL/TIMEOUT 시 '앞 문맥' 첨부
3. 판정 직후 M줄을 더 모아서 '뒤 문맥' 첨부 (원본 로그를 다시 안 뒤져도 되게)
4. 실행 전 룰 충돌 정적 검사 (가장 흔한 오탐 원인 사전 차단)
"""

from __future__ import annotations

from collections import deque

from .log_event import LogEvent
from .step import TCDefinition
from .tc_engine import EventWatcher, TCEngine
from .verdict import Verdict

CONTEXT_BEFORE = 30   # 판정 지점 앞쪽으로 보관할 줄 수
CONTEXT_AFTER = 10    # 판정 이후 추가로 모을 줄 수


class TCManager:
    def __init__(self, clock, console=None):
        self.clock = clock
        self.console = console

        self.engines: list[TCEngine] = []
        self.watchers: list[EventWatcher] = []
        self.definitions: list[TCDefinition] = []

        self._context = deque(maxlen=CONTEXT_BEFORE)
        self._pending_tail: list[tuple[Verdict, list[str]]] = []

        self.on_verdict = None      # fn(Verdict)  -> 리포트로 전달

    # ------------------------------------------------------------------
    def add(self, definition: TCDefinition):
        self.definitions.append(definition)
        if definition.is_event:
            watcher = EventWatcher(definition, self.clock, self.console)
            watcher.context_provider = lambda: list(self._context)
            watcher.on_verdict = self._handle_verdict
            self.watchers.append(watcher)
        else:
            engine = TCEngine(definition, self.clock, self.console)
            engine.context_provider = lambda: list(self._context)
            engine.on_verdict = self._handle_verdict
            self.engines.append(engine)

    # ------------------------------------------------------------------
    def process(self, event: LogEvent):
        line = f"[{event.stamp.strftime('%H:%M:%S.%f')[:-3]}] {event.clean}"

        # 판정 직후 뒤쪽 문맥 수집 -> 다 모이면 그때 리포트로 넘긴다
        if self._pending_tail:
            still = []
            for verdict, buf in self._pending_tail:
                buf.append(line)
                if len(buf) < CONTEXT_AFTER:
                    still.append((verdict, buf))
                else:
                    self._emit(verdict)
            self._pending_tail = still

        for engine in self.engines:
            engine.process(event)
        for watcher in self.watchers:
            watcher.process(event)

        self._context.append(line)

    def tick(self, now: float):
        for engine in self.engines:
            engine.tick(now)

    # ------------------------------------------------------------------
    def _emit(self, verdict: Verdict):
        if self.on_verdict:
            self.on_verdict(verdict)

    def _handle_verdict(self, verdict: Verdict, event):
        if verdict.status == "PASS":
            self._emit(verdict)          # PASS 는 뒤 문맥이 필요 없다
            return
        # FAIL/TIMEOUT/INCOMPLETE : 뒤쪽 로그 CONTEXT_AFTER 줄을 더 모은 뒤 기록
        verdict.context_after = []
        self._pending_tail.append((verdict, verdict.context_after))

    def flush_pending(self):
        for verdict, _buf in self._pending_tail:
            self._emit(verdict)
        self._pending_tail = []

    def finalize(self):
        """감시 종료 시 호출. 진행 중 TC 마감 + 미완 근거 flush + 이벤트 집계."""
        for engine in self.engines:
            engine.abort()
        self.flush_pending()
        for watcher in self.watchers:
            if watcher.count > 0 and self.on_verdict:
                self.on_verdict(watcher.to_verdict())

    # ------------------------------------------------------------------
    def abort_running(self, reason_hint="로그 파일 전환"):
        """세션이 바뀌면 진행 중이던 TC 는 문맥이 끊긴 것이므로 마감한다."""
        for engine in self.engines:
            if engine.is_running:
                engine.abort()
        self.flush_pending()

    def status_lines(self) -> list[str]:
        return [e.status_line() for e in self.engines if e.is_running]

    def running_count(self) -> int:
        return sum(1 for e in self.engines if e.is_running)

    # ------------------------------------------------------------------
    def validate(self, max_items=8, max_warnings=12) -> list[str]:
        """
        실행 전 룰 충돌 검사.

        가장 위험한 것은 '서로 다른 TC 가 같은 문자열을 기다리는' 상황이다.
        예) TC007/TC008/TC009 가 모두 'http status code [200]' 대기
            -> 남의 응답을 자기 것으로 착각해 잘못 PASS
        예) TC004/TC006 시작 트리거가 둘 다 'Format start!!'
            -> SD 포맷만 해도 HDD TC 가 같이 시작되어 허위 TIMEOUT

        경고가 수백 줄이 되면 읽을 수 없으므로 표시 개수를 제한한다.
        """
        NL = chr(10)
        warnings = []
        # VALUE 미입력(TODO) TC 는 검사 대상에서 뺀다.
        # 자리표시자끼리 비교해봐야 의미 없는 경고만 쏟아진다.
        seq = [e.d for e in self.engines if not e.d.is_todo]

        def fmt(ids):
            ids = sorted(set(ids))
            head = ", ".join(ids[:max_items])
            more = f" 외 {len(ids) - max_items}개" if len(ids) > max_items else ""
            return f"[{head}{more}]  (총 {len(ids)}개)"

        # 0) ABSENT 스텝 규칙 검사
        for d in seq:
            if d.steps[0].is_absent:
                warnings.append(
                    f"{d.tc_id} : STEP 1 은 ABSENT 로 둘 수 없습니다 "
                    f"(TC 를 시작시킬 트리거가 없음)")
            for st in d.steps:
                if st.is_absent and not st.timeout:
                    warnings.append(
                        f"{d.tc_id} STEP {st.step_no} : "
                        f"ABSENT 인데 TIMEOUT 이 없습니다")

        # 1) 시작 트리거 중복
        starts = {}
        for d in seq:
            starts.setdefault(d.steps[0].keyword, []).append(d.tc_id)
        dup = [(k, v) for k, v in starts.items() if len(set(v)) > 1]
        dup.sort(key=lambda x: -len(set(x[1])))
        for keyword, ids in dup:
            warnings.append(
                f"시작 트리거 중복 {fmt(ids)}" + NL
                + f"      '{keyword[:70]}'" + NL
                + "      -> 한쪽만 선택해서 실행하거나 트리거를 유니크하게 바꾸세요.")

        # 2) 대기 키워드 중복 (2번째 이후 스텝)
        waits = {}
        for d in seq:
            for st in d.steps[1:]:
                waits.setdefault(st.keyword, []).append(d.tc_id)
        dup = [(k, v) for k, v in waits.items() if len(set(v)) > 1]
        dup.sort(key=lambda x: -len(set(x[1])))
        for keyword, ids in dup:
            warnings.append(
                f"대기 키워드 중복 {fmt(ids)}" + NL
                + f"      '{keyword[:70]}'" + NL
                + "      -> 동시에 실행하면 오탐 가능. 따로 실행하세요.")

        if len(warnings) > max_warnings:
            hidden = len(warnings) - max_warnings
            warnings = warnings[:max_warnings]
            warnings.append(f"... 이 밖에 {hidden}건 더 있습니다. "
                            f"TC 선택을 줄여서 다시 확인하세요.")
        return warnings
