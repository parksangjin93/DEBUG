"""
화면 출력.

사람이 옆에서 보고 있는 도구이므로, 원본 로그를 그대로 쏟아내지 않는다.
(그럴 거면 SecureCRT 를 보는 것과 다를 게 없다)
필요하면 --verbose 로 원본도 볼 수 있다.
"""

from __future__ import annotations

import sys
import threading
from datetime import datetime

from .verdict import EVENT, FAIL, INCOMPLETE, PASS, TIMEOUT


def _safe_stdout():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


_safe_stdout()

W = 74

# 여러 제품을 동시에 감시할 때 출력이 섞이지 않도록 하는 잠금
_PRINT_LOCK = threading.RLock()


class Console:
    def __init__(self, verbose=False, quiet=False, tag=""):
        self.verbose = verbose
        self.quiet = quiet
        self.tag = tag                       # 제품명 (다중 감시 시 구분용)
        self.counts = {PASS: 0, FAIL: 0, TIMEOUT: 0, INCOMPLETE: 0}

    # ------------------------------------------------------------------
    @property
    def p(self) -> str:
        return f"[{self.tag}] " if self.tag else ""

    def out(self, *lines):
        with _PRINT_LOCK:
            for line in lines:
                print(f"{self.p}{line}" if line else "")

    def banner(self, title, rows):
        self.out("=" * W, f" {title}", "=" * W)
        self.out(*[f"  {k:<12}: {v}" for k, v in rows])
        self.out("=" * W)

    def raw(self, event):
        if self.verbose:
            self.out(f"      | {event.clean}")

    # ------------------------------------------------------------------
    def tc_start(self, d, run_no):
        if self.quiet:
            return
        lines = ["", f"[START] {d.label}  (#{run_no})"]
        if d.purpose:
            lines.append(f"        {d.purpose}")
        self.out(*lines)

    def step_ok(self, d, step, n, total):
        if self.quiet:
            return
        method = f" {step.method}" if step.method else ""
        self.out(f"   OK   {d.tc_id} STEP {n}/{total}{method}  <- {step.keyword[:50]}")

    def event_hit(self, d, count, event):
        if self.quiet:
            return
        self.out(f"   ..   {d.tc_id} {d.tc_name} 검출 ({count}회)")

    def verdict(self, v):
        if v.status in self.counts:
            self.counts[v.status] += 1
        mark = {PASS: "PASS", FAIL: "FAIL", TIMEOUT: "TIME", INCOMPLETE: "INCP"}.get(v.status, v.status[:4])
        bar = {PASS: "#", FAIL: "!", TIMEOUT: "!", INCOMPLETE: "~"}.get(v.status, "-") * W
        took = f"{v.exec_time:.2f}s" if v.exec_time is not None else "-"
        lines = [bar, f" [{mark}] {v.tc_id} {v.tc_name}   ({took})"]
        if v.reason:
            lines.append(f"        사유 : {v.reason}")
        if v.failed_step:
            lines.append(f"        위치 : {v.failed_step}")
        lines.append(bar)
        lines.append(f" 누계  PASS {self.counts[PASS]} / FAIL {self.counts[FAIL]}"
                     f" / TIMEOUT {self.counts[TIMEOUT]}")
        self.out(*lines)

    def heartbeat(self, manager):
        if self.quiet:
            return
        now = datetime.now().strftime("%H:%M:%S")
        running = manager.status_lines()
        if running:
            self.out("", f"-- {now} 진행 중 --", *[f"   {x}" for x in running])
        else:
            self.out(f"-- {now} 대기 중 (무장 TC {len(manager.definitions)}개) --")
