from __future__ import annotations

import csv
import io
import re
import zipfile
from collections import defaultdict
from pathlib import Path

from .common import RAW, valid_corporate_number

SOURCE_URL = "https://info.gbiz.go.jp/hojin/DownloadTop"
SPECS = {
    "subsidy": ("Hojokinjoho", {"法人番号", "証明日", "名称", "金額", "対象", "発行元"}),
    "patent": ("Tokkyojoho", {"法人番号", "特許/意匠/商標", "登録番号", "出願年月日", "発明の名称(等)/意匠に係る物品/表示用商標", "文献固定アドレス"}),
}


def source_path(kind: str) -> Path | None:
    prefix = SPECS[kind][0]
    files = sorted((RAW / "gbiz").glob(f"{prefix}_UTF-8_*.zip"))
    return files[-1] if files else None


def source_date(path: Path) -> str:
    match = re.search(r"(20\d{6})", path.name)
    if not match:
        raise ValueError(f"missing source date: {path.name}")
    date = match.group(1)
    return f"{date[:4]}-{date[4:6]}-{date[6:]}"


def rows_from_zip(path: Path, required: set[str]):
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"expected one CSV in {path.name}")
        with archive.open(names[0]) as raw:
            reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))
            if not required.issubset(reader.fieldnames or []):
                raise ValueError(f"unexpected gBizINFO schema in {path.name}")
            yield from reader


def load_activity_map(corporate_numbers) -> tuple[dict[str, dict], dict[str, dict]]:
    targets = {str(value) for value in corporate_numbers if valid_corporate_number(value)}
    if not targets:
        return {}, {}
    subsidies = defaultdict(dict)
    patents = defaultdict(dict)
    metadata = {}
    for kind, (_, required) in SPECS.items():
        path = source_path(kind)
        if not path:
            raise FileNotFoundError(f"gBizINFO {kind} ZIP is missing; download the official snapshot before building")
        metadata[kind] = {"sourceDate": source_date(path), "sourceUrl": SOURCE_URL, "sourceFile": path.name}
        for row in rows_from_zip(path, required):
            number = row["法人番号"].strip()
            if number not in targets:
                continue
            if kind == "subsidy":
                amount_text = row["金額"].strip().replace(",", "")
                if amount_text and not re.fullmatch(r"-?\d+", amount_text):
                    raise ValueError(f"invalid subsidy amount for {number}: {amount_text!r}")
                item = {
                    "date": row["証明日"].strip(),
                    "name": row["名称"].strip(),
                    "amount": int(amount_text) if amount_text else None,
                    "target": row["対象"].strip(),
                    "issuer": row["発行元"].strip(),
                }
                if not item["name"]:
                    continue
                key = tuple(item.values())
                subsidies[number][key] = item
            elif row["特許/意匠/商標"].strip() == "特許":
                registration = row["登録番号"].strip()
                if not registration:
                    continue
                item = {
                    "registration": registration,
                    "applicationDate": row["出願年月日"].strip(),
                    "name": row["発明の名称(等)/意匠に係る物品/表示用商標"].strip(),
                    "url": row["文献固定アドレス"].strip(),
                }
                previous = patents[number].setdefault(registration, item)
                if any(previous[key] and item[key] and previous[key] != item[key] for key in ("applicationDate", "name", "url")):
                    raise ValueError(f"conflicting patent registration for {number}: {registration}")
    activities = {}
    for number in targets:
        subsidy_records = sorted(subsidies[number].values(), key=lambda x: (x["date"], x["name"]), reverse=True)
        patent_records = sorted(patents[number].values(), key=lambda x: (x["applicationDate"], x["registration"]), reverse=True)
        if not subsidy_records and not patent_records:
            continue
        activities[number] = {
            "subsidies": {"count": len(subsidy_records), "recent": subsidy_records[:8], "sourceDate": metadata["subsidy"]["sourceDate"]} if subsidy_records else None,
            "patents": {"count": len(patent_records), "recent": patent_records[:8], "sourceDate": metadata["patent"]["sourceDate"]} if patent_records else None,
        }
    return activities, metadata
