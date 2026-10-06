#!/usr/bin/env python3
"""Validate station identity, locality, axes, measurements, and published shards."""
import json
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

root = Path(__file__).resolve().parents[1]
base = root / "public/data/weather"
index = json.loads((base/"index.json").read_text())
assert index["schemaVersion"] == 1
assert index["sourceUrl"] == "https://www.data.jma.go.jp/risk/obsdl/"
assert len(index["masterSha256"]) == 64
assert len(index["stations"]) == index["stationCount"] >= 1200
assert index["usableStationCount"] >= 1200
assert index["municipalityMappedCount"] >= 1280
months, days = index["months"], index["days"]
assert months[0] == "2015-01" and len(months) >= 140 and months == sorted(set(months))
assert len(days) == 366 and days == sorted(set(days))
assert date.fromisoformat(days[-1]) - date.fromisoformat(days[0]) == timedelta(days=365)
canonical = json.loads((root/"public/data/municipality-stats-2026.json").read_text())["records"]
municipality = {r["code"]:(r["prefecture"],r["municipality"]) for r in canonical}
assert len({s["id"] for s in index["stations"]}) == index["stationCount"]
seen, usable = set(), 0
for code in index["regions"]:
    payload = json.loads((base/(code+".json")).read_text())
    assert payload["schemaVersion"] == 1 and payload["regionCode"] == code
    assert payload["months"] == months and payload["days"] == days
    for row in payload["records"]:
        sid = row["id"]
        assert sid not in seen and row["regionCode"] == code
        seen.add(sid)
        assert 20 <= row["lat"] <= 46 and 122 <= row["lon"] <= 154
        if row["municipalityCode"]:
            assert municipality[row["municipalityCode"]] == (row["prefecture"],row["municipality"])
            assert row["address"]
        assert len(row["monthly"]) == len(months),sid
        assert len(row["daily"]) == len(days),sid
        valid = False
        for period in ("monthly","daily"):
            for temp,rain in row[period]:
                assert temp is None or -50 <= temp <= 50,(sid,temp)
                assert rain is None or 0 <= rain <= 10000,(sid,rain)
                valid |= temp is not None or rain is not None
        usable += valid
assert seen == {s["id"] for s in index["stations"]}
assert usable == index["usableStationCount"]
tokyo = next(r for r in json.loads((base/"44.json").read_text())["records"] if r["id"]=="s47662")
assert tokyo["municipality"] == "千代田区" and tokyo["municipalityCode"] == "13101"
assert {s["municipalityCode"] for s in index["stations"] if s["name"] in ("八丈島","八重見ヶ原")} == {"13401"}
assert next(s for s in index["stations"] if s["name"]=="梼原")["municipalityCode"] == "39405"
assert 0 <= tokyo["monthly"][months.index("2025-01")][0] <= 15
assert 0 <= tokyo["monthly"][months.index("2025-01")][1] <= 300
assert len(set(r["municipalityCode"] for r in index["stations"] if r["municipalityCode"])) >= 600
print(f"jma-weather: {len(seen)} stations, {index['municipalityMappedCount']} mapped, {len(months)} months, {len(days)} days; Tokyo anchor OK")
