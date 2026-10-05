#!/usr/bin/env python3
import json
from pathlib import Path

root=Path(__file__).resolve().parents[1]
data=json.loads((root/"public/data/lodging-statistics.json").read_text())
months=data["months"]
records=data["records"]
assert data["schemaVersion"]==1
assert len(records)==48 and len(data["prefectures"])==48
assert data["prefectures"]==[r["prefecture"] for r in records]
assert data["prefectures"][0]=="全国"
assert months[0]=="2011-01" and months==sorted(set(months))
assert len(months)>=187 and months[-1][5:]<="12"
assert data["sourceUrl"].startswith("https://www.mlit.go.jp/kankocho/")
assert data["workbookUrl"].startswith("https://www.mlit.go.jp/kankocho/content/")
assert len(data["sha256"])==64
for record in records:
    values=record["values"]
    assert len(values)==len(months),record["prefecture"]
    for total,japanese,foreign,occupancy in values:
        assert isinstance(total,int) and total>=0
        assert japanese is None or (isinstance(japanese,int) and japanese>=0)
        assert foreign is None or (isinstance(foreign,int) and foreign>=0)
        assert japanese is None or foreign is None or abs(total-japanese-foreign)<=20
        assert occupancy is None or 0<=occupancy<=100
idx=months.index("2025-07")
assert records[0]["values"][idx][0]>40000000
annual=sum(records[0]["values"][months.index(f"2025-{month:02d}")][0] for month in range(1,13))
assert abs(annual-661105480)<=120,annual
hokkaido=sum(records[1]["values"][months.index(f"2025-{month:02d}")][0] for month in range(1,13))
assert abs(hokkaido-46503620)<=120,hokkaido
assert records[0]["values"][-1][0]>=10000000
print(f"lodging-statistics: {len(records)} areas × {len(months)} months, latest {months[-1]}; 2025 annual anchors matched")
