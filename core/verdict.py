"""판정 결과 모델."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

PASS = "PASS"
FAIL = "FAIL"
TIMEOUT = "TIMEOUT"
NOT_EXECUTED = "NOT_EXECUTED"
INCOMPLETE = "INCOMPLETE"
EVENT = "EVENT"

STATUS_ORDER = [PASS, FAIL, TIMEOUT, INCOMPLETE, NOT_EXECUTED, EVENT]


@dataclass
class Verdict:
    tc_id: str
    tc_name: str
    status: str
    start_time: datetime | None = None
    end_time: datetime | None = None
    exec_time: float | None = None
    reason: str = ""
    failed_step: str = ""
    purpose: str = ""

    # 근거
    steps_log: list[dict] = field(default_factory=list)  # 스텝별 매칭 기록
    context_before: list[str] = field(default_factory=list)
    context_after: list[str] = field(default_factory=list)

    def evidence_text(self) -> str:
        """엑셀 EVIDENCE 셀 / Redmine 붙여넣기용 텍스트."""
        parts = []
        if self.steps_log:
            parts.append("[STEP 판정 결과]")
            for s in self.steps_log:
                mark = "OK  " if s.get("ok") else "NG  "
                parts.append(f"{mark}STEP {s['step']}  ({s.get('method','')})")
                parts.append(f"     기대 : {s['expected']}")
                parts.append(f"     매칭 : {s.get('matched','(없음)')}")
                if s.get("at"):
                    parts.append(f"     시각 : {s['at']}")
            parts.append("")
        if self.context_before or self.context_after:
            parts.append("[전후 로그]")
            parts.extend(self.context_before)
            parts.append(">>>>>>>>>> 판정 지점 <<<<<<<<<<")
            parts.extend(self.context_after)
        return "\n".join(parts)
