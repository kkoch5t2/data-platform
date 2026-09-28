#!/usr/bin/env python3
import csv
import random
import sqlite3
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'data' / 'public_it.db'
OLD_DB = ROOT / 'tmp' / 'classifier-before.db'
OUT = ROOT / 'tmp' / 'classifier-review.tsv'
SEED = 20260927
RANDOM_PER_CATEGORY = 12
TOP_PER_CATEGORY = 8
CHANGED_PER_CATEGORY = 10

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
categories = [r[0] for r in conn.execute(
    "select category from procurements group by category order by category"
)]
print('categories=', len(categories))

reservoir = defaultdict(list)
seen = defaultdict(int)
rng = random.Random(SEED)
for row in conn.execute("select source_id,title,category,agency,award_amount,source_url from procurements order by source_id"):
    cat = row['category'] or 'その他'
    seen[cat] += 1
    bucket = reservoir[cat]
    item = tuple(row)
    if len(bucket) < RANDOM_PER_CATEGORY:
        bucket.append(item)
    else:
        j = rng.randrange(seen[cat])
        if j < RANDOM_PER_CATEGORY:
            bucket[j] = item
conn.execute("attach database ? as olddb", (str(OLD_DB),))

def top_rows(cat):
    return [tuple(r) for r in conn.execute(
        """select source_id,title,category,agency,award_amount,source_url
           from procurements where category=?
           order by coalesce(award_amount,0) desc, source_id limit ?""",
        (cat, TOP_PER_CATEGORY),
    )]

def changed_rows(cat):
    return [tuple(r) for r in conn.execute(
        """select n.source_id,n.title,n.category,n.agency,n.award_amount,n.source_url
           from procurements n join olddb.procurements o using(source_id)
           where n.category=? and coalesce(o.category,'')<>coalesce(n.category,'')
           order by coalesce(n.award_amount,0) desc, n.source_id limit ?""",
        (cat, CHANGED_PER_CATEGORY),
    )]

with OUT.open('w', encoding='utf-8', newline='') as f:
    w = csv.writer(f, delimiter='\t')
    w.writerow(['category','sample_type','source_id','title','agency','award_amount','source_url'])
    total = 0
    for cat in categories:
        chosen = []
        used = set()
        for sample_type, rows in (
            ('top', top_rows(cat)),
            ('changed', changed_rows(cat)),
            ('random', reservoir.get(cat, [])),
        ):
            for source_id,title,category,agency,amount,url in rows:
                if source_id in used:
                    continue
                used.add(source_id)
                chosen.append((cat,sample_type,source_id,title,agency,amount,url))
        for row in chosen:
            w.writerow(row)
        print(f'{cat}\tcount={seen[cat]}\tsamples={len(chosen)}')
        total += len(chosen)
print('review_rows=', total)
print('output=', OUT)
