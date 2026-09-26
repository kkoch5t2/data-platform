from __future__ import annotations

import re


ROW_RE = re.compile(r"CurrentYearInstant_No(\d+)MajorShareholdersMember$")


def parse_number(value: str):
    text = (value or "").strip().replace(",", "")
    if not text or text in {"-", "―", "－", "—"}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def extract_major_shareholders(rows: list[dict]) -> list[dict]:
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

    result = []
    for rank in sorted(grouped):
        item = grouped[rank]
        if not item.get("name"):
            continue
        if item.get("shareholdingRatio") is None:
            continue
        result.append(item)
    return result
