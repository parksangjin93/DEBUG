"""
QA Automation - GUI

    python qa_gui.py       (또는 run_gui.bat 더블클릭)

CLI(main.py)와 완전히 같은 엔진을 쓴다. GUI 는 껍데기일 뿐이라
여기서 저장한 설정은 CLI 에서도 그대로 동작한다 (config/products.ini 공유).

필요한 것: Python 3.10+, openpyxl, tkinter(윈도우 파이썬에 기본 포함)
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from core.profile import Profile, ProfileStore          # noqa: E402
from core.rule_loader import load_rules, select         # noqa: E402
from core.runner import Runner                          # noqa: E402
from core.verdict import (EVENT, FAIL, INCOMPLETE, PASS,  # noqa: E402
                          TIMEOUT)

PRODUCTS_INI = BASE_DIR / "config" / "products.ini"
OUT_DIR = BASE_DIR / "output"

CHECKED, UNCHECKED = "☑", "☐"

COLORS = {
    PASS: "#0a7f2e",
    FAIL: "#c0261c",
    TIMEOUT: "#b5730a",
    INCOMPLETE: "#8a5a00",
    EVENT: "#1f4e79",
    "info": "#333333",
    "muted": "#777777",
    "warn": "#b5730a",
    "step": "#1f4e79",
}


# ===========================================================================
# GUI 로 출력을 보내는 콘솔 (Console 과 같은 인터페이스)
# ===========================================================================
class GuiConsole:
    def __init__(self, q: queue.Queue, tag: str = ""):
        self.q = q
        self.tag = tag
        self.verbose = False
        self.quiet = False
        self.counts = {PASS: 0, FAIL: 0, TIMEOUT: 0, INCOMPLETE: 0}

    def _put(self, text, style="info"):
        self.q.put(("log", text, style))

    # -- Console 인터페이스 -------------------------------------------
    def out(self, *lines):
        for line in lines:
            if line and not set(str(line)) <= {"=", "-", "!", "#", "~", " "}:
                self._put(str(line).rstrip(), "muted")

    def banner(self, title, rows):
        self._put(title, "info")
        for k, v in rows:
            self._put(f"   {k} : {v}", "muted")

    def raw(self, event):
        if self.verbose:
            self._put(f"    | {event.clean}", "muted")

    def tc_start(self, d, run_no):
        self._put(f"▶ [START] {d.tc_id} {d.tc_name}  (#{run_no})", "step")

    def step_ok(self, d, step, n, total):
        method = f"  {step.method}" if step.method else ""
        self._put(f"    OK  {d.tc_id}  STEP {n}/{total}{method}", "step")

    def event_hit(self, d, count, event):
        self._put(f"    ·   {d.tc_id} {d.tc_name} 검출 ({count}회)", "muted")

    def verdict(self, v):
        if v.status in self.counts:
            self.counts[v.status] += 1
        took = f"{v.exec_time:.2f}s" if v.exec_time is not None else "-"
        self._put(f"■ [{v.status}] {v.tc_id} {v.tc_name}   ({took})", v.status)
        if v.reason:
            self._put(f"      사유 : {v.reason}", v.status)
        if v.failed_step:
            self._put(f"      위치 : {v.failed_step}", v.status)
        self.q.put(("counts", dict(self.counts), None))

    def heartbeat(self, manager):
        pass


# ===========================================================================
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("QA Automation - 로그 판정기")
        # 화면보다 큰 창이 뜨지 않도록 제한 (노트북/저해상도 대응)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = min(1180, sw - 80), min(820, sh - 100)
        self.geometry(f"{max(900, w)}x{max(620, h)}")
        self.minsize(900, 560)

        self.store = ProfileStore(PRODUCTS_INI, BASE_DIR)
        self.q: queue.Queue = queue.Queue()
        self.runner: Runner | None = None
        self.thread: threading.Thread | None = None
        self.definitions = []
        self.current_name = ""

        self._setup_style()
        self._build()
        self._refresh_products()
        self.after(100, self._drain)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    def _setup_style(self):
        family = "Malgun Gothic"
        try:
            import tkinter.font as tkfont
            if family not in tkfont.families():
                family = tkfont.nametofont("TkDefaultFont").actual("family")
        except Exception:
            family = None
        self.base_font = (family, 10) if family else None
        self.mono_font = (family or "Courier", 9)
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        if self.base_font:
            style.configure(".", font=self.base_font)
            style.configure("Treeview", rowheight=22)

    # ------------------------------------------------------------------
    def _build(self):
        pad = dict(padx=6, pady=3)

        # ================================================================
        # pack 순서가 중요하다.
        # 아래쪽 고정 바(실행 버튼/상태바)를 side="bottom" 으로 **먼저** 배치하고,
        # 늘어나는 영역(TC 목록 / 진행 상황)을 마지막에 expand 로 채운다.
        # 순서를 반대로 하면 창이 작을 때 버튼 줄이 화면 밖으로 밀려난다.
        # ================================================================

        # ---------------- 제품 선택 (위 고정) ----------------
        top = ttk.LabelFrame(self, text=" 제품 ")
        top.pack(side="top", fill="x", padx=8, pady=(8, 4))

        self.cb_product = ttk.Combobox(top, state="readonly", width=24)
        self.cb_product.grid(row=0, column=0, **pad)
        self.cb_product.bind("<<ComboboxSelected>>", lambda e: self._load_product())

        ttk.Button(top, text="새 제품", command=self._new_product).grid(row=0, column=1, **pad)
        ttk.Button(top, text="설정 저장", command=self._save_product).grid(row=0, column=2, **pad)
        ttk.Button(top, text="삭제", command=self._delete_product).grid(row=0, column=3, **pad)
        ttk.Separator(top, orient="vertical").grid(row=0, column=4, sticky="ns", padx=10)
        ttk.Label(top, text="제품명").grid(row=0, column=5, **pad)
        self.e_name = ttk.Entry(top, width=18)
        self.e_name.grid(row=0, column=6, **pad)
        ttk.Label(top, text="테스터").grid(row=0, column=7, **pad)
        self.e_tester = ttk.Entry(top, width=12)
        self.e_tester.grid(row=0, column=8, **pad)
        ttk.Label(top, text="FW").grid(row=0, column=9, **pad)
        self.e_fw = ttk.Entry(top, width=14)
        self.e_fw.grid(row=0, column=10, **pad)

        # ---------------- 경로 설정 (위 고정) ----------------
        cfg = ttk.LabelFrame(self, text=" 로그 / TC 설정 ")
        cfg.pack(side="top", fill="x", padx=8, pady=4)
        cfg.columnconfigure(1, weight=1)

        ttk.Label(cfg, text="디버그 로그 폴더").grid(row=0, column=0, sticky="w", **pad)
        self.e_logdir = ttk.Entry(cfg)
        self.e_logdir.grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(cfg, text="폴더 선택", command=self._pick_logdir).grid(row=0, column=2, **pad)
        ttk.Label(cfg, text="패턴").grid(row=0, column=3, **pad)
        self.e_pattern = ttk.Entry(cfg, width=10)
        self.e_pattern.insert(0, "*.log")
        self.e_pattern.grid(row=0, column=4, **pad)

        ttk.Label(cfg, text="TC 규칙 파일").grid(row=1, column=0, sticky="nw", **pad)
        rule_box = ttk.Frame(cfg)
        rule_box.grid(row=1, column=1, sticky="ew", **pad)
        rule_box.columnconfigure(0, weight=1)
        self.lb_rules = tk.Listbox(rule_box, height=2, exportselection=False,
                                   font=self.mono_font)
        self.lb_rules.grid(row=0, column=0, sticky="ew")
        sb = ttk.Scrollbar(rule_box, orient="vertical", command=self.lb_rules.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.lb_rules.configure(yscrollcommand=sb.set)

        btns = ttk.Frame(cfg)
        btns.grid(row=1, column=2, columnspan=3, sticky="nw", **pad)
        ttk.Button(btns, text="파일 추가", command=self._add_rule).pack(fill="x", pady=1)
        ttk.Button(btns, text="선택 제거", command=self._remove_rule).pack(fill="x", pady=1)
        ttk.Button(btns, text="TC 다시 읽기", command=self._reload_tcs).pack(fill="x", pady=1)

        hint = ("여러 개를 넣으면 위에서부터 병합됩니다 "
                "(공통 TC 먼저, 제품 전용 TC 나중에 / 같은 TC_ID 는 아래쪽이 우선)")
        ttk.Label(cfg, text=hint, foreground="#777").grid(
            row=2, column=1, columnspan=4, sticky="w", padx=6)

        # ---------------- 상태바 (맨 아래 고정) ----------------
        self.status = ttk.Label(self, text="", anchor="w", relief="sunken")
        self.status.pack(side="bottom", fill="x")

        # ---------------- 실행 버튼 (아래 고정) ----------------
        run = ttk.Frame(self)
        run.pack(side="bottom", fill="x", padx=8, pady=6)

        self.btn_start = ttk.Button(run, text="  ▶  감시 시작  ", command=self._start)
        self.btn_start.pack(side="left", padx=3)
        self.btn_stop = ttk.Button(run, text="  ■  중지  ", command=self._stop,
                                   state="disabled")
        self.btn_stop.pack(side="left", padx=3)
        ttk.Button(run, text="저장된 로그 재분석",
                   command=self._replay).pack(side="left", padx=3)
        ttk.Button(run, text="리포트 폴더 열기",
                   command=self._open_out).pack(side="left", padx=3)
        self.var_verbose = tk.BooleanVar(value=False)
        ttk.Checkbutton(run, text="원본 로그도 표시", variable=self.var_verbose,
                        command=self._toggle_verbose).pack(side="left", padx=12)

        big = (self.base_font[0] if self.base_font else None, 11, "bold")
        self.lb_counts = ttk.Label(
            run, text="PASS 0   FAIL 0   TIMEOUT 0   INCOMPLETE 0", font=big)
        self.lb_counts.pack(side="right", padx=8)

        # ---------------- 늘어나는 영역 (맨 마지막에 배치) ----------------
        self.paned = ttk.PanedWindow(self, orient="vertical")
        self.paned.pack(side="top", fill="both", expand=True, padx=8, pady=4)

        # TC 목록
        tcf = ttk.LabelFrame(self.paned, text=" 판정할 TC 선택 (체크한 것만 감시합니다) ")
        self.paned.add(tcf, weight=3)

        bar = ttk.Frame(tcf)
        bar.pack(fill="x", padx=6, pady=4)
        ttk.Button(bar, text="전체 선택",
                   command=lambda: self._check_all(True)).pack(side="left", padx=2)
        ttk.Button(bar, text="전체 해제",
                   command=lambda: self._check_all(False)).pack(side="left", padx=2)
        ttk.Label(bar, text="   태그").pack(side="left")
        self.e_tagfilter = ttk.Entry(bar, width=16)
        self.e_tagfilter.pack(side="left", padx=4)
        ttk.Button(bar, text="태그로 선택",
                   command=self._check_by_tag).pack(side="left", padx=2)
        self.lb_selcount = ttk.Label(bar, text="", foreground="#1f4e79")
        self.lb_selcount.pack(side="right", padx=6)

        cols = ("chk", "id", "mode", "steps", "name", "purpose", "tags")
        self.tree = ttk.Treeview(tcf, columns=cols, show="headings",
                                 selectmode="browse", height=6)
        for col, text, w, anchor in [
            ("chk", "", 34, "center"), ("id", "TC_ID", 70, "w"),
            ("mode", "종류", 80, "center"), ("steps", "STEP", 50, "center"),
            ("name", "TC_NAME", 200, "w"), ("purpose", "목적", 380, "w"),
            ("tags", "태그", 120, "w"),
        ]:
            self.tree.heading(col, text=text)
            self.tree.column(col, width=w, anchor=anchor,
                             stretch=(col in ("purpose", "name")))
        vs = ttk.Scrollbar(tcf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=(0, 6))
        vs.pack(side="right", fill="y", pady=(0, 6), padx=(0, 6))
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<space>", lambda e: self._toggle(self.tree.focus()))
        self.tree.tag_configure("evt", foreground="#666666")
        self.tree.tag_configure("todo", foreground="#b5730a")

        # 진행 상황
        st = ttk.LabelFrame(self.paned, text=" 진행 상황 ")
        self.paned.add(st, weight=2)

        self.lb_running = ttk.Label(st, text="대기 중", foreground="#1f4e79")
        self.lb_running.pack(anchor="w", padx=8, pady=(4, 0))

        wrap = ttk.Frame(st)
        wrap.pack(fill="both", expand=True, padx=6, pady=4)
        self.txt = tk.Text(wrap, height=6, wrap="none", font=self.mono_font,
                           background="#fbfbfb", relief="flat", borderwidth=1)
        ts = ttk.Scrollbar(wrap, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=ts.set, state="disabled")
        self.txt.pack(side="left", fill="both", expand=True)
        ts.pack(side="right", fill="y")
        for key, color in COLORS.items():
            self.txt.tag_configure(key, foreground=color)
        self.txt.tag_configure(PASS, foreground=COLORS[PASS],
                               font=(self.mono_font[0], 9, "bold"))
        self.txt.tag_configure(FAIL, foreground=COLORS[FAIL],
                               font=(self.mono_font[0], 9, "bold"))

        # 분할 위치 초기화 (창이 그려진 뒤에)
        self.after(250, self._init_sash)

    def _init_sash(self):
        try:
            h = self.paned.winfo_height()
            if h > 200:
                self.paned.sashpos(0, int(h * 0.58))
        except (tk.TclError, IndexError):
            pass

    # ==================================================================
    # 제품 프로파일
    # ==================================================================
    def _refresh_products(self, select_name: str | None = None):
        names = self.store.names()
        self.cb_product["values"] = names
        if names:
            target = select_name if select_name in names else names[0]
            self.cb_product.set(target)
            self._load_product()
        else:
            self.cb_product.set("")
            self._new_product()

    def _load_product(self):
        name = self.cb_product.get()
        if not name:
            return
        try:
            prof = self.store.get(name)
        except KeyError:
            return
        self.current_name = name

        self.e_name.delete(0, "end"); self.e_name.insert(0, prof.name)
        self.e_logdir.delete(0, "end"); self.e_logdir.insert(0, prof.log_dir or prof.log_file)
        self.e_pattern.delete(0, "end"); self.e_pattern.insert(0, prof.pattern or "*.log")
        self.e_tester.delete(0, "end"); self.e_tester.insert(0, prof.tester)
        self.e_fw.delete(0, "end"); self.e_fw.insert(0, prof.fw)
        self.lb_rules.delete(0, "end")
        for r in prof.rules:
            self.lb_rules.insert("end", r)

        self._reload_tcs(preselect=prof)
        self._set_status(f"'{prof.name}' 프로파일을 불러왔습니다.")

    def _new_product(self):
        self.current_name = ""
        self.cb_product.set("")
        for e in (self.e_name, self.e_logdir, self.e_tester, self.e_fw):
            e.delete(0, "end")
        self.e_pattern.delete(0, "end"); self.e_pattern.insert(0, "*.log")
        self.lb_rules.delete(0, "end")
        self.tree.delete(*self.tree.get_children())
        self.definitions = []
        self._update_selcount()
        self._set_status("새 제품 - 이름/로그 폴더/TC 파일을 지정한 뒤 [설정 저장]")

    def _collect_profile(self) -> Profile:
        name = self.e_name.get().strip()
        rules = list(self.lb_rules.get(0, "end"))
        return Profile(
            name=name,
            log_dir=self.e_logdir.get().strip(),
            pattern=self.e_pattern.get().strip() or "*.log",
            rules=rules,
            tc=",".join(self._checked_ids()),
            tester=self.e_tester.get().strip(),
            fw=self.e_fw.get().strip(),
        )

    def _save_product(self):
        prof = self._collect_profile()
        if not prof.name:
            messagebox.showwarning("확인", "제품명을 입력하세요.")
            return
        if not prof.rules:
            messagebox.showwarning("확인", "TC 규칙 파일을 1개 이상 추가하세요.")
            return
        if self.current_name and self.current_name != prof.name:
            self.store.remove(self.current_name)
        self.store.upsert(prof)
        try:
            self.store.save()
        except OSError as e:
            messagebox.showerror("저장 실패", str(e))
            return
        self.current_name = prof.name
        self._refresh_products(select_name=prof.name)
        self._set_status(f"저장 완료 : {self.store.path}")

    def _delete_product(self):
        name = self.cb_product.get()
        if not name:
            return
        if not messagebox.askyesno("삭제", f"'{name}' 프로파일을 삭제할까요?"):
            return
        self.store.remove(name)
        self.store.save()
        self._refresh_products()

    # ==================================================================
    # 경로 / 규칙
    # ==================================================================
    def _pick_logdir(self):
        init = self.e_logdir.get().strip() or str(BASE_DIR)
        path = filedialog.askdirectory(title="디버그 로그가 저장되는 폴더 선택",
                                       initialdir=init if Path(init).is_dir() else str(BASE_DIR))
        if path:
            self.e_logdir.delete(0, "end")
            self.e_logdir.insert(0, os.path.normpath(path))

    def _add_rule(self):
        paths = filedialog.askopenfilenames(
            title="TC 규칙 파일 선택",
            initialdir=str(BASE_DIR / "tc"),
            filetypes=[("TC 규칙", "*.csv *.tsv *.txt *.xlsx *.xlsm"),
                       ("모든 파일", "*.*")])
        for p in paths:
            self.lb_rules.insert("end", os.path.normpath(p))
        if paths:
            self._reload_tcs()

    def _remove_rule(self):
        for i in reversed(self.lb_rules.curselection()):
            self.lb_rules.delete(i)
        self._reload_tcs()

    # ==================================================================
    # TC 목록
    # ==================================================================
    def _reload_tcs(self, preselect: Profile | None = None):
        rules = list(self.lb_rules.get(0, "end"))
        self.tree.delete(*self.tree.get_children())
        self.definitions = []
        if not rules:
            self._update_selcount()
            return

        missing = [r for r in rules if not Path(r).exists()]
        if missing:
            messagebox.showerror("규칙 파일 없음", "\n".join(missing))
            return

        try:
            defs, notes = load_rules(rules, product=self.e_name.get().strip())
        except RuntimeError as e:
            # 사용자용으로 이미 정리된 메시지
            messagebox.showerror("TC 규칙 파일 오류", str(e))
            self._append(str(e).replace("\n", "  "), "warn")
            return
        except Exception as e:
            messagebox.showerror("TC 규칙 파일 오류",
                                 f"{type(e).__name__}: {e}")
            return

        self.definitions = defs
        for n in notes:
            self._append(str(n), "warn")

        # 어떤 형식으로 읽었는지 알려준다 (문제 생겼을 때 원인 파악용)
        try:
            from core.rule_loader import RuleLoader
            probe = RuleLoader(rules[-1]); probe.load()
            dname = {",": "쉼표", "\t": "탭", ";": "세미콜론",
                     "|": "세로줄"}.get(probe.delimiter, probe.delimiter)
            self._set_status(f"TC {len(defs)}개 로드 "
                             f"(구분자: {dname}, 인코딩: {probe.encoding_used or 'xlsx'})")
        except Exception:
            self._set_status(f"TC {len(defs)}개 로드")

        # 프로파일에 저장된 선택 복원
        wanted = set()
        if preselect:
            if preselect.all_tc:
                wanted = {d.tc_id for d in defs}
            else:
                chosen = select(
                    defs,
                    tc_filter=preselect.tc.split(",") if preselect.tc else None,
                    tag_filter=preselect.tag.split(",") if preselect.tag else None,
                    name_filter=preselect.tc_name.split(",") if preselect.tc_name else None)
                wanted = {d.tc_id for d in chosen}

        for d in defs:
            if d.is_todo:
                mode = f"미완성 {d.todo_count}"
            elif d.is_event:
                mode = "이벤트감시"
            elif any(x.is_absent for x in d.steps):
                mode = "시나리오+금지"
            else:
                mode = "시나리오"
            self.tree.insert(
                "", "end", iid=d.tc_id,
                values=(CHECKED if d.tc_id in wanted else UNCHECKED,
                        d.tc_id, mode, len(d.steps), d.tc_name,
                        d.purpose, ",".join(d.tags)),
                tags=("todo",) if d.is_todo else (("evt",) if d.is_event else ()))
        self._update_selcount()

    def _on_tree_click(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != "#1":
            return
        self._toggle(self.tree.identify_row(event.y))
        return "break"

    def _toggle(self, iid):
        if not iid:
            return
        cur = self.tree.set(iid, "chk")
        self.tree.set(iid, "chk", UNCHECKED if cur == CHECKED else CHECKED)
        self._update_selcount()

    def _check_all(self, on: bool):
        for iid in self.tree.get_children():
            self.tree.set(iid, "chk", CHECKED if on else UNCHECKED)
        self._update_selcount()

    def _check_by_tag(self):
        tags = {t.strip().lower() for t in self.e_tagfilter.get().split(",") if t.strip()}
        if not tags:
            return
        for d in self.definitions:
            if {t.lower() for t in d.tags} & tags:
                self.tree.set(d.tc_id, "chk", CHECKED)
        self._update_selcount()

    def _checked_ids(self) -> list[str]:
        return [iid for iid in self.tree.get_children()
                if self.tree.set(iid, "chk") == CHECKED]

    def _update_selcount(self):
        ids = set(self._checked_ids())
        seq = sum(1 for d in self.definitions if d.tc_id in ids and not d.is_event)
        evt = len(ids) - seq
        self.lb_selcount.config(
            text=f"선택 {len(ids)} / 전체 {len(self.definitions)}"
                 f"   (시나리오 {seq}, 이벤트감시 {evt})")

    # ==================================================================
    # 실행
    # ==================================================================
    def _validate(self) -> Profile | None:
        prof = self._collect_profile()
        if not prof.name:
            messagebox.showwarning("확인", "제품명을 입력하세요.")
            return None
        if not prof.rules:
            messagebox.showwarning("확인", "TC 규칙 파일을 추가하세요.")
            return None
        if not prof.tc:
            messagebox.showwarning("확인", "판정할 TC 를 1개 이상 체크하세요.")
            return None
        return prof

    def _start(self):
        prof = self._validate()
        if not prof:
            return
        if not prof.log_dir:
            messagebox.showwarning("확인", "디버그 로그 폴더를 선택하세요.")
            return
        if not Path(prof.log_dir).is_dir():
            messagebox.showerror("폴더 없음", f"로그 폴더가 없습니다:\n{prof.log_dir}")
            return
        self._launch(prof, replay=None)

    def _replay(self):
        prof = self._validate()
        if not prof:
            return
        init = prof.log_dir if Path(prof.log_dir or "").is_dir() else str(BASE_DIR)
        path = filedialog.askopenfilename(
            title="재분석할 로그 파일 선택", initialdir=init,
            filetypes=[("로그 파일", "*.log *.txt"), ("모든 파일", "*.*")])
        if not path:
            return
        prof.log_dir = ""
        self._launch(prof, replay=path)

    def _launch(self, prof: Profile, replay: str | None):
        console = GuiConsole(self.q, tag=prof.name)
        console.verbose = self.var_verbose.get()
        try:
            self.runner = Runner(prof, out_dir=str(OUT_DIR), replay=replay,
                                 console=console, heartbeat=0)
        except Exception as e:
            messagebox.showerror("시작 실패", str(e))
            return

        warns = self.runner.warnings()
        if warns and not self._confirm_warnings(warns):
            self.runner = None
            return
        for w in warns:
            self._append("[경고] " + w.replace("\n", " "), "warn")

        self._clear_log()
        self._append("=" * 70, "muted")
        for line in self.runner.describe():
            self._append("  " + line, "info")
        self._append("=" * 70, "muted")

        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal" if not replay else "disabled")
        self.lb_counts.config(text="PASS 0   FAIL 0   TIMEOUT 0   INCOMPLETE 0")

        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()
        self._set_status("감시 중..." if not replay else "재분석 중...")
        self._tick_running()

    def _confirm_warnings(self, warns) -> bool:
        """
        룰 충돌 경고 창.
        경고가 많아도 창 크기가 고정이고 스크롤된다.
        (messagebox 는 내용이 길면 화면 밖으로 넘쳐 닫을 수 없게 된다)
        """
        dlg = tk.Toplevel(self)
        dlg.title("룰 충돌 경고")
        dlg.transient(self)
        dlg.resizable(True, True)

        W, H = 820, 480
        self.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - W) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - H) // 3)
        dlg.geometry(f"{W}x{H}+{x}+{y}")
        dlg.minsize(560, 320)

        result = {"go": False}

        head = ttk.Frame(dlg)
        head.pack(fill="x", padx=14, pady=(12, 6))
        ttk.Label(head, text=f"같은 로그 문구를 기다리는 TC 가 있습니다  ({len(warns)}건)",
                  font=(self.base_font[0] if self.base_font else None, 11, "bold"),
                  foreground=COLORS["warn"]).pack(anchor="w")
        ttk.Label(head, text="이대로 동시에 감시하면 잘못된 PASS 나 허위 TIMEOUT 이 날 수 있습니다.",
                  foreground="#555").pack(anchor="w", pady=(2, 0))

        body = ttk.Frame(dlg)
        body.pack(fill="both", expand=True, padx=14, pady=6)
        txt = tk.Text(body, wrap="word", font=self.mono_font,
                      background="#fbfbfb", relief="solid", borderwidth=1)
        sc = ttk.Scrollbar(body, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sc.set)
        txt.pack(side="left", fill="both", expand=True)
        sc.pack(side="right", fill="y")
        for i, w in enumerate(warns, start=1):
            txt.insert("end", f"{i}. {w}\n\n")
        txt.config(state="disabled")

        btns = ttk.Frame(dlg)
        btns.pack(fill="x", padx=14, pady=(4, 12))

        def cancel(*_):
            result["go"] = False
            dlg.destroy()

        def proceed():
            result["go"] = True
            dlg.destroy()

        ttk.Button(btns, text="취소하고 TC 선택 줄이기 (권장)",
                   command=cancel).pack(side="right", padx=4)
        ttk.Button(btns, text="그래도 진행", command=proceed).pack(side="right", padx=4)
        ttk.Label(btns, text="Esc 로 닫기", foreground="#888").pack(side="left")

        dlg.bind("<Escape>", cancel)
        dlg.protocol("WM_DELETE_WINDOW", cancel)
        dlg.grab_set()
        dlg.focus_set()
        self.wait_window(dlg)
        return result["go"]

    def _worker(self):
        try:
            self.runner.run()
        except Exception:
            self.q.put(("log", traceback.format_exc(), FAIL))
        finally:
            self.q.put(("done", self.runner.report.xlsx_path if self.runner else "", None))

    def _stop(self):
        if self.runner:
            self._append("중지 요청 - 리포트 저장 중...", "warn")
            self.runner.stop()
        self.btn_stop.config(state="disabled")

    def _tick_running(self):
        if self.runner and self.thread and self.thread.is_alive():
            try:
                lines = self.runner.manager.status_lines()
            except Exception:
                lines = []
            self.lb_running.config(
                text="   |   ".join(lines) if lines else "대기 중 (트리거 로그를 기다리는 중)")
            self.after(500, self._tick_running)
        else:
            self.lb_running.config(text="대기 중")

    # ==================================================================
    # 큐 처리
    # ==================================================================
    def _drain(self):
        try:
            while True:
                kind, payload, style = self.q.get_nowait()
                if kind == "log":
                    self._append(payload, style or "info")
                elif kind == "counts":
                    self.lb_counts.config(
                        text=f"PASS {payload[PASS]}   FAIL {payload[FAIL]}   "
                             f"TIMEOUT {payload[TIMEOUT]}   INCOMPLETE {payload[INCOMPLETE]}")
                elif kind == "done":
                    self._on_finished(payload)
        except queue.Empty:
            pass
        self.after(100, self._drain)

    def _on_finished(self, xlsx_path):
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self._append("=" * 70, "muted")
        self._append(f"종료. 리포트 : {xlsx_path}", "info")
        self._append("=" * 70, "muted")
        self._set_status(f"완료 - {xlsx_path}")
        self.runner = None

    # ==================================================================
    def _append(self, text, style="info"):
        self.txt.config(state="normal")
        self.txt.insert("end", text + "\n", style)
        self.txt.see("end")
        self.txt.config(state="disabled")

    def _clear_log(self):
        self.txt.config(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.config(state="disabled")

    def _set_status(self, text):
        self.status.config(text="  " + text)

    def _toggle_verbose(self):
        if self.runner:
            self.runner.console.verbose = self.var_verbose.get()

    def _open_out(self):
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        target = OUT_DIR
        name = self.e_name.get().strip()
        if name and (OUT_DIR / name).is_dir():
            target = OUT_DIR / name
        try:
            if os.name == "nt":
                os.startfile(target)             # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except Exception as e:
            messagebox.showinfo("폴더 위치", f"{target}\n\n({e})")

    def _on_close(self):
        if self.runner and self.thread and self.thread.is_alive():
            if not messagebox.askyesno("종료", "감시 중입니다. 중지하고 종료할까요?"):
                return
            self.runner.stop()
            self.thread.join(timeout=8)
        self.destroy()


def main():
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        root = tk.Tk(); root.withdraw()
        messagebox.showerror("라이브러리 없음",
                             "openpyxl 이 설치되어 있지 않습니다.\n\n"
                             "명령 프롬프트에서:\n    pip install openpyxl")
        return 1
    App().mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
