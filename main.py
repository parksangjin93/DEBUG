"""
QA Automation - 실시간 로그 판정기

제품별 프로파일(config/products.ini)로 로그 폴더와 TC 파일을 따로 관리한다.

사용 예
-------
  python main.py --products                     # 등록된 제품 목록
  python main.py -p XVM508                      # 제품 하나 감시
  python main.py -p XVM508 --tc TC002           # TC 만 덮어쓰기
  python main.py -p XVM508,KP2S                 # 여러 제품 동시 감시
  python main.py -p XVM508 --list               # 그 제품의 TC 목록
  python main.py -p XVM508 --replay "...\\a.log"  # 저장된 로그 재분석

  # 프로파일 없이 즉석 실행
  python main.py --log-dir "D:\\LOG\\XVM508" --rules tc\\XVM508.csv --tc TC002

종료: Ctrl+C  (종료 시 리포트가 자동 저장됩니다)
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
from pathlib import Path

from core.profile import Profile, ProfileStore
from core.rule_loader import load_rules
from core.runner import Runner

BASE_DIR = Path(__file__).resolve().parent
PRODUCTS_INI = BASE_DIR / "config" / "products.ini"
W = 74


def parse_args():
    p = argparse.ArgumentParser(
        description="임베디드 디버그 로그 실시간 PASS/FAIL 판정기 (제품별 프로파일 지원)",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)

    prod = p.add_argument_group("제품 프로파일")
    prod.add_argument("-p", "--product",
                      help="config/products.ini 의 제품명. 쉼표로 여러 개 동시 감시")
    prod.add_argument("--products", action="store_true", help="등록된 제품 목록 출력")
    prod.add_argument("--check", action="store_true",
                      help="설정 진단 (경로/규칙/TC 선택이 올바른지 검사)")
    prod.add_argument("--config", default=str(PRODUCTS_INI), help="프로파일 파일 경로")

    src = p.add_argument_group("로그 소스 (프로파일 미사용 / 덮어쓰기)")
    src.add_argument("--log-dir", help="감시할 폴더. 가장 최근 파일 자동 추적")
    src.add_argument("--log-file", help="특정 파일 하나만 감시")
    src.add_argument("--replay", help="저장된 로그를 처음부터 재분석 후 종료")
    src.add_argument("--pattern", help="폴더 감시 파일 패턴 (기본 *.log)")
    src.add_argument("--from-start", action="store_true", help="기존 내용도 처음부터")
    src.add_argument("--encoding", help="로그 인코딩 강제 (utf-8 / cp949)")

    sel = p.add_argument_group("TC 선택 (지정 시 프로파일 값을 덮어씀)")
    sel.add_argument("--rules", help="TC 규칙 파일. 쉼표로 여러 개 병합 가능")
    sel.add_argument("--tc", help="TC_ID 선택. 쉼표 구분")
    sel.add_argument("--tag", help="태그 선택. 쉼표 구분")
    sel.add_argument("--name", help="TC_NAME 부분일치 선택")
    sel.add_argument("--all", action="store_true", help="전체 TC 무장 (오탐 주의)")
    sel.add_argument("--list", action="store_true", help="TC 목록만 출력하고 종료")

    meta = p.add_argument_group("기타")
    meta.add_argument("--out", default=str(BASE_DIR / "output"), help="리포트 출력 폴더")
    meta.add_argument("--tester", help="테스터 이름")
    meta.add_argument("--fw", help="FW 버전")
    meta.add_argument("--verbose", action="store_true", help="원본 로그도 출력")
    meta.add_argument("--quiet", action="store_true", help="판정 결과만 출력")
    return p.parse_args()


# ---------------------------------------------------------------------------
def build_profiles(args, store: ProfileStore) -> list[Profile]:
    """프로파일 + CLI 덮어쓰기를 합쳐 최종 실행 대상을 만든다."""
    if args.product:
        names = [n.strip() for n in args.product.split(",") if n.strip()]
        profiles = []
        for n in names:
            try:
                profiles.append(store.get(n))
            except KeyError:
                raise SystemExit(
                    f"[오류] 프로파일에 '{n}' 이 없습니다.\n"
                    f"       등록된 제품: {', '.join(store.names()) or '(없음)'}\n"
                    f"       파일: {store.path}")
    else:
        profiles = [Profile(name="")]

    # CLI 인자는 프로파일보다 우선
    for prof in profiles:
        if args.log_dir:
            prof.log_dir, prof.log_file = args.log_dir, ""
        if args.log_file:
            prof.log_file, prof.log_dir = args.log_file, ""
        if args.pattern:
            prof.pattern = args.pattern
        if args.rules:
            prof.rules = []
            for r in args.rules.split(","):
                r = ProfileStore.normalize(r.strip())
                if not r:
                    continue
                path = Path(r)
                prof.rules.append(str(path if path.is_absolute() else BASE_DIR / path))
        if args.tc:
            prof.tc, prof.tag, prof.tc_name, prof.all_tc = args.tc, "", "", False
        if args.tag:
            prof.tag, prof.tc, prof.tc_name, prof.all_tc = args.tag, "", "", False
        if args.name:
            prof.tc_name, prof.tc, prof.tag, prof.all_tc = args.name, "", "", False
        if args.all:
            prof.all_tc, prof.tc, prof.tag, prof.tc_name = True, "", "", ""
        if args.from_start:
            prof.from_start = True
        if args.encoding:
            prof.encoding = args.encoding
        if args.tester:
            prof.tester = args.tester
        if args.fw:
            prof.fw = args.fw
        if not prof.rules:
            prof.rules = [str(BASE_DIR / "tc" / "tc_rules.csv")]
    return profiles


def print_products(store: ProfileStore):
    if not store:
        print(f"등록된 제품이 없습니다. 설정 파일: {store.path}")
        print("config/products.ini 를 만들고 제품을 등록하세요. (README 참고)")
        return
    print(f"설정 파일: {store.path}\n")
    print(f"{'제품':<12} {'규칙파일':<28} {'무장 TC':<18} 로그 위치")
    print("-" * 100)
    for name in store.names():
        print(store.get(name).describe())
    print("-" * 100)
    print(f"총 {len(store.names())}개")


def run_check(args, store: ProfileStore) -> int:
    """설정 진단. 실행하지 않고 문제만 찾아서 알려준다."""
    ok, ng = 0, 0
    print("=" * W)
    print(" 설정 진단")
    print("=" * W)

    # 실행 환경
    print(f" Python      : {sys.version.split()[0]}  ({sys.executable})")
    try:
        import openpyxl
        print(f" openpyxl    : {openpyxl.__version__}")
    except ImportError:
        print(" openpyxl    : [NG] 미설치  ->  pip install openpyxl")
        ng += 1
    print(f" 프로그램 폴더 : {BASE_DIR}")
    print(f" 설정 파일    : {store.path}"
          f"{'' if store.path.exists() else '   [NG] 파일 없음'}")
    print("-" * W)

    if not store:
        print(" 등록된 제품이 없습니다. config/products.ini 를 작성하세요.")
        return 1

    targets = ([store.get(n.strip()) for n in args.product.split(",")]
               if args.product else [store.get(n) for n in store.names()])

    for prof in targets:
        print(f"\n [{prof.name}]")
        problems = []

        # 로그 소스
        if prof.log_dir:
            path = Path(ProfileStore.normalize(prof.log_dir))
            if path.is_dir():
                found = sorted(path.glob(prof.pattern),
                               key=lambda x: x.stat().st_mtime, reverse=True)
                print(f"   log_dir  : OK  {path}")
                if found:
                    print(f"              최근 파일 {len(found)}개, "
                          f"가장 최근: {found[0].name}")
                else:
                    print(f"              [주의] '{prof.pattern}' 에 맞는 파일이 없습니다."
                          f" (파일이 생기면 자동으로 잡습니다)")
            else:
                problems.append(f"log_dir 폴더 없음: {path}")
        elif prof.log_file:
            path = Path(ProfileStore.normalize(prof.log_file))
            if path.is_file():
                print(f"   log_file : OK  {path}")
            else:
                problems.append(f"log_file 없음: {path}")
        else:
            problems.append("log_dir 또는 log_file 이 지정되지 않음")

        # 규칙 파일
        if not prof.rules:
            problems.append("rules 가 지정되지 않음")
        for r in prof.rules:
            if Path(r).exists():
                print(f"   rules    : OK  {r}")
            else:
                problems.append(f"규칙 파일 없음: {r}")

        # TC 선택
        if not problems:
            try:
                defs, notes = load_rules(prof.rules, product=prof.name)
                from core.rule_loader import select
                armed = defs if prof.all_tc else select(
                    defs,
                    tc_filter=prof.tc.split(",") if prof.tc else None,
                    tag_filter=prof.tag.split(",") if prof.tag else None,
                    name_filter=prof.tc_name.split(",") if prof.tc_name else None)
                if armed:
                    print(f"   TC       : OK  전체 {len(defs)}개 중 {len(armed)}개 무장")
                else:
                    problems.append(
                        f"선택된 TC 가 0개 (tc={prof.tc} tag={prof.tag} name={prof.tc_name})")
                for n in notes:
                    print(f"   {n}")
            except Exception as e:
                problems.append(f"규칙 로드 실패: {e}")

        if problems:
            ng += 1
            for msg in problems:
                print(f"   [NG] {msg}")
        else:
            ok += 1
            print("   -> 실행 가능")

    print("\n" + "=" * W)
    print(f" 정상 {ok}개 / 문제 {ng}개")
    print("=" * W)
    return 0 if ng == 0 else 1


def print_tc_list(profiles):
    for prof in profiles:
        defs, _ = load_rules(prof.rules, product=prof.name)
        title = f"[{prof.name}] " if prof.name else ""
        print(f"\n{title}{', '.join(Path(r).name for r in prof.rules)}")
        print(f"{'TC_ID':<8}{'MODE':<10}{'STEP':<6}{'TC_NAME':<26}TEST_PURPOSE")
        print("-" * 100)
        for d in defs:
            mode = "EVENT" if d.is_event else "SEQUENCE"
            print(f"{d.tc_id:<8}{mode:<10}{len(d.steps):<6}"
                  f"{d.tc_name[:25]:<26}{d.purpose[:44]}")
        print("-" * 100)
        print(f"총 {len(defs)}개")


# ---------------------------------------------------------------------------
def main():
    args = parse_args()
    store = ProfileStore(args.config, BASE_DIR)

    if args.products:
        print_products(store)
        return 0

    if args.check:
        return run_check(args, store)

    if not (args.product or args.log_dir or args.log_file or args.replay or args.list):
        print("[오류] -p(제품) 또는 --log-dir / --log-file / --replay 가 필요합니다.")
        print("       등록된 제품 보기: python main.py --products")
        return 1

    profiles = build_profiles(args, store)

    if args.list:
        print_tc_list(profiles)
        return 0

    if args.replay and len(profiles) > 1:
        print("[오류] --replay 는 제품 하나씩만 가능합니다.")
        return 1

    # ---------------- Runner 생성 ----------------
    runners: list[Runner] = []
    for prof in profiles:
        try:
            runners.append(Runner(prof, out_dir=args.out, verbose=args.verbose,
                                  quiet=args.quiet, replay=args.replay))
        except (ValueError, FileNotFoundError) as e:
            print(f"[오류] {e}")
            return 1

    # ---------------- 배너 ----------------
    print("=" * W)
    print(" QA Automation - Log Judge")
    print("=" * W)
    for r in runners:
        head = f" {r.profile.name}" if r.profile.name else " (프로파일 없음)"
        print(head)
        for line in r.describe():
            print(f"   {line}")
        for d in r.armed:
            kind = "EVENT" if d.is_event else f"{len(d.steps)}step"
            print(f"     - {d.tc_id:<7} [{kind:<6}] {d.tc_name}")
        warns = r.warnings()
        if warns:
            print("   " + "!" * 60)
            print("   룰 충돌 경고 (오탐 가능)")
            for w in warns:
                print(f"   [!] {w}")
            print("   " + "!" * 60)
        print("-" * W)

    print("\n종료하려면 Ctrl+C\n")

    # ---------------- 실행 ----------------
    stopping = {"once": False}

    def _on_sigint(_sig, _frm):
        if stopping["once"]:
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            return
        stopping["once"] = True
        print("\n\n사용자 중지 요청 (Ctrl+C) - 리포트 저장 중...")
        for r in runners:
            r.stop()

    try:
        signal.signal(signal.SIGINT, _on_sigint)
    except (ValueError, AttributeError):
        pass

    if len(runners) == 1:
        runners[0].run()
    else:
        threads = [threading.Thread(target=r.run, name=r.profile.name, daemon=True)
                   for r in runners]
        for t in threads:
            t.start()
        try:
            for t in threads:
                while t.is_alive():
                    t.join(timeout=0.3)
        except KeyboardInterrupt:
            _on_sigint(None, None)
            for t in threads:
                t.join(timeout=10)

    # ---------------- 마무리 ----------------
    print("\n" + "=" * W)
    print(" 감시 종료")
    print("=" * W)
    for r in runners:
        print(" " + r.summary_line())
    print("=" * W)
    return 1 if any(r.error for r in runners) else 0


if __name__ == "__main__":
    sys.exit(main())
