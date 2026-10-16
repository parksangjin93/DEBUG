"""
분석기 자체 검증 (pytest 불필요).

    python tools/selftest.py

가짜 로그를 리플레이해서 '나와야 할 판정'이 실제로 나오는지 확인한다.
룰이나 엔진을 수정한 뒤 이걸 먼저 돌리면, 실제 장비 없이 회귀를 잡을 수 있다.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from core.log_source import ReplaySource            # noqa: E402
from core.rule_loader import RuleLoader, select     # noqa: E402
from core.tc_manager import TCManager               # noqa: E402

# (TC_ID, 기대 상태, 기대 횟수)
EXPECTED = [
    ("TC001", "PASS", 1),
    ("TC001", "FAIL", 1),
    ("TC001", "TIMEOUT", 1),
    ("TC002", "PASS", 1),
    ("TC003", "PASS", 1),
    ("TC004", "PASS", 1),
    ("TC005", "PASS", 1),
    ("TC006", "INCOMPLETE", 1),   # TC004와 시작 트리거가 같아 잘못 시작됨 (룰 결함 감지)
    ("TC026", "FAIL", 1),         # Redmine #9604 회귀
]


ABSENT_RULES = """TC_ID,TC_NAME,TEST_PURPOSE,STEP,TEST_METHOD,TYPE,VALUE,FAIL,TIMEOUT,MATCH,TAG
TC900,Boot_No_Reboot,부팅 중 재부팅 없이 완료,1,부트로더 시작,CHECK,U-Boot 2019,,,CONTAINS,boot
TC900,Boot_No_Reboot,부팅 중 재부팅 없이 완료,2,30초간 재부팅 미발생,ABSENT,U-Boot 2019,,30,CONTAINS,boot
TC900,Boot_No_Reboot,부팅 중 재부팅 없이 완료,3,앱 부팅 완료,CHECK,BOOT COMPLETE,,60,CONTAINS,boot
TC901,Todo_Sample,VALUE 미입력 예시,1,아직 안 채움,CHECK,TODO_STEP1,,,CONTAINS,todo
"""

ABSENT_CASES = [
    ("정상(재부팅 없음)", [(0, "U-Boot 2019.04"), (2, "Starting kernel"),
                     (20, "dvr: BOOT COMPLETE"), (45, "idle")], "PASS"),
    ("부팅 중 재부팅", [(0, "U-Boot 2019.04"), (2, "Starting kernel"),
                   (9, "U-Boot 2019.04"), (30, "dvr: BOOT COMPLETE")], "FAIL"),
    ("부팅 미완료", [(0, "U-Boot 2019.04"), (2, "Starting kernel"),
                 (90, "nothing"), (120, "idle")], "TIMEOUT"),
]


def run_absent() -> int:
    """ABSENT(금지 문구 감시) 와 TODO(미입력) 동작 검증."""
    from datetime import datetime, timedelta
    tmp = Path(tempfile.gettempdir())
    rules = tmp / "selftest_absent.csv"
    rules.write_text(ABSENT_RULES, encoding="utf-8-sig")

    defs_all, _ = RuleLoader(rules).load(), None
    todo = [d for d in RuleLoader(rules).load() if d.is_todo]
    fails = []
    if len(todo) != 1:
        fails.append(f"  TODO TC 감지 실패: 기대 1개, 실제 {len(todo)}개")

    base = datetime(2026, 7, 22, 11, 0, 0)
    for label, lines, expect in ABSENT_CASES:
        log = tmp / "selftest_absent.log"
        log.write_text("\n".join(
            f"[{(base + timedelta(seconds=o)).strftime('%H:%M:%S.%f')[:-3]}] {t}"
            for o, t in lines) + "\n", encoding="utf-8")

        defs = [d for d in RuleLoader(rules).load() if not d.is_todo]
        source = ReplaySource(log)
        manager = TCManager(source.clock, console=None)
        for d in defs:
            manager.add(d)
        got = []
        manager.on_verdict = lambda v: got.append(v.status)
        source.add_line_callback(manager.process)
        source.add_tick_callback(manager.tick)
        source.run()
        manager.finalize()
        if expect not in got:
            fails.append(f"  ABSENT [{label}] 기대 {expect}, 실제 {got}")

    if fails:
        print(" ABSENT/TODO 검증 실패")
        for f in fails:
            print(f)
        return 1
    print(f" ABSENT/TODO 검증 통과 ({len(ABSENT_CASES)}개 시나리오 + TODO 감지)")
    return 0


def run() -> int:
    log_path = Path(tempfile.gettempdir()) / "[2026-07-22-10시46분32초].log"
    gen = subprocess.run([sys.executable, str(BASE / "tools" / "make_test_log.py")],
                         capture_output=True, text=True, check=True)
    log_path.write_text(gen.stdout, encoding="utf-8")

    defs = RuleLoader(BASE / "tc" / "tc_rules.csv").load()
    armed = select(defs, tc_filter=[f"TC{n:03d}" for n in list(range(1, 10)) + [26]])

    source = ReplaySource(log_path)
    manager = TCManager(source.clock, console=None)
    for d in armed:
        manager.add(d)

    got: list = []
    manager.on_verdict = lambda v: got.append((v.tc_id, v.status))

    source.add_line_callback(manager.process)
    source.add_tick_callback(manager.tick)
    source.run()
    manager.finalize()

    actual = Counter(got)
    failures = []
    for tc_id, status, count in EXPECTED:
        if actual[(tc_id, status)] != count:
            failures.append(
                f"  기대 {tc_id} {status} x{count}  ->  실제 {actual[(tc_id, status)]}")

    print("\n" + "=" * 60)
    if failures:
        print(" SELFTEST 실패")
        print("=" * 60)
        for f in failures:
            print(f)
        print("\n 실제 판정 전체:")
        for (tc, st), n in sorted(actual.items()):
            print(f"   {tc} {st} x{n}")
        return 1
    print(f" SELFTEST 통과 ({len(EXPECTED)}개 기대 판정 일치)")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    rc = run()
    rc |= run_absent()
    sys.exit(rc)
