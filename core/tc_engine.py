"""
TC 판정 엔진.

TCEngine    : 다단계 시나리오 TC 상태머신 (SEQUENCE)
EventWatcher: 단일 키워드 TC. 발생 횟수만 집계하고 리포트를 오염시키지 않는다.

시간은 전부 Clock 에서 받는다 (time.time() 직접 호출 금지).
-> 실시간 감시와 리플레이가 같은 코드로 동작한다.
"""

from __future__ import annotations

from datetime import datetime

from .log_event import LogEvent
from .step import TCDefinition
from .verdict import EVENT, FAIL, INCOMPLETE, PASS, TIMEOUT, Verdict


class TCEngine:
    """하나의 시나리오 TC 를 판정하는 상태머신."""

    def __init__(self, definition: TCDefinition, clock, console=None):
        self.d = definition
        self.clock = clock
        self.console = console

        self.state = "IDLE"
        self.current_step = 0
        self.step_deadline: float | None = None
        self.start_ts: float | None = None
        self.start_dt: datetime | None = None

        self.steps_log: list[dict] = []
        self.guards: list[dict] = []      # 동시 감시 중인 ABSENT 조건
        self.on_verdict = None            # fn(Verdict, LogEvent|None)
        self.context_provider = None      # fn() -> list[str]

        self.run_count = 0

    # ------------------------------------------------------------------
    @property
    def steps(self):
        return self.d.steps

    @property
    def is_running(self) -> bool:
        return self.state == "RUNNING"

    def status_line(self) -> str:
        if not self.is_running:
            return f"{self.d.tc_id:<6} IDLE"
        step = self.steps[self.current_step]
        remain = ""
        if self.step_deadline is not None:
            remain = f"  (남은 {max(0.0, self.step_deadline - self.clock.now()):.1f}s)"
        what = ("미발생 감시: " if step.is_absent else "대기: ") + step.keyword[:44]
        return (f"{self.d.tc_id:<6} STEP {self.current_step + 1}/{len(self.steps)} "
                f"{what}{remain}")

    # ------------------------------------------------------------------
    def process(self, event: LogEvent):
        line = event.clean

        if self.state == "IDLE":
            if not self._try_start(event):
                return
            # 시작 트리거 = STEP1 이므로 이 라인으로 STEP1 을 바로 통과 처리한다.

        # 0) 동시 감시(ABSENT) : 금지 문구가 나오면 즉시 실패
        for g in self.guards:
            if g["step"].matcher.match(line) is not None:
                self._trip_guard(g, event)
                return

        step = self.steps[self.current_step]

        # 1) FAIL 키워드 우선 확인
        if step.fail_matcher and step.fail_matcher.match(line) is not None:
            self._finish(FAIL, event,
                         reason=f"FAIL 키워드 검출: {step.fail_keyword}")
            return

        # 2) 통과 조건
        caps = step.matcher.match(line)
        if caps is None:
            return

        self.steps_log.append({
            "step": step.step_no,
            "method": step.method,
            "expected": step.keyword,
            "matched": line[:400],
            "at": event.stamp.strftime("%H:%M:%S.%f")[:-3],
            "ok": True,
            "captures": caps,
        })

        if self.console:
            self.console.step_ok(self.d, step, self.current_step + 1, len(self.steps))

        self._advance(event)

    def tick(self, now: float):
        """
        로그가 안 들어와도 주기적으로 호출된다.
        - 만료된 ABSENT 감시 구간 정리 (무사히 지나갔으면 통과 기록)
        - CHECK 스텝 제한 시간 초과 -> TIMEOUT
        """
        if self.state != "RUNNING":
            return

        # 감시 구간이 끝난 ABSENT 조건은 '통과'로 확정
        if self.guards:
            still = []
            for g in self.guards:
                if now >= g["until"]:
                    g["log"]["matched"] = f"미발생 확인 완료 ({g['step'].timeout}s)"
                else:
                    still.append(g)
            self.guards = still

        if self.step_deadline is None or now < self.step_deadline:
            return

        step = self.steps[self.current_step]
        self._finish(
            TIMEOUT, None,
            reason=(f"STEP {step.step_no} 미검출 "
                    f"({step.timeout}s 초과) : {step.keyword}"),
        )

    # -- 내부 -----------------------------------------------------------
    def _try_start(self, event: LogEvent) -> bool:
        first = self.steps[0]
        if first.matcher.match(event.clean) is None:
            return False
        self.state = "RUNNING"
        self.current_step = 0
        self.steps_log = []
        self.start_ts = self.clock.now()
        self.start_dt = event.stamp
        self.step_deadline = None
        self.guards = []
        self.run_count += 1
        if self.console:
            self.console.tc_start(self.d, self.run_count)
        return True

    def _advance(self, event):
        """현재 스텝을 통과 처리한 뒤 다음으로 넘어간다."""
        self.current_step += 1
        self._arm_step(self.current_step, event)

    def _arm_step(self, idx: int, event=None):
        """
        다음 스텝을 준비한다.
        ABSENT 스텝은 '차단'이 아니라 '동시 감시'다.
        등록만 하고 곧바로 그다음 스텝으로 넘어간다.
        -> 감시 구간 동안에도 뒤 스텝의 통과 조건을 계속 볼 수 있다.
        """
        while idx < len(self.steps) and self.steps[idx].is_absent:
            st = self.steps[idx]
            log = {
                "step": st.step_no,
                "method": st.method,
                "expected": f"{st.timeout}초 동안 미발생: {st.keyword}",
                "matched": "(감시 중)",
                "at": self.clock.now_dt().strftime("%H:%M:%S.%f")[:-3],
                "ok": True,
            }
            self.steps_log.append(log)
            self.guards.append({
                "step": st,
                "until": self.clock.now() + float(st.timeout or 0),
                "log": log,
            })
            if self.console:
                self.console.step_ok(self.d, st, idx + 1, len(self.steps))
            idx += 1

        self.current_step = idx

        if idx >= len(self.steps):
            # 남은 감시 구간이 있어도 시나리오 자체는 완료
            self._finish(PASS, event)
            return

        step = self.steps[idx]
        self.step_deadline = (self.clock.now() + float(step.timeout)
                              if step.timeout else None)

    def _trip_guard(self, guard, event):
        """감시 중이던 금지 문구가 실제로 나왔다."""
        st = guard["step"]
        guard["log"]["ok"] = False
        guard["log"]["matched"] = event.clean[:400] if event else ""
        self._finish(FAIL, event,
                     reason=f"금지 문구 검출: {st.keyword}",
                     at_step=st)

    def _finish(self, status: str, event: LogEvent | None, reason: str = "",
                at_step=None):
        end_dt = event.stamp if event else self.clock.now_dt()
        exec_time = max(0.0, self.clock.now() - (self.start_ts or self.clock.now()))

        # 아직 감시 구간이 남아 있던 ABSENT 조건 마감 표기
        for g in self.guards:
            if g["log"].get("matched") == "(감시 중)":
                left = max(0.0, g["until"] - self.clock.now())
                g["log"]["matched"] = f"판정 시점까지 미발생 (잔여 {left:.0f}s)"

        failed_step = ""
        if at_step is not None:
            failed_step = (f"STEP {at_step.step_no} ({at_step.method})"
                           if at_step.method else f"STEP {at_step.step_no}")
        elif status != PASS and self.current_step < len(self.steps):
            s = self.steps[self.current_step]
            failed_step = f"STEP {s.step_no} ({s.method})" if s.method else f"STEP {s.step_no}"
            self.steps_log.append({
                "step": s.step_no,
                "method": s.method,
                "expected": s.keyword,
                "matched": (event.clean[:400] if event else ""),
                "at": end_dt.strftime("%H:%M:%S.%f")[:-3],
                "ok": False,
            })

        verdict = Verdict(
            tc_id=self.d.tc_id,
            tc_name=self.d.tc_name,
            purpose=self.d.purpose,
            status=status,
            start_time=self.start_dt,
            end_time=end_dt,
            exec_time=round(exec_time, 3),
            reason=reason,
            failed_step=failed_step,
            steps_log=list(self.steps_log),
            context_before=(self.context_provider() if self.context_provider else []),
        )

        if self.console:
            self.console.verdict(verdict)
        if self.on_verdict:
            self.on_verdict(verdict, event)

        self.reset()

    def abort(self):
        """감시 종료 시점에 아직 진행 중이던 TC를 미완료로 마감한다."""
        if self.state != "RUNNING":
            return
        step = self.steps[self.current_step]
        self._finish(INCOMPLETE, None,
                     reason=f"감시 종료 시점까지 STEP {step.step_no} 미완료 : {step.keyword}")

    def reset(self):
        self.state = "IDLE"
        self.current_step = 0
        self.step_deadline = None
        self.start_ts = None
        self.start_dt = None
        self.steps_log = []
        self.guards = []


class EventWatcher:
    """
    단일 키워드 TC (RECORD ON(SD), DSM Event 등).

    매번 PASS 를 쌓지 않고 발생 횟수와 최초/최종 시각만 집계한다.
    cooldown 안에 반복 발생하는 것은 1회로 본다.
    """

    def __init__(self, definition: TCDefinition, clock, console=None):
        self.d = definition
        self.clock = clock
        self.console = console
        self.step = definition.steps[0]

        self.count = 0
        self.first_at: datetime | None = None
        self.last_at: datetime | None = None
        self.samples: list[str] = []
        self._last_ts: float = -1e18
        self._last_fail_ts: float = -1e18

        self.on_verdict = None          # fn(Verdict, LogEvent)
        self.context_provider = None

    def process(self, event: LogEvent):
        # 단일 스텝이라도 FAIL 키워드가 있으면 그건 즉시 불합 신호다.
        # (예: TC026 'Disk probe is not finished yet!!' - Redmine #9604 회귀)
        if self.step.fail_matcher and self.step.fail_matcher.match(event.clean) is not None:
            now = self.clock.now()
            if now - self._last_fail_ts >= self.d.cooldown:
                self._last_fail_ts = now
                self._emit_fail(event)
            return

        if self.step.matcher.match(event.clean) is None:
            return
        now = self.clock.now()
        if now - self._last_ts < self.d.cooldown:
            return
        self._last_ts = now
        self.count += 1
        self.last_at = event.stamp
        if self.first_at is None:
            self.first_at = event.stamp
        if len(self.samples) < 5:
            self.samples.append(
                f"[{event.stamp.strftime('%H:%M:%S')}] {event.clean[:200]}")
        if self.console:
            self.console.event_hit(self.d, self.count, event)

    def tick(self, now: float):
        pass

    def _emit_fail(self, event: LogEvent):
        verdict = Verdict(
            tc_id=self.d.tc_id,
            tc_name=self.d.tc_name,
            purpose=self.d.purpose,
            status=FAIL,
            start_time=event.stamp,
            end_time=event.stamp,
            exec_time=0.0,
            reason=f"FAIL 키워드 검출: {self.step.fail_keyword}",
            failed_step=f"STEP {self.step.step_no} ({self.step.method})",
            steps_log=[{
                "step": self.step.step_no,
                "method": self.step.method,
                "expected": self.step.keyword,
                "matched": event.clean[:400],
                "at": event.stamp.strftime("%H:%M:%S.%f")[:-3],
                "ok": False,
            }],
            context_before=(self.context_provider() if self.context_provider else []),
        )
        if self.console:
            self.console.verdict(verdict)
        if self.on_verdict:
            self.on_verdict(verdict, event)

    def to_verdict(self) -> Verdict:
        return Verdict(
            tc_id=self.d.tc_id,
            tc_name=self.d.tc_name,
            purpose=self.d.purpose,
            status=EVENT,
            start_time=self.first_at,
            end_time=self.last_at,
            exec_time=None,
            reason=f"{self.count}회 검출",
            steps_log=[],
            context_after=self.samples,
        )
