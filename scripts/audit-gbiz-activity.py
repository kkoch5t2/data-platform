#!/usr/bin/env python3
from __future__ import annotations
import csv
import io
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "public/data"
RAW = ROOT / "data/raw/company-registry/gbiz"


def read(relative):
    return json.loads((DATA / relative).read_text(encoding="utf-8"))


def entries(area):
    result = {}
    for path in sorted((DATA / area / "details").glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for key, row in payload["c"].items():
            assert key not in result, (area, key)
            result[key] = row
    assert len(list((DATA / area / "details").glob("*.json"))) == 64
    return result


listed = entries("listed-companies")
unlisted = entries("company-registry")
listed_index = {r["securityCode"]: r for r in read("listed-companies/index.json")["records"]}
unlisted_index = {r["entityKey"]: r for r in read("company-registry/unlisted-index.json")["records"]}
summaries = {area: read(f"{area}/summary.json") for area in ("listed-companies", "company-registry")}
assert set(listed) == set(listed_index)
assert set(unlisted) == set(unlisted_index)
for area, records, index in (("listed-companies", listed, listed_index), ("company-registry", unlisted, unlisted_index)):
    summary = summaries[area]
    sources = summary["activitySources"] if area == "listed-companies" else summary["sources"]["gbizActivity"]
    for kind, prefix in (("subsidy", "Hojokinjoho"), ("patent", "Tokkyojoho")):
        path = RAW / sources[kind]["sourceFile"]
        assert path.name.startswith(prefix) and path.is_file()
        assert re.fullmatch(r"20\d{2}-\d{2}-\d{2}", sources[kind]["sourceDate"])
        assert sources[kind]["sourceDate"].replace("-", "") in path.name
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None
    counts = {"subsidies": 0, "patents": 0}
    for key, row in records.items():
        number = row["company"].get("corporateNumber") if area == "listed-companies" else row["corporateNumber"]
        activity = row.get("activity") or {}
        if activity:
            assert re.fullmatch(r"\d{13}", number), (area, key)
        for metric, flag in (("subsidies", "hasSubsidies"), ("patents", "hasPatents")):
            value = activity.get(metric)
            if area == "company-registry":
                assert bool(value) == bool(index[key][flag]), (area, key, metric)
            if not value:
                continue
            counts[metric] += 1
            assert 0 < len(value["recent"]) <= min(8 if metric == "subsidies" else 20, value["count"])
            assert value["sourceDate"] == sources["subsidy" if metric == "subsidies" else "patent"]["sourceDate"]
            if metric == "patents":
                registrations = [v["registration"] for v in value["recent"]]
                assert len(registrations) == len(set(registrations))
                assert value["recent"] == sorted(value["recent"], key=lambda x: (x["applicationDate"], x["registration"]), reverse=True)
            else:
                for item in value["recent"]:
                    assert item["amount"] is None or isinstance(item["amount"], int)
                    assert item["name"]
    assert counts["subsidies"] == summary["subsidyCompanies" if area == "listed-companies" else "unlistedSubsidyCompanies"]
    assert counts["patents"] == summary["patentCompanies" if area == "listed-companies" else "unlistedPatentCompanies"]
    print(area, len(records), counts)

# Independent source anchors for a sampled listed and unlisted company with data.
samples = []
for records in (listed, unlisted):
    sample = next(row for row in records.values() if (row.get("activity") or {}).get("patents") and (row.get("activity") or {}).get("subsidies"))
    number = sample["company"].get("corporateNumber") if "company" in sample else sample["corporateNumber"]
    samples.append((number, sample["activity"]))
expected = {number: {"subsidies": set(), "patents": set()} for number, _ in samples}
for kind, prefix in (("subsidies", "Hojokinjoho"), ("patents", "Tokkyojoho")):
    path = sorted(RAW.glob(f"{prefix}_UTF-8_*.zip"))[-1]
    with zipfile.ZipFile(path) as archive:
        with archive.open(archive.namelist()[0]) as raw:
            for row in csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")):
                target = expected.get(row["法人番号"])
                if target is None:
                    continue
                if kind == "patents":
                    if row["特許/意匠/商標"] == "特許" and row["登録番号"].strip():
                        target[kind].add(row["登録番号"].strip())
                elif row["名称"].strip():
                    amount = row["金額"].strip().replace(",", "")
                    assert not amount or re.fullmatch(r"-?\d+", amount)
                    target[kind].add((row["証明日"].strip(), row["名称"].strip(), int(amount) if amount else None, row["対象"].strip(), row["発行元"].strip()))
for number, activity in samples:
    for kind in ("patents", "subsidies"):
        assert len(expected[number][kind]) == activity[kind]["count"], (number, kind)
print("raw source anchors matched", [n for n, _ in samples])
