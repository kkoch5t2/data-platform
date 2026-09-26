from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .common import (
    EDINET_CODE_URL,
    JPX_LIST_URL,
    PUBLIC,
    RAW,
    download,
    ensure_dirs,
    normalize_security_code,
    read_xlsx_first_sheet,
    write_json,
)

MARKET_MAP = {
    "プライム（内国株式）": "プライム",
    "スタンダード（内国株式）": "スタンダード",
    "グロース（内国株式）": "グロース",
    "PRO Market": "TOKYO PRO Market",
}

CORP_WORDS = ("株式会社", "（株）", "(株)", "㈱")


def normalize_name(value: str) -> str:
    text = value.replace("\u3000", " ").strip()
    for word in CORP_WORDS:
        text = text.replace(word, "")
    return re.sub(r"\s+", "", text).casefold()


def load_edinet_rows(zip_path: Path) -> tuple[str, list[dict[str, str]]]:
    with zipfile.ZipFile(zip_path) as archive:
        csv_name = next(name for name in archive.namelist() if name.lower().endswith(".csv"))
        text = archive.read(csv_name).decode("cp932")
    raw = list(csv.reader(io.StringIO(text)))
    source_label = raw[0][1] if raw and len(raw[0]) > 1 else ""
    headers = raw[1]
    rows = [dict(zip(headers, row)) for row in raw[2:] if row]
    return source_label, rows


def make_edinet_maps(rows: list[dict[str, str]]):
    by_code: dict[str, dict[str, str]] = {}
    by_name: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        security_code = normalize_security_code(row.get("証券コード"))
        if security_code:
            by_code[security_code] = row
        key = normalize_name(row.get("提出者名", ""))
        if key:
            by_name.setdefault(key, []).append(row)
    return by_code, by_name


def pick_edinet(jpx_row: dict[str, str], by_code, by_name):
    code = normalize_security_code(jpx_row.get("コード"))
    if code in by_code:
        return by_code[code], "securityCode"
    candidates = by_name.get(normalize_name(jpx_row.get("銘柄名", "")), [])
    if len(candidates) == 1:
        return candidates[0], "exactName"
    return None, None


def main() -> None:
    ensure_dirs()
    jpx_path = download(JPX_LIST_URL, RAW / "jpx" / "data_j.xlsx")
    edinet_zip = download(EDINET_CODE_URL, RAW / "edinet" / "Edinetcode.zip")
    jpx_rows = read_xlsx_first_sheet(jpx_path)
    edinet_label, edinet_rows = load_edinet_rows(edinet_zip)
    by_code, by_name = make_edinet_maps(edinet_rows)

    companies = []
    skipped_share_classes = []
    for row in jpx_rows:
        market_raw = row.get("市場・商品区分", "")
        if market_raw not in MARKET_MAP:
            continue
        code = normalize_security_code(row.get("コード"))
        if len(code) != 4:
            skipped_share_classes.append(code)
            continue
        edinet, mapping_method = pick_edinet(row, by_code, by_name)
        companies.append((row, edinet, mapping_method))
    records = []
    for row, edinet, mapping_method in companies:
        code = normalize_security_code(row.get("コード"))
        records.append({
            "securityCode": code,
            "name": row.get("銘柄名", "").strip(),
            "market": MARKET_MAP[row.get("市場・商品区分", "")],
            "industry33Code": row.get("33業種コード", ""),
            "industry33": row.get("33業種区分", ""),
            "industry17Code": row.get("17業種コード", ""),
            "industry17": row.get("17業種区分", ""),
            "topixScaleCode": row.get("規模コード", ""),
            "topixScale": row.get("規模区分", ""),
            "edinetCode": edinet.get("ＥＤＩＮＥＴコード") if edinet else None,
            "corporateNumber": edinet.get("提出者法人番号") if edinet else None,
            "edinetName": edinet.get("提出者名") if edinet else None,
            "edinetNameEn": edinet.get("提出者名（英字）") if edinet else None,
            "address": edinet.get("所在地") if edinet else None,
            "fiscalYearEnd": edinet.get("決算日") if edinet else None,
            "consolidatedAvailable": edinet.get("連結の有無") == "有" if edinet else None,
            "edinetListedStatus": edinet.get("上場区分") if edinet else None,
            "edinetMappingMethod": mapping_method,
            "financialDataEligible": bool(edinet),
        })

    records.sort(key=lambda item: item["securityCode"])
    market_counts: dict[str, int] = {}
    for item in records:
        market_counts[item["market"]] = market_counts.get(item["market"], 0) + 1
    source_date = ""
    if jpx_rows:
        raw_date = jpx_rows[0].get("日付", "")
        if re.fullmatch(r"\d{8}", raw_date):
            source_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
    payload = {
        "dataset": "listed-companies-master",
        "sourceDate": source_date,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "jpx": JPX_LIST_URL,
            "edinetCodeList": EDINET_CODE_URL,
            "edinetCodeListAsOf": edinet_label,
        },
        "counts": {
            "companies": len(records),
            "withEdinetCode": sum(1 for item in records if item["edinetCode"]),
            "withoutEdinetCode": sum(1 for item in records if not item["edinetCode"]),
            "byMarket": market_counts,
            "skippedShareClasses": len(skipped_share_classes),
        },
        "records": records,
    }
    write_json(PUBLIC / "master.json", payload)
    print(json_summary(payload))


def json_summary(payload: dict) -> str:
    counts = payload["counts"]
    return (
        f"listed companies={counts['companies']} "
        f"edinet={counts['withEdinetCode']} missing={counts['withoutEdinetCode']} "
        f"sourceDate={payload['sourceDate']}"
    )


if __name__ == "__main__":
    main()
