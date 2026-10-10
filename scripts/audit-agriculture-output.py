#!/usr/bin/env python3
"""Compare every public municipality/product cell against the archived official workbook."""
import hashlib
import json
from collections import Counter
from pathlib import Path
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
raw = ROOT / 'data/raw/agriculture-output/2024-detail.xlsx'
public = ROOT / 'public/data/agriculture-output.json'
data = json.loads(public.read_text(encoding='utf-8'))
assert data['year'] == 2024 and data['unit'] == '千万円'
assert data['sourceSha256'] == hashlib.sha256(raw.read_bytes()).hexdigest()
products = {p['name']: i for i,p in enumerate(data['products'])}
cities = {r['code']: r for r in data['records']}
assert len(products) == 70 and len(cities) == 1719
counts = Counter()
sheet = load_workbook(raw, read_only=True, data_only=True).active
for row in list(sheet.values)[1:]:
    code = f'{int(row[1]):02d}{int(row[2]):03d}'
    index = products[row[8]]
    assert cities[code]['prefecture'] == row[4] and cities[code]['city'] == row[5]
    observed = cities[code]['values'][index]
    assert observed == row[9], (code,row[8],row[9],observed)
    counts['number' if isinstance(observed,int) else observed] += 1
assert sum(counts.values()) == 120330
assert counts == data['statusCounts']
assert cities['32202']['values'][products['農業産出額']] == 717
assert cities['32204']['values'][products['農業産出額']] == 1019
print('agriculture source audit PASS: 120330 cells, 1719 municipalities, 70 items, corrections and status markers')
