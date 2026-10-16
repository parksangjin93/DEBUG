"""TC 정의 모델 (Step / TCDefinition)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


class Matcher:
    """
    문자열 매칭기.
      mode="CONTAINS" : 부분 문자열 (기본, 기존 TC 그대로 동작)
      mode="REGEX"    : 정규식. 캡처 그룹은 evidence 에 기록된다.
    """

    __slots__ = ("pattern", "mode", "_re")

    def __init__(self, pattern: str, mode: str = "CONTAINS"):
        self.pattern = pattern or ""
        self.mode = (mode or "CONTAINS").upper()
        self._re = re.compile(self.pattern) if self.mode == "REGEX" else None

    def match(self, text: str):
        """매칭되면 dict(캡처값) 또는 {} 를 반환, 아니면 None."""
        if not self.pattern:
            return None
        if self._re is not None:
            m = self._re.search(text)
            if not m:
                return None
            return m.groupdict() or {}
        return {} if self.pattern in text else None

    def __bool__(self):
        return bool(self.pattern)

    def __str__(self):
        return self.pattern


@dataclass
class Step:
    step_no: int
    keyword: str                     # 통과 조건 (ABSENT 면 '나오면 안 되는' 문구)
    fail_keyword: str | None = None  # 이게 나오면 즉시 FAIL
    timeout: float | None = None     # 이전 STEP 완료 후 이 시간 안에 나와야 함
    method: str = ""                 # TEST_METHOD (사람이 읽는 설명)
    match_mode: str = "CONTAINS"
    step_type: str = "CHECK"         # CHECK | ABSENT

    matcher: Matcher = field(init=False)
    fail_matcher: Matcher = field(init=False)

    def __post_init__(self):
        self.step_type = (self.step_type or "CHECK").upper()
        self.matcher = Matcher(self.keyword, self.match_mode)
        self.fail_matcher = Matcher(self.fail_keyword or "", self.match_mode)

    @property
    def is_absent(self) -> bool:
        """
        ABSENT 스텝 : TIMEOUT 시간 동안 이 문구가 '나오지 않아야' 통과.
        예) 부팅 중 재부팅/커널 panic 이 없어야 한다
        """
        return self.step_type == "ABSENT"

    def describe(self) -> str:
        if self.is_absent:
            return f"{self.timeout}초 동안 미발생: {self.keyword}"
        return self.keyword


@dataclass
class TCDefinition:
    tc_id: str
    tc_name: str
    purpose: str = ""
    steps: list[Step] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    mode: str = "SEQUENCE"     # SEQUENCE | EVENT
    cooldown: float = 10.0     # EVENT 모드에서 같은 이벤트 재기록 최소 간격(초)
    note: str = ""

    @property
    def label(self) -> str:
        return f"{self.tc_id} {self.tc_name}"

    @property
    def is_todo(self) -> bool:
        """VALUE 가 아직 채워지지 않은 초안 TC (로그 키워드 미입력)."""
        return any(st.keyword.strip().upper().startswith("TODO")
                   for st in self.steps)

    @property
    def todo_count(self) -> int:
        return sum(1 for st in self.steps
                   if st.keyword.strip().upper().startswith("TODO"))

    @property
    def is_event(self) -> bool:
        # 스텝이 1개뿐이면 '테스트'가 아니라 '이벤트 감지'로 취급한다.
        # 이렇게 하지 않으면 RECORD ON(SD) 같은 게 뜰 때마다 PASS 행이 쌓여
        # 리포트를 쓸 수 없게 된다.
        return (self.mode.upper() == "EVENT"
                or (len(self.steps) <= 1 and not self.is_todo))
