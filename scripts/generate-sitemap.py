#!/usr/bin/env python3
import json, os
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape
ROOT=Path(__file__).resolve().parents[1]
DIST=ROOT/'dist'
BASE=os.environ.get('SITE_URL','https://datlume.com').rstrip('/')
urls=[]
for p in sorted(DIST.rglob('index.html')):
    rel=p.relative_to(DIST)
    parts=list(rel.parts[:-1])
    if any(x.startswith('_') for x in parts): continue
    route='/'+'/'.join(quote(x,safe='') for x in parts)
    if route!='/' and not route.endswith('/'): route+='/'
    urls.append(BASE+route)
master_path=ROOT/'public/data/listed-companies/master.json'
if master_path.exists():
    master=json.loads(master_path.read_text(encoding='utf-8'))
    for company in master.get('records',[]):
        code=company.get('securityCode')
        if code:
            urls.append(f"{BASE}/listed-companies/{quote(str(code),safe='')}/")
company_path=ROOT/'src'/'data'/'companies.json'
if company_path.exists():
    for company in json.loads(company_path.read_text(encoding='utf-8')):
        cid=str(company.get('id') or '')
        if cid: urls.append(BASE+'/procurement/companies/'+quote(cid,safe='')+'/')
urls=sorted(set(urls))
if len(urls)>50000: raise SystemExit(f'sitemap URL limit exceeded: {len(urls)}')
xml=['<?xml version="1.0" encoding="UTF-8"?>','<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
for u in urls: xml.append(f'  <url><loc>{escape(u)}</loc></url>')
xml.append('</urlset>')
(DIST/'sitemap.xml').write_text('\n'.join(xml)+'\n',encoding='utf-8')
print(f'sitemap: {len(urls)} URLs -> {DIST/"sitemap.xml"}')
