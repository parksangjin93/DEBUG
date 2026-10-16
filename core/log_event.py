"""
로그 한 줄을 구조화하고, 판정에 쓸 '시계'를 제공한다.

핵심 개념
---------
- LogEvent : 원본 라인 + ANSI 제거된 라인 + 타임스탬프
- LineParser : ANSI/제어문자 제거, 라인 선두 타임스탬프 파싱
- Clock : 판정 기준 시각. 로그 타임스탬프가 있으면 그것을 기준으로 하고,
          로그가 잠시 끊긴 동안에는 실시간으로 외삽(extrapolate)한다.
          -> SecureCRT 버퍼링으로 인한 오차를 줄이면서, 무입력 구간에서도
             TIMEOUT 판정이 정상 동작한다.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# ANSI escape / 제어문자 제거
# ---------------------------------------------------------------------------
# SecureCRT 로그에는 색상/커서 제어 코드가 그대로 남는 경우가 많다.
# 이걸 지우지 않으면 "눈에는 보이는데 keyword in line 이 실패"하는 현상이 생긴다.
_ANSI_RE = re.compile(
    r"\x1b\[[0-9;?]*[ -/]*[@-~]"   # CSI 시퀀스
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC 시퀀스
    r"|\x1b[@-Z\\-_]"              # 2문자 이스케이프
    r"|[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]"  # 기타 제어문자 (\t \n \r 제외)
)


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text).replace("\r", "")


# ---------------------------------------------------------------------------
# 타임스탬프 파서
# ---------------------------------------------------------------------------
# SecureCRT: Session Options > Terminal > Log File > Custom log data
#            "On each line" 에 시각 포맷을 넣으면 모든 줄 앞에 시각이 붙는다.
# 아래는 대표적인 형태들을 지원한다. 어느 것도 안 맞으면 None 을 반환하고
# Clock 이 실시간(wall clock)으로 대체한다.
_TS_PATTERNS = [
    # [2026-07-22 10:46:32.123]  /  [2026-07-22 10:46:32]
    (re.compile(r"^\[?(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:[.,](\d{1,6}))?\]?"),
     "full"),
    # [07/22 10:46:32.123]  (월/일)
    (re.compile(r"^\[?(\d{2})/(\d{2})\s+(\d{2}):(\d{2}):(\d{2})(?:[.,](\d{1,6}))?\]?"),
     "monthday"),
    # [10:46:32.123]  /  10:46:32.123  /  [10:46:32]
    (re.compile(r"^\[?(\d{2}):(\d{2}):(\d{2})(?:[.,](\d{1,6}))?\]?"),
     "timeonly"),
]


def _frac_to_micro(frac: str | None) -> int:
    if not frac:
        return 0
    return int(frac.ljust(6, "0")[:6])


class LineParser:
    """라인 정제 + 타임스탬프 추출."""

    def __init__(self, base_date: datetime | None = None):
        # 시:분:초만 있는 포맷을 위해 날짜 기준이 필요하다.
        self.base_date = (base_date or datetime.now()).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        self._prev_ts: datetime | None = None

    def parse(self, raw: str) -> "LogEvent":
        text = strip_ansi(raw).strip()
        ts, body = self._parse_ts(text)
        return LogEvent(raw=raw, clean=body, ts=ts)

    # -- 내부 ---------------------------------------------------------------
    def _parse_ts(self, clean: str):
        """(datetime|None, 타임스탬프를 제거한 본문) 반환."""
        for pattern, kind in _TS_PATTERNS:
            m = pattern.match(clean)
            if not m:
                continue
            g = m.groups()
            try:
                if kind == "full":
                    ts = datetime(int(g[0]), int(g[1]), int(g[2]),
                                  int(g[3]), int(g[4]), int(g[5]),
                                  _frac_to_micro(g[6]))
                elif kind == "monthday":
                    ts = datetime(self.base_date.year, int(g[0]), int(g[1]),
                                  int(g[2]), int(g[3]), int(g[4]),
                                  _frac_to_micro(g[5]))
                else:  # timeonly
                    ts = self.base_date.replace(
                        hour=int(g[0]), minute=int(g[1]), second=int(g[2]),
                        microsecond=_frac_to_micro(g[3]),
                    )
            except ValueError:
                return None, clean

            # 자정 넘어감 처리 (시:분:초 포맷에서만 발생)
            if kind != "full" and self._prev_ts and ts < self._prev_ts - timedelta(hours=12):
                ts += timedelta(days=1)
                self.base_date += timedelta(days=1)

            self._prev_ts = ts
            return ts, clean[m.end():].strip()
        return None, clean


# ---------------------------------------------------------------------------
# LogEvent
# ---------------------------------------------------------------------------
@dataclass
class LogEvent:
    raw: str
    clean: str
    ts: datetime | None = None          # 로그에서 파싱된 시각 (없으면 None)
    recv_at: datetime = field(default_factory=datetime.now)  # 프로그램이 읽은 시각

    @property
    def stamp(self) -> datetime:
        """표시/기록용 시각. 로그 시각이 있으면 그것, 없으면 수신 시각."""
        return self.ts or self.recv_at

    def __contains__(self, needle: str) -> bool:
        return needle in self.clean


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
class Clock:
    """
    TIMEOUT 판정에 쓰는 시계.

    mode="live"   : 마지막 로그 시각을 기준점으로 삼고, 그 이후 흐른 실제 시간을
                    더해서 현재 시각을 계산한다. (로그가 끊겨도 시간이 흐름)
    mode="replay" : 저장된 로그를 재분석할 때. 오직 로그 시각만 사용하므로
                    같은 로그를 몇 번 돌려도 결과가 동일하다(결정론적).
    """

    def __init__(self, mode: str = "live"):
        self.mode = mode
        self._anchor_log: float | None = None
        self._anchor_mono: float = time.monotonic()
        self._last: float = time.time()

    def feed(self, event: LogEvent) -> None:
        if event.ts is not None:
            self._anchor_log = event.ts.timestamp()
            self._anchor_mono = time.monotonic()
        elif self.mode == "replay":
            # 리플레이인데 타임스탬프가 없으면 시간이 흐르지 않는다.
            # (TIMEOUT 판정 불가 -> loader/validator 에서 경고)
            pass
        self._last = self.now()

    def now(self) -> float:
        if self._anchor_log is None:
            return time.time()
        if self.mode == "replay":
            return self._anchor_log
        return self._anchor_log + (time.monotonic() - self._anchor_mono)

    def now_dt(self) -> datetime:
        return datetime.fromtimestamp(self.now())

    @property
    def has_log_time(self) -> bool:
        return self._anchor_log is not None
