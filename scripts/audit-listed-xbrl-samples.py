#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import zipfile
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from collector.listed_companies.salary import recover_average_salary
RAW = ROOT / "data/raw/listed-companies"
NORMALIZED = RAW / "normalized/financials.json"
METRICS = (
    "revenue", "operatingIncome", "ordinaryIncome", "profitBeforeTax",
    "netIncome", "assets", "liabilities", "equity", "cash",
    "operatingCashFlow", "investingCashFlow", "financingCashFlow",
    "employees", "averageSalary",
)


def numeric(text: str):
    try:
        return Decimal(text.strip().replace(",", ""))
    except (InvalidOperation, AttributeError):
        return None


def public_xbrl_roots(path: Path):
    roots = []
    with zipfile.ZipFile(path) as archive:
        names = [
            name for name in archive.namelist()
            if name.lower().endswith(".xbrl") and "publicdoc" in name.lower()
        ]
        for name in names:
            try:
                roots.append(ET.fromstring(archive.read(name)))
            except ET.ParseError:
                pass
    return roots


def values_for(roots, local_name: str, context: str):
    values = []
    for root in roots:
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] != local_name:
                continue
            if element.attrib.get("contextRef") != context:
                continue
            value = numeric(element.text or "")
            if value is not None:
                values.append(value)
    return values


def main() -> int:
    if not NORMALIZED.exists():
        print("listed XBRL audit: normalized data missing")
        return 2
    payload = json.loads(NORMALIZED.read_text(encoding="utf-8"))
    checks = 0
    failures = []
    audited_companies = 0
    for record in payload.get("records", []):
        archive = RAW / "xbrl" / f"{record['docID']}.zip"
        if not archive.exists():
            continue
        roots = public_xbrl_roots(archive)
        if not roots:
            failures.append(f"{record['securityCode']}: no PublicDoc XBRL")
            continue
        audited_companies += 1
        for metric in METRICS:
            source = record.get("metricSources", {}).get(metric)
            value = record.get("metrics", {}).get(metric)
            if not source or value is None:
                continue
            checks += 1
            expected = Decimal(str(value))
            if metric == "averageSalary" and source.get("presentationRecovery"):
                recovered, _ = recover_average_salary(archive)
                if recovered is None or Decimal(str(recovered)) != expected:
                    failures.append(
                        f"{record['securityCode']} {metric}: presentation {recovered} != {expected}"
                    )
                continue
            local_name = source["concept"].rsplit(":", 1)[-1]
            found = values_for(roots, local_name, source["context"])
            if expected not in found:
                failures.append(
                    f"{record['securityCode']} {metric}: {expected} not in {found[:4]}"
                )
    if audited_companies == 0:
        print("listed XBRL audit: no local sample archives; skipped")
        return 0
    print(
        f"listed XBRL audit: {audited_companies} companies, "
        f"{checks} checks, {len(failures)} failures"
    )
    for failure in failures[:50]:
        print("FAIL", failure)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
