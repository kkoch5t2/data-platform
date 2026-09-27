from __future__ import annotations

import html
import re
import zipfile
from pathlib import Path


ROW_RE = re.compile(r"CurrentYearInstant_No(\d+)MajorShareholdersMember$")
HTML_CONTEXT_RE = re.compile(r'contextRef="CurrentYearInstant_No(\d+)MajorShareholdersMember"', re.I)
TABLE_RE = re.compile(r"<table\b[^>]*>.*?</table>", re.I | re.S)
TR_RE = re.compile(r"<tr\b[^>]*>.*?</tr>", re.I | re.S)
TD_RE = re.compile(r"<td\b[^>]*>(.*?)</td>", re.I | re.S)


def parse_number(value: str):
    text = (value or "").strip().replace(",", "")
    if not text or text in {"-", "―", "－", "—"}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def _plain(fragment: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", fragment, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def presentation_shareholders(xbrl_zip: Path | None) -> dict[int, dict]:
    if xbrl_zip is None or not xbrl_zip.exists():
        return {}
    result: dict[int, dict] = {}
    with zipfile.ZipFile(xbrl_zip) as archive:
        names = [
            name for name in archive.namelist()
            if "publicdoc" in name.lower() and name.lower().endswith((".htm", ".html"))
        ]
        for name in names:
            source = archive.read(name).decode("utf-8", "ignore")
            for table_match in TABLE_RE.finditer(source):
                table_html = table_match.group(0)
                table_text = _plain(table_html)
                if "氏名又は名称" not in table_text or "所有株式数" not in table_text:
                    continue
                unit_match = re.search(r"所有株式数\s*[（(]\s*(千株|株)\s*[）)]", table_text)
                share_multiplier = 1_000 if unit_match and unit_match.group(1) == "千株" else 1
                for tr_match in TR_RE.finditer(table_html):
                    row_html = tr_match.group(0)
                    ranks = {int(rank) for rank in HTML_CONTEXT_RE.findall(row_html)}
                    if len(ranks) != 1:
                        continue
                    cells = TD_RE.findall(row_html)
                    if len(cells) < 4:
                        continue
                    candidate = _plain(cells[0])
                    if not candidate or candidate in {"氏名又は名称", "氏名", "名称", "計", "合計"}:
                        continue
                    rank = next(iter(ranks))
                    item = result.setdefault(rank, {})
                    item.setdefault("name", candidate)
                    shares = parse_number(_plain(cells[2]))
                    if shares is not None and shares >= 0:
                        item.setdefault("shares", shares * share_multiplier)
    return result


def extract_major_shareholders(rows: list[dict], xbrl_zip: Path | None = None) -> list[dict]:
    grouped: dict[int, dict] = {}
    for row in rows:
        match = ROW_RE.search(row.get("context") or "")
        if not match:
            continue
        rank = int(match.group(1))
        item = grouped.setdefault(rank, {"rank": rank})
        concept = (row.get("concept") or "").rsplit(":", 1)[-1]
        value = row.get("value") or ""
        if concept == "NameMajorShareholders":
            item["name"] = value.strip()
        elif concept == "NumberOfSharesHeld":
            item["shares"] = parse_number(value)
        elif concept == "ShareholdingRatio":
            ratio = parse_number(value)
            item["shareholdingRatio"] = ratio * 100 if ratio is not None else None

    recovered = presentation_shareholders(xbrl_zip)
    for rank, presentation in recovered.items():
        item = grouped.setdefault(rank, {"rank": rank})
        if presentation.get("name"):
            item.setdefault("name", presentation["name"])
        if presentation.get("shares") is not None:
            item.setdefault("shares", presentation["shares"])

    result = []
    for rank in sorted(grouped):
        item = grouped[rank]
        if not item.get("name"):
            continue
        if item.get("shareholdingRatio") is None:
            continue
        result.append(item)
    return result
