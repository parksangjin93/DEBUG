"""
TC 규칙 파일 로더 (.csv / .xlsx).

기존 컬럼(TC_NAME, STEP, TYPE, VALUE, FAIL, TIMEOUT)과
새 컬럼(TC_ID, TEST_PURPOSE, TEST_METHOD, 비고)을 모두 지원한다.

선택 컬럼
---------
MATCH    : CONTAINS(기본) | REGEX
TAG      : 쉼표 구분. --tag 로 묶음 실행
MODE     : SEQUENCE | EVENT  (미지정 시 스텝 1개면 자동 EVENT)
COOLDOWN : EVENT 모드 재기록 최소 간격(초), 기본 10
"""

from __future__ import annotations

import csv
from pathlib import Path

from .step import Step, TCDefinition

# 컬럼 별칭 (대소문자/공백 무시하고 매칭)
ALIASES = {
    "tc_id": ["tc_id", "id", "tcid"],
    "tc_name": ["tc_name", "tcname", "name"],
    "purpose": ["test_purpose", "purpose", "목적"],
    "step": ["step", "step_no", "no"],
    "method": ["test_method", "method", "테스트방법"],
    "type": ["type", "row_type"],
    "value": ["value", "expected", "keyword"],
    "fail": ["fail", "fail_keyword", "ng"],
    "timeout": ["timeout", "time_out"],
    "match": ["match", "match_mode"],
    "tag": ["tag", "tags", "test_group", "group", "category"],
    "mode": ["mode", "check_mode", "check_type"],
    "cooldown": ["cooldown"],
    "product": ["product", "model", "제품", "기종"],
    "note": ["note", "remark", "비고"],
}

ENCODINGS = ["utf-8-sig", "cp949", "utf-8", "euc-kr", "latin-1"]

# 엑셀에서 저장하는 방식에 따라 구분자가 달라진다.
#   쉼표(,)  : 일반 CSV
#   탭(\t)   : "텍스트(탭으로 분리)" 로 저장했거나 엑셀에서 복사-붙여넣기
#   세미콜론(;) : 일부 국가 로케일의 엑셀 기본값
DELIMITERS = [",", "\t", ";", "|"]

# 헤더로 인정할 최소 조건 (제목 행이 위에 있어도 찾아내기 위함)
HEADER_HINTS = ("value", "tc_name", "tc_id", "expected", "keyword")


def _sniff_delimiter(lines: list[str]) -> str:
    """앞쪽 몇 줄을 보고 가장 많이 쓰인 구분자를 고른다."""
    best, best_score = ",", -1
    for d in DELIMITERS:
        counts = [ln.count(d) for ln in lines[:10] if ln.strip()]
        if not counts:
            continue
        # 여러 줄에서 일관되게 나타나는 구분자를 선호한다
        score = min(counts) * 10 + sum(counts)
        if score > best_score:
            best, best_score = d, score
    return best


def _find_header(rows: list[list], limit: int = 10) -> int:
    """헤더 행의 인덱스를 찾는다. 위에 제목 행이 있어도 건너뛴다."""
    for i, row in enumerate(rows[:limit]):
        cells = {_norm(c) for c in row if c not in (None, "")}
        if len(cells) >= 3 and any(h in cells for h in HEADER_HINTS):
            return i
    return 0


def _norm(name) -> str:
    return str(name or "").strip().lower().replace(" ", "_")


def _build_index(headers) -> dict:
    idx = {}
    normalized = [_norm(h) for h in headers]
    for key, names in ALIASES.items():
        for n in names:
            if n in normalized:
                idx[key] = normalized.index(n)
                break
    return idx


def _get(row, idx, key, default=""):
    i = idx.get(key)
    if i is None or i >= len(row):
        return default
    v = row[i]
    return default if v is None else str(v).strip()


def _to_float(v):
    try:
        s = str(v).strip()
        return float(s) if s else None
    except (TypeError, ValueError):
        return None


def _to_int(v, default=0):
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return default


class RuleLoader:
    def __init__(self, path, product: str | None = None):
        self.path = Path(path)
        self.product = (product or "").strip().lower()
        self.seen_products: set[str] = set()   # 오타 감지용
        self.delimiter = ","
        self.encoding_used = ""

    # ------------------------------------------------------------------
    def _rows(self):
        if self.path.suffix.lower() in (".xlsx", ".xlsm"):
            return self._rows_xlsx()
        return self._rows_csv()

    def _rows_csv(self):
        last_err = None
        for enc in ENCODINGS:
            try:
                with open(self.path, "r", encoding=enc, newline="") as fh:
                    text = fh.read()
                lines = text.splitlines()
                if not lines:
                    continue
                self.delimiter = _sniff_delimiter(lines)
                rows = list(csv.reader(lines, delimiter=self.delimiter))
                if rows:
                    self.encoding_used = enc
                    return rows
            except (UnicodeDecodeError, LookupError) as e:
                last_err = e
        raise RuntimeError(f"CSV 인코딩을 판별하지 못했습니다: {self.path} ({last_err})")

    def _rows_xlsx(self):
        from openpyxl import load_workbook
        wb = load_workbook(self.path, data_only=True, read_only=True)
        ws = wb.active
        return [list(r) for r in ws.iter_rows(values_only=True)]

    # ------------------------------------------------------------------
    def _header_error(self, header) -> str:
        name = {",": "쉼표(,)", "\t": "탭", ";": "세미콜론(;)",
                "|": "세로줄(|)"}.get(self.delimiter, repr(self.delimiter))
        found = [str(h).strip() for h in header if h not in (None, "")]
        msg = [f"TC 규칙 파일을 읽지 못했습니다: {self.path.name}",
               "",
               "필수 컬럼 'VALUE' 를 찾을 수 없습니다."]
        if len(found) <= 1 and found and any(
                c in found[0] for c in ("\t", ",", ";", "|")):
            msg += ["",
                    "헤더가 한 칸으로 붙어 있습니다. 컬럼 구분이 안 된 상태입니다.",
                    f"인식된 컬럼 : {found[0][:120]}",
                    "",
                    "해결 방법:",
                    "  엑셀에서 파일을 연 뒤 [다른 이름으로 저장] →",
                    "  파일 형식을 'CSV UTF-8(쉼표로 분리)' 로 지정해서 저장하세요.",
                    "  (탭으로 분리 / 텍스트 파일 형식은 안 됩니다)"]
        elif len(found) <= 1:
            msg += ["",
                    "컬럼이 1개뿐입니다. 구분자가 없는 파일로 보입니다.",
                    f"인식된 내용 : {found[0][:120] if found else '(비어 있음)'}",
                    "",
                    "엑셀에서 [다른 이름으로 저장] → 'CSV UTF-8(쉼표로 분리)' 로 저장하세요."]
        else:
            msg += ["",
                    f"인식된 구분자 : {name}",
                    "읽어낸 컬럼 : " + ", ".join(found[:20]),
                    "",
                    "TC_ID / TC_NAME / STEP / TYPE / VALUE 컬럼이 있어야 합니다.",
                    "첫 줄이 컬럼 이름 행인지 확인하세요."]
        return "\n".join(msg)

    def load(self) -> list[TCDefinition]:
        rows = self._rows()
        if not rows:
            raise RuntimeError(f"빈 규칙 파일: {self.path}")

        head_at = _find_header(rows)
        header = rows[head_at]
        idx = _build_index(header)

        if "value" not in idx:
            raise RuntimeError(self._header_error(header))

        rows = rows[head_at:]

        buckets: dict[str, dict] = {}
        order: list[str] = []

        for raw in rows[1:]:
            if not raw or all(c in (None, "") for c in raw):
                continue

            row_type = _get(raw, idx, "type", "CHECK").upper() or "CHECK"
            if row_type not in ("CHECK", "ABSENT"):
                continue  # CHECK(있어야 함) / ABSENT(없어야 함) 행만 사용

            # PRODUCT 컬럼이 있으면 해당 제품 행 + 공통 행(빈칸)만 사용한다.
            # -> TC 파일을 제품별로 나눠도 되고, 한 파일에 몰아넣어도 된다.
            if "product" in idx:
                row_product = _get(raw, idx, "product").lower()
                if row_product:
                    self.seen_products.add(row_product)
                if self.product and row_product and row_product != self.product:
                    continue

            tc_id = _get(raw, idx, "tc_id")
            tc_name = _get(raw, idx, "tc_name")
            if not tc_id and not tc_name:
                continue
            key = tc_id or tc_name

            if key not in buckets:
                order.append(key)
                tags = [t.strip() for t in
                        _get(raw, idx, "tag").replace("/", ",").split(",") if t.strip()]
                buckets[key] = {
                    "tc_id": tc_id or tc_name,
                    "tc_name": tc_name or tc_id,
                    "purpose": _get(raw, idx, "purpose"),
                    "tags": tags,
                    "mode": _get(raw, idx, "mode", "").upper(),
                    "cooldown": _to_float(_get(raw, idx, "cooldown")) or 10.0,
                    "note": _get(raw, idx, "note"),
                    "steps": [],
                }

            value = _get(raw, idx, "value")
            if not value:
                continue

            buckets[key]["steps"].append(Step(
                step_no=_to_int(_get(raw, idx, "step"), len(buckets[key]["steps"]) + 1),
                keyword=value,
                fail_keyword=_get(raw, idx, "fail") or None,
                timeout=_to_float(_get(raw, idx, "timeout")),
                method=_get(raw, idx, "method"),
                match_mode=_get(raw, idx, "match", "CONTAINS").upper() or "CONTAINS",
                step_type=row_type,
            ))

        result = []
        for key in order:
            b = buckets[key]
            if not b["steps"]:
                continue
            # STEP 번호 기준 정렬 (엑셀 행 순서를 신뢰하지 않는다)
            b["steps"].sort(key=lambda s: s.step_no)
            mode = b["mode"] if b["mode"] in ("SEQUENCE", "EVENT") else "SEQUENCE"
            result.append(TCDefinition(
                tc_id=b["tc_id"], tc_name=b["tc_name"], purpose=b["purpose"],
                steps=b["steps"], tags=b["tags"], mode=mode,
                cooldown=b["cooldown"], note=b["note"],
            ))
        return result


# ----------------------------------------------------------------------
def select(definitions, tc_filter=None, tag_filter=None, name_filter=None):
    """--tc / --tag / --name 으로 실행할 TC 를 고른다."""
    if not (tc_filter or tag_filter or name_filter):
        return list(definitions)

    tc_set = {t.strip().upper() for t in (tc_filter or [])}
    tag_set = {t.strip().lower() for t in (tag_filter or [])}
    name_kw = [n.strip().lower() for n in (name_filter or [])]

    out = []
    for d in definitions:
        if tc_set and d.tc_id.upper() in tc_set:
            out.append(d); continue
        if tag_set and {t.lower() for t in d.tags} & tag_set:
            out.append(d); continue
        if name_kw and any(k in d.tc_name.lower() for k in name_kw):
            out.append(d); continue
    return out


def load_rules(paths, product: str | None = None):
    """
    여러 규칙 파일을 순서대로 읽어 병합한다.
    예) rules = tc/common.csv, tc/XVM508.csv
    같은 TC_ID 가 뒤에 다시 나오면 뒤엣것이 앞엣것을 덮어쓴다(제품별 override).
    """
    merged: dict[str, object] = {}
    order: list[str] = []
    overridden: list[str] = []
    seen_products: set[str] = set()

    for path in paths:
        loader = RuleLoader(path, product=product)
        for d in loader.load():
            if d.tc_id in merged:
                overridden.append(d.tc_id)
            else:
                order.append(d.tc_id)
            merged[d.tc_id] = d
        seen_products |= loader.seen_products

    # PRODUCT 컬럼은 있는데 이 제품명과 맞는 행이 하나도 없으면 오타일 가능성이 높다
    if product and seen_products and product.strip().lower() not in seen_products:
        overridden.append(
            f"[주의] PRODUCT 컬럼에 '{product}' 이(가) 없습니다. "
            f"파일에 있는 값: {', '.join(sorted(seen_products))}")

    return [merged[k] for k in order], overridden
