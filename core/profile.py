"""
제품별 프로파일 (config/products.ini).

제품마다 로그 폴더와 TC 파일이 다르므로, 매번 CLI 로 넘기는 대신
설정 파일에 등록해두고 이름으로 부른다.

    python main.py -p XVM508

INI 를 쓰는 이유: 윈도우 경로의 역슬래시를 이스케이프 없이 그대로 쓸 수 있고,
주석을 달 수 있다. (JSON 은 C:\\\\Users\\\\... 처럼 써야 해서 실수가 잦다)
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Profile:
    name: str
    log_dir: str = ""
    log_file: str = ""
    pattern: str = "*.log"
    rules: list[str] = field(default_factory=list)   # 여러 개면 병합
    tc: str = ""
    tag: str = ""
    tc_name: str = ""
    all_tc: bool = False
    encoding: str = ""
    tester: str = ""
    fw: str = ""
    out: str = ""
    from_start: bool = False
    note: str = ""

    def describe(self) -> str:
        src = self.log_dir or self.log_file or "(미지정)"
        sel = self.tc or self.tag or self.tc_name or ("ALL" if self.all_tc else "(미지정)")
        rules = ", ".join(Path(r).name for r in self.rules) or "(미지정)"
        return f"{self.name:<12} {rules:<28} {sel:<18} {src}"


def _bool(v: str, default=False) -> bool:
    if v is None or v == "":
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


def _split(v: str) -> list[str]:
    return [x.strip() for x in str(v or "").split(",") if x.strip()]


class ProfileStore:
    def __init__(self, path, base_dir: Path):
        self.path = Path(path)
        self.base_dir = Path(base_dir)
        self.profiles: dict[str, Profile] = {}
        if self.path.exists():
            self._load()

    # ------------------------------------------------------------------
    def _load(self):
        cp = configparser.ConfigParser(interpolation=None)
        # 윈도우 메모장 저장분(BOM) 대응
        for enc in ("utf-8-sig", "cp949", "utf-8"):
            try:
                with open(self.path, "r", encoding=enc) as fh:
                    cp.read_file(fh)
                break
            except (UnicodeDecodeError, configparser.Error) as e:
                last = e
        else:
            raise RuntimeError(f"products.ini 를 읽지 못했습니다: {last}")

        for name in cp.sections():
            s = cp[name]
            self.profiles[name] = Profile(
                name=name,
                log_dir=s.get("log_dir", "").strip(),
                log_file=s.get("log_file", "").strip(),
                pattern=s.get("pattern", "*.log").strip() or "*.log",
                rules=[self._resolve(r) for r in _split(s.get("rules", ""))],
                tc=s.get("tc", "").strip(),
                tag=s.get("tag", "").strip(),
                tc_name=s.get("name", "").strip(),
                all_tc=_bool(s.get("all", "")),
                encoding=s.get("encoding", "").strip(),
                tester=s.get("tester", "").strip(),
                fw=s.get("fw", "").strip(),
                out=s.get("out", "").strip(),
                from_start=_bool(s.get("from_start", "")),
                note=s.get("note", "").strip(),
            )

    @staticmethod
    def normalize(rel: str) -> str:
        """윈도우식 역슬래시 경로를 현재 OS 형식으로 맞춘다."""
        return rel.replace("\\", "/") if os.name != "nt" else rel

    def _resolve(self, rel: str) -> str:
        p = Path(self.normalize(rel))
        return str(p if p.is_absolute() else (self.base_dir / p))

    # ------------------------------------------------------------------
    def get(self, name: str) -> Profile:
        # 대소문자 무시 매칭
        for key, prof in self.profiles.items():
            if key.lower() == name.strip().lower():
                return prof
        raise KeyError(name)

    def names(self) -> list[str]:
        return list(self.profiles.keys())

    # ------------------------------------------------------------------
    def upsert(self, prof: Profile):
        self.profiles[prof.name] = prof

    def remove(self, name: str):
        for key in list(self.profiles):
            if key.lower() == name.strip().lower():
                del self.profiles[key]

    def relative(self, path: str) -> str:
        """프로그램 폴더 안의 경로면 상대경로로 저장한다 (폴더째 옮겨도 동작)."""
        try:
            return str(Path(path).relative_to(self.base_dir))
        except (ValueError, TypeError):
            return str(path)

    def save(self):
        """products.ini 로 다시 기록한다. (GUI 에서 편집한 내용 저장)"""
        cp = configparser.ConfigParser(interpolation=None)
        for name, prof in self.profiles.items():
            sec = {}
            if prof.log_dir:
                sec["log_dir"] = prof.log_dir
            if prof.log_file:
                sec["log_file"] = prof.log_file
            if prof.pattern and prof.pattern != "*.log":
                sec["pattern"] = prof.pattern
            if prof.rules:
                sec["rules"] = ", ".join(self.relative(r) for r in prof.rules)
            if prof.tc:
                sec["tc"] = prof.tc
            if prof.tag:
                sec["tag"] = prof.tag
            if prof.tc_name:
                sec["name"] = prof.tc_name
            if prof.all_tc:
                sec["all"] = "true"
            if prof.encoding:
                sec["encoding"] = prof.encoding
            if prof.tester:
                sec["tester"] = prof.tester
            if prof.fw:
                sec["fw"] = prof.fw
            if prof.out:
                sec["out"] = prof.out
            if prof.from_start:
                sec["from_start"] = "true"
            if prof.note:
                sec["note"] = prof.note
            cp[name] = sec

        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".ini.tmp")
        with open(tmp, "w", encoding="utf-8-sig") as fh:
            fh.write("; 제품별 프로파일 - GUI(qa_gui.py)에서 편집하거나 직접 수정하세요.\n")
            fh.write("; 자세한 항목 설명은 README 참고\n\n")
            cp.write(fh)
        os.replace(tmp, self.path)

    def __bool__(self):
        return bool(self.profiles)
