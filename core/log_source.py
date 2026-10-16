"""
로그 공급원.

- FolderTailSource : 폴더를 감시하며 '가장 최근 로그 파일'을 자동으로 따라간다.
                     SecureCRT 가 세션마다 새 파일을 만들어도 자동 전환.
- FileTailSource   : 특정 파일 하나만 tail
- ReplaySource     : 저장된 로그를 처음부터 끝까지 읽고 종료 (룰 검증/재분석용)

세 가지 모두 동일한 인터페이스를 갖는다:
    source.add_line_callback(fn)   # fn(LogEvent)
    source.add_tick_callback(fn)   # fn(now: float)
    source.run()
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime
from pathlib import Path

from .log_event import Clock, LineParser, LogEvent

TICK_INTERVAL = 0.2      # 초. TIMEOUT 감시 주기
POLL_INTERVAL = 0.05     # 초. 새 데이터 확인 주기
ROTATE_CHECK_INTERVAL = 2.0  # 초. 새 로그 파일 등장 확인 주기

# [2026-07-22-10시46분32초].log  같은 파일명에서 날짜 추출
_FNAME_DATE = re.compile(r"(\d{4})[-_.]?(\d{2})[-_.]?(\d{2})")


def _date_from_filename(path: Path) -> datetime | None:
    m = _FNAME_DATE.search(path.name)
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


class _BaseSource:
    def __init__(self, encoding: str = "utf-8", clock_mode: str = "live"):
        self.encoding = encoding
        self.clock = Clock(clock_mode)
        self.parser = LineParser()
        self.line_callbacks: list = []
        self.tick_callbacks: list = []
        self._stop = False
        self.log = print          # 제품 태그를 붙이려면 Runner 가 교체한다
        self._seen = 0
        self._warned_no_ts = False

    def add_line_callback(self, fn):
        self.line_callbacks.append(fn)

    def add_tick_callback(self, fn):
        self.tick_callbacks.append(fn)

    def stop(self):
        self._stop = True

    # -- 내부 ---------------------------------------------------------------
    def _emit(self, raw_line: str):
        event = self.parser.parse(raw_line)
        if not event.clean:
            return
        self.clock.feed(event)

        # 로그에 타임스탬프가 없으면 TIMEOUT 판정이 벽시계 기준이 되어
        # SecureCRT 버퍼링만큼 오차가 생긴다. 조용히 틀리면 안 되므로 한 번 알린다.
        self._seen += 1
        if (not self._warned_no_ts and self._seen >= 50
                and not self.clock.has_log_time):
            self._warned_no_ts = True
            self.log("  [주의] 로그에 시각 정보가 없어 TIMEOUT 을 프로그램 시각으로 잽니다.")
            self.log("         SecureCRT > Session Options > Terminal > Log File >")
            self.log("         Custom log data > On each line 에 '[%h:%m:%s.%t] ' 를 넣으면")
            self.log("         장비가 출력한 시각 기준으로 정확히 판정합니다.")

        for fn in self.line_callbacks:
            fn(event)

    def _tick(self):
        now = self.clock.now()
        for fn in self.tick_callbacks:
            fn(now)


class _Tailer:
    """
    파일 하나를 tail 하는 저수준 헬퍼.
    - 완결되지 않은 라인(개행 없음)은 버퍼에 보관했다가 다음에 이어붙인다.
    - 파일이 truncate/교체되면 감지해서 다시 연다.
    """

    def __init__(self, path: Path, encoding: str, from_start: bool):
        self.path = path
        self.encoding = encoding
        self._buf = ""
        self._fh = open(path, "r", encoding=encoding, errors="replace", newline="")
        if not from_start:
            self._fh.seek(0, os.SEEK_END)
        self._inode = self._stat_key()

    def _stat_key(self):
        try:
            st = self.path.stat()
            return (getattr(st, "st_ino", 0), st.st_dev, st.st_size)
        except OSError:
            return None

    def read_lines(self) -> list[str]:
        """완결된 라인들만 반환."""
        chunk = self._fh.read()
        if not chunk:
            self._check_rotate()
            return []
        self._buf += chunk
        if "\n" not in self._buf:
            return []
        *lines, self._buf = self._buf.split("\n")
        return lines

    def _check_rotate(self):
        """파일이 truncate 되었거나 교체된 경우 재오픈."""
        try:
            size = self.path.stat().st_size
        except OSError:
            return
        if size < self._fh.tell():
            # truncate 됨 -> 처음부터 다시
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = open(self.path, "r", encoding=self.encoding,
                            errors="replace", newline="")
            self._buf = ""

    def flush_tail(self) -> list[str]:
        """남은 미완결 버퍼를 마지막에 한 번 뱉는다."""
        if self._buf.strip():
            out, self._buf = [self._buf], ""
            return out
        return []

    def close(self):
        try:
            self._fh.close()
        except OSError:
            pass


class FileTailSource(_BaseSource):
    """파일 하나를 실시간 감시."""

    def __init__(self, path, encoding="utf-8", from_start=False):
        super().__init__(encoding, clock_mode="live")
        self.path = Path(path)
        self.from_start = from_start

    def run(self):
        base = _date_from_filename(self.path)
        if base:
            self.parser = LineParser(base_date=base)
        tailer = _Tailer(self.path, self.encoding, self.from_start)
        self.log(f"  감시 중 : {self.path}")
        last_tick = time.monotonic()
        try:
            while not self._stop:
                lines = tailer.read_lines()
                for line in lines:
                    self._emit(line)
                now = time.monotonic()
                if now - last_tick >= TICK_INTERVAL:
                    self._tick()
                    last_tick = now
                if not lines:
                    time.sleep(POLL_INTERVAL)
        finally:
            tailer.close()


class FolderTailSource(_BaseSource):
    """
    폴더 안에서 가장 최근에 수정된 로그 파일을 자동으로 따라간다.
    SecureCRT 세션을 새로 열어 새 로그 파일이 생기면 자동으로 갈아탄다.
    """

    def __init__(self, folder, pattern="*.log", encoding="utf-8", from_start=False):
        super().__init__(encoding, clock_mode="live")
        self.folder = Path(folder)
        self.pattern = pattern
        self.from_start = from_start
        self._current: Path | None = None
        self._tailer: _Tailer | None = None
        self.on_switch = None  # fn(new_path)

    def _newest(self) -> Path | None:
        files = [p for p in self.folder.glob(self.pattern) if p.is_file()]
        if not files:
            return None
        return max(files, key=lambda p: p.stat().st_mtime)

    def _switch_to(self, path: Path, from_start: bool):
        if self._tailer:
            for line in self._tailer.flush_tail():
                self._emit(line)
            self._tailer.close()
        base = _date_from_filename(path)
        self.parser = LineParser(base_date=base) if base else LineParser()
        self._tailer = _Tailer(path, self.encoding, from_start)
        self._current = path
        self.log(f"  >> 로그 파일 전환 : {path.name}")
        if self.on_switch:
            self.on_switch(path)

    def run(self):
        if not self.folder.is_dir():
            raise FileNotFoundError(f"폴더를 찾을 수 없습니다: {self.folder}")

        self.log(f"  감시 폴더 : {self.folder}  (패턴: {self.pattern})")
        newest = self._newest()
        if newest:
            self._switch_to(newest, self.from_start)
        else:
            self.log("  (아직 로그 파일이 없습니다. 생성되면 자동으로 잡습니다)")

        last_tick = time.monotonic()
        last_scan = 0.0
        try:
            while not self._stop:
                now = time.monotonic()

                # 새 로그 파일 등장 확인
                if now - last_scan >= ROTATE_CHECK_INTERVAL:
                    last_scan = now
                    candidate = self._newest()
                    if candidate and candidate != self._current:
                        # 새로 생긴 파일은 항상 처음부터 읽는다
                        self._switch_to(candidate, from_start=True)

                lines = self._tailer.read_lines() if self._tailer else []
                for line in lines:
                    self._emit(line)

                if now - last_tick >= TICK_INTERVAL:
                    self._tick()
                    last_tick = now
                if not lines:
                    time.sleep(POLL_INTERVAL)
        finally:
            if self._tailer:
                self._tailer.close()


class ReplaySource(_BaseSource):
    """
    저장된 로그를 처음부터 끝까지 읽는다.
    - TC 를 추가하거나 TIMEOUT 을 조정한 뒤 어제 로그로 즉시 재검증
    - 같은 로그 -> 항상 같은 결과 (결정론적)
    """

    def __init__(self, path, encoding="utf-8"):
        super().__init__(encoding, clock_mode="replay")
        self.path = Path(path)

    def run(self):
        base = _date_from_filename(self.path)
        if base:
            self.parser = LineParser(base_date=base)
        self.log(f"  리플레이 : {self.path}")
        count = 0
        with open(self.path, "r", encoding=self.encoding,
                  errors="replace", newline="") as fh:
            for line in fh:
                self._emit(line.rstrip("\n"))
                self._tick()   # 라인마다 tick -> 로그 시각 기준 TIMEOUT 판정
                count += 1
        self.log(f"  리플레이 완료 : {count} lines")
        if not self.clock.has_log_time:
            self.log("  [경고] 로그에 타임스탬프가 없어 TIMEOUT 판정을 할 수 없습니다.")
            self.log("         SecureCRT의 'Custom log data > On each line' 설정을 켜세요.")


def detect_encoding(path: Path) -> str:
    """UTF-8 로 못 읽으면 CP949 로 판단 (국내 임베디드 로그 대응)."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(65536)
        head.decode("utf-8")
        return "utf-8"
    except (UnicodeDecodeError, OSError):
        return "cp949"
