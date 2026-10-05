#!/usr/bin/env python3
"""Guard official IPSS projection coverage, raw provenance and census baseline."""
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
data = json.loads((ROOT / "public/data/municipality-population-projections.json").read_text())
assert data["years"] == list(range(2020, 2051, 5))
assert data["projectionYears"] == list(range(2025, 2051, 5))
assert data["metrics"] == ["population", "under15", "workingAge", "elderly"]
records = data["records"]
assert len(records) == 1951
assert Counter(r["kind"] for r in records) == {"a": 47, "0": 198, "1": 20, "2": 769, "3": 916, "9": 1}
assert len({r["code"] for r in records}) == len(records)
assert sum("lon" in r for r in records if r["kind"] != "a") == 1728
assert set(data["workbooksSha256"]) == {"kekkahyo1.xlsx", "kekkahyo2_1.xlsx", "kekkahyo2_2.xlsx", "kekkahyo2_3.xlsx"}
for name, digest in data["workbooksSha256"].items():
    raw = ROOT / "data/raw/ipss-shicyoson-2023" / name
    if raw.exists():
        assert hashlib.sha256(raw.read_bytes()).hexdigest() == digest, name
base = {r["code"]: r for r in json.loads((ROOT / "public/data/municipality-stats-2026.json").read_text())["records"]}
for r in records:
    assert len(r["values"]) == len(data["years"])
    for year, values in zip(data["years"], r["values"]):
        assert len(values) == 4 and all(isinstance(v, int) and v >= 0 for v in values)
        assert sum(values[1:]) <= values[0]
        if year > 2020:
            assert sum(values[1:]) == values[0], (r["code"], year)
    if r["code"] in base:
        assert r["values"][0][0] == base[r["code"]]["population"]
        assert r["municipality"] == base[r["code"]]["municipality"]
hamadori = [r for r in records if r["kind"] == "9"]
assert len(hamadori) == 1 and hamadori[0]["prefecture"] == "福島県"
assert hamadori[0]["code"] == "07999" and hamadori[0]["municipality"] == "浜通り地域"
assert {r["code"] for r in base.values()} - {r["code"] for r in records} == {"07204", "07209", "07212", "07541", "07542", "07543", "07544", "07545", "07546", "07547", "07548", "07561", "07564"}
assert next(r for r in records if r["code"] == "01100")["values"][-1][0] == 1745608
assert next(r for r in records if r["code"] == "13101")["values"][-1][0] == 79828
print("IPSS audit: 1,884 official regions + 20 designated-city aggregates + 47 prefectures; 2020 census aligned")
