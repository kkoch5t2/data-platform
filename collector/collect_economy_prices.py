#!/usr/bin/env python3
import json, re, subprocess, tempfile, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
try:
    from core.source_run import SourceRun
except ModuleNotFoundError:
    from collector.core.source_run import SourceRun

ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'public/data/economy-prices.json'
INDEX='https://www.stat.go.jp/data/kouri/kouzou/gaiyou.htm'; UA={'User-Agent':'Mozilla/5.0 DATLUME/1.0'}
PREFS=['北海道','青森県','岩手県','宮城県','秋田県','山形県','福島県','茨城県','栃木県','群馬県','埼玉県','千葉県','東京都','神奈川県','新潟県','富山県','石川県','福井県','山梨県','長野県','岐阜県','静岡県','愛知県','三重県','滋賀県','京都府','大阪府','兵庫県','奈良県','和歌山県','鳥取県','島根県','岡山県','広島県','山口県','徳島県','香川県','愛媛県','高知県','福岡県','佐賀県','長崎県','熊本県','大分県','宮崎県','鹿児島県','沖縄県']
FIELDS=['overall','overallExRent','food','housing','utilities','household','clothing','medical','transport','education','recreation','misc']
LABELS={'overall':'総合','overallExRent':'家賃を除く総合','food':'食料','housing':'住居','utilities':'光熱・水道','household':'家具・家事用品','clothing':'被服及び履物','medical':'保健医療','transport':'交通・通信','education':'教育','recreation':'教養娯楽','misc':'諸雑費'}

def fetch(url):
    req=urllib.request.Request(url,headers=UA)
    with urllib.request.urlopen(req,timeout=90) as r: return r.read()

def latest_pdf():
    html=fetch(INDEX).decode('utf-8','ignore')
    found=re.findall(r'href=["\']([^"\']*?/pdf/g_(20\d{2})\.pdf)["\']',html)
    if not found: raise RuntimeError('latest regional price PDF not found')
    href,year=max(found,key=lambda x:int(x[1]))
    return int(year),urljoin(INDEX,href)

def numbers(s):
    return [float(x) for x in re.findall(r'\d+\.\d+|\d+',s)]

def parse_table(pdf_bytes):
    with tempfile.TemporaryDirectory() as td:
        pdf=Path(td)/'source.pdf'; txt=Path(td)/'source.txt'; pdf.write_bytes(pdf_bytes)
        subprocess.run(['pdftotext','-layout',str(pdf),str(txt)],check=True)
        lines=txt.read_text(encoding='utf-8',errors='ignore').splitlines()
    first={}; second={}
    for raw in lines:
        s=' '.join(raw.split())
        for pref in PREFS:
            if pref not in first and s.startswith(pref):
                vals=numbers(s[len(pref):])
                if len(vals)>=12: first[pref]=vals[:12:2]
            if pref not in second and s.endswith(pref):
                vals=numbers(s[:-len(pref)])
                if len(vals)>=12: second[pref]=vals[:12:2]
    missing=[p for p in PREFS if p not in first or p not in second]
    if missing: raise RuntimeError('could not parse prefectures: '+','.join(missing))

    records=[]
    for pref in PREFS:
        vals=first[pref]+second[pref]
        records.append({'prefecture':pref,**{k:round(v,1) for k,v in zip(FIELDS,vals)}})
    return records

def main():
    year,url=latest_pdf(); pdf=fetch(url); records=parse_table(pdf)
    extremes={}
    for key in FIELDS:
        ordered=sorted(records,key=lambda r:r[key])
        extremes[key]={'min':{'prefecture':ordered[0]['prefecture'],'value':ordered[0][key]},'max':{'prefecture':ordered[-1]['prefecture'],'value':ordered[-1][key]}}
    payload={'schemaVersion':1,'year':year,'base':100,'source':'総務省統計局 小売物価統計調査（構造編） 消費者物価地域差指数','sourceUrl':url,'generatedAt':datetime.now(timezone.utc).isoformat(),'labels':LABELS,'records':records,'extremes':extremes}
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print(f'economy-prices: {len(records)} prefectures / {year} -> {OUT}')
    return {'records':len(records),'year':year}

if __name__=='__main__':
    with SourceRun('economy_prices','総務省統計局 小売物価統計調査（構造編）') as run:
        run.set_metrics(**main())
