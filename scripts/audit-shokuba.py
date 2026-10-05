#!/usr/bin/env python3
"""Independent original CSV -> normalized -> public workplace verification."""
import csv
import hashlib
import io
import json
import re
import unicodedata
import sqlite3
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from collector.collect_shokuba import DB, RAW, SPECS, HIRING

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
meta = dict(conn.execute("SELECT key,value FROM metadata"))
normalized = {number: json.loads(payload) for number, payload in conn.execute("SELECT corporate_number,payload FROM workplaces")}
conn.close()
archives = list(RAW.glob("*.zip"))
archive = next((p for p in archives if hashlib.sha256(p.read_bytes()).hexdigest() == meta["sha256"]), None)
assert archive, "Original archive is missing"
seen = set()
checks = 0
with zipfile.ZipFile(archive) as z:
    reader = csv.DictReader(io.TextIOWrapper(z.open(meta["sourceFile"]), encoding="cp932", newline=""))
    total = 0
    for raw in reader:
        total += 1
        corp = raw["法人番号"].strip()
        assert corp not in seen, f"Duplicate corporate number {corp}"
        seen.add(corp)
        item = normalized.get(corp)
        if not item:
            continue
        assert item["corporateNumber"] == corp
        assert item["sourceName"] == raw["企業名"].strip()
        assert item["sourceUpdatedAt"] == raw["更新日時"].strip()
        assert item["sourceDate"] == meta["sourceDate"]
        for key, column, _, unit, scope_column, note_column in SPECS:
            m = item["metrics"].get(key)
            if m is None:
                continue
            assert m["display"] == raw[column].strip(), (corp, key, "raw value")
            number_text = unicodedata.normalize("NFKC", raw[column].strip())
            match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*" + re.escape(unit), number_text)
            assert match and m["value"] == float(match[1]), (corp, key, "numeric mismatch")
            assert m["unit"] == unit and m["value"] >= 0
            assert m["sourceColumn"] == column
            assert m["note"] == (raw[note_column].strip() if note_column else "")
            expected_scope = "正社員" if key == "paidLeaveDays" else raw[scope_column].strip() if scope_column else ""
            assert m["scope"] == expected_scope, (corp, key, "scope")
            checks += 6
        for key, (_, prefix) in HIRING.items():
            for field, suffix in [("hires", "-男女計"), ("leavers", "-離職者数")]:
                values = item["hiring"].get(key, {}).get(field)
                if values is not None:
                    assert "/".join(v["display"] for v in values) == raw[prefix + suffix].strip()
                    checks += 1
assert total == int(meta["records"])
assert len(normalized) == int(meta["usableCompanies"])

coverage = {}
for folder, number_path, index_key, summary_key in [
    ("company-registry", ("corporateNumber",), "corporateNumber", "unlistedWorkplaceCompanies"),
    ("listed-companies", ("company", "corporateNumber"), "securityCode", "workplaceCompanies"),
]:
    base = ROOT / "public/data" / folder
    items = {}
    for path in (base / "details").glob("*.json"):
        items.update(json.loads(path.read_text())["c"])
    count = 0
    for key, item in items.items():
        number = item
        for part in number_path:
            number = number.get(part) if isinstance(number, dict) else None
        expected = normalized.get(str(number or ""))
        assert item.get("workplace") == expected, (folder, key, "public mismatch")
        count += bool(expected)
        checks += 1
    index = json.loads((base / ("unlisted-index.json" if folder == "company-registry" else "index.json")).read_text())["records"]
    for item in index:
        assert item.get("hasWorkplace") == bool(items[str(item[index_key])].get("workplace"))
        checks += 1
    summary = json.loads((base / "summary.json").read_text())
    assert summary[summary_key] == count
    coverage[folder] = count
assert (ROOT / "public/workplace.css").exists()
print(json.dumps({"checks": checks, "sourceRows": total, "usableCompanies": len(normalized), "published": coverage, "failures": 0}, ensure_ascii=False))
