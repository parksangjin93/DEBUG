"""
Runner : 제품 하나에 대한 감시 파이프라인 한 세트.

  로그 소스 -> TCManager -> ReportGenerator

제품마다 Runner 를 하나씩 만들면 여러 제품을 동시에 감시할 수 있다.
각 Runner 는 자기 리포트 파일을 따로 만든다 (섞이지 않는다).
"""

from __future__ import annotations

from pathlib import Path

from .console import Console
from .log_source import (FileTailSource, FolderTailSource, ReplaySource,
                         detect_encoding)
from .profile import Profile
from .rule_loader import load_rules, select
from .tc_manager import TCManager

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from report.report_generator import ReportGenerator  # noqa: E402


class Runner:
    def __init__(self, profile: Profile, *, out_dir: str, verbose=False,
                 quiet=False, replay: str | None = None, heartbeat=30.0,
                 console=None):
        self.profile = profile
        self.heartbeat = heartbeat
        self.error: str = ""

        # ---------- 규칙 ----------
        if not profile.rules:
            raise ValueError(f"[{profile.name}] rules 가 지정되지 않았습니다.")
        for r in profile.rules:
            if not Path(r).exists():
                raise FileNotFoundError(f"[{profile.name}] 규칙 파일 없음: {r}")

        definitions, overridden = load_rules(profile.rules, product=profile.name)
        self.overridden = overridden

        if profile.all_tc:
            armed = definitions
        else:
            armed = select(
                definitions,
                tc_filter=profile.tc.split(",") if profile.tc else None,
                tag_filter=profile.tag.split(",") if profile.tag else None,
                name_filter=profile.tc_name.split(",") if profile.tc_name else None,
            )
        # VALUE 미입력(TODO) TC 는 실행하지 않는다. 무조건 안 잡히기 때문.
        self.todo = [d for d in armed if d.is_todo]
        armed = [d for d in armed if not d.is_todo]

        if not armed:
            raise ValueError(
                    f"[{profile.name}] 실행할 TC 가 없습니다."
                + (f" (선택한 {len(self.todo)}개는 VALUE 미입력 상태입니다)"
                   if self.todo else " tc/tag/name 설정을 확인하세요."))
        self.definitions = definitions
        self.armed = armed

        # ---------- 로그 소스 ----------
        if replay:
            path = Path(replay)
            enc = profile.encoding or detect_encoding(path)
            self.source = ReplaySource(path, encoding=enc)
            self.source_desc = f"REPLAY {path}"
            self.is_replay = True
        elif profile.log_file:
            path = Path(profile.log_file)
            if not path.is_file():
                raise FileNotFoundError(
                    f"[{profile.name}] 로그 파일이 없습니다: {path}")
            enc = profile.encoding or detect_encoding(path)
            self.source = FileTailSource(path, encoding=enc,
                                         from_start=profile.from_start)
            self.source_desc = f"FILE {path}"
            self.is_replay = False
        elif profile.log_dir:
            if not Path(profile.log_dir).is_dir():
                raise FileNotFoundError(
                    f"[{profile.name}] 로그 폴더가 없습니다: {profile.log_dir}\n"
                    f"       config/products.ini 의 log_dir 을 확인하세요.")
            enc = profile.encoding or "utf-8"
            self.source = FolderTailSource(profile.log_dir, pattern=profile.pattern,
                                           encoding=enc, from_start=profile.from_start)
            self.source_desc = f"DIR {profile.log_dir}"
            self.is_replay = False
        else:
            raise ValueError(
                f"[{profile.name}] log_dir 또는 log_file 이 필요합니다.")

        # ---------- 파이프라인 ----------
        # GUI 등 외부에서 콘솔을 주입할 수 있다 (같은 인터페이스면 무엇이든)
        self.console = console or Console(verbose=verbose, quiet=quiet,
                                          tag=profile.name)
        self.manager = TCManager(self.source.clock, self.console)
        for d in armed:
            self.manager.add(d)

        self.report = ReportGenerator(
            out_dir=(profile.out or out_dir),
            product=profile.name,
            log_source=self.source_desc,
            rule_file=", ".join(Path(r).name for r in profile.rules),
            tester=profile.tester,
            fw_version=profile.fw,
            run_tag=profile.tc or profile.tag or profile.tc_name
                    or ("ALL" if profile.all_tc else ""),
        )
        self.report.set_armed([d for d in armed if not d.is_event])
        self.manager.on_verdict = self.report.add

        if hasattr(self.source, "on_switch"):
            self.source.on_switch = lambda _p: self.manager.abort_running()

        self.source.log = self.console.out    # 소스 메시지에도 제품 태그를 붙인다
        self.source.add_line_callback(self.console.raw)
        self.source.add_line_callback(self.manager.process)
        self.source.add_tick_callback(self.manager.tick)

        if not self.is_replay and self.heartbeat:
            import time as _t
            state = {"last": _t.monotonic()}

            def _hb(_now):
                if _t.monotonic() - state["last"] >= self.heartbeat:
                    state["last"] = _t.monotonic()
                    self.console.heartbeat(self.manager)

            self.source.add_tick_callback(_hb)

    # ------------------------------------------------------------------
    def describe(self) -> list[str]:
        seq = len(self.manager.engines)
        evt = len(self.manager.watchers)
        lines = [
            f"규칙 : {', '.join(Path(r).name for r in self.profile.rules)}",
            f"소스 : {self.source_desc}",
            f"무장 : 시나리오 {seq}개 + 이벤트감시 {evt}개",
            f"출력 : {self.report.xlsx_path.name}",
        ]
        notes = [x for x in self.overridden if x.startswith("[주의]")]
        dupes = sorted({x for x in self.overridden if not x.startswith("[주의]")})
        if dupes:
            lines.append(f"덮어씀 : {', '.join(dupes)} (뒤 파일 우선)")
        lines.extend(notes)
        return lines

    def warnings(self) -> list[str]:
        return self.manager.validate()

    # ------------------------------------------------------------------
    def run(self):
        try:
            self.source.run()
        except FileNotFoundError as e:
            self.error = str(e)
            self.console.out(f"[오류] {e}")
        except Exception as e:                    # 한 제품이 죽어도 나머지는 계속
            self.error = f"{type(e).__name__}: {e}"
            self.console.out(f"[오류] 감시 중단 - {self.error}")
        finally:
            self.close()

    def stop(self):
        self.source.stop()

    def close(self):
        try:
            self.manager.finalize()
            self.report.save()
        except Exception as e:
            self.console.out(f"[경고] 리포트 저장 실패: {e}")

    def summary_line(self) -> str:
        c = self.console.counts
        tail = f"  ({self.error})" if self.error else ""
        return (f"{self.profile.name:<12} "
                + " / ".join(f"{k} {v}" for k, v in c.items())
                + f"   -> {self.report.xlsx_path.name}{tail}")
