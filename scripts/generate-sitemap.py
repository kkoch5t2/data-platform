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
listed_index_path=ROOT/'public/data/listed-companies/index.json'
if listed_index_path.exists():
    listed_index=json.loads(listed_index_path.read_text(encoding='utf-8'))
    for company in listed_index.get('records',[]):
        code=company.get('securityCode')
        if code and company.get('hasFinancials') is True:
            urls.append(f"{BASE}/listed-companies/{quote(str(code),safe='')}/")
unlisted_index_path=ROOT/'public/data/company-registry/unlisted-index.json'
if unlisted_index_path.exists():
    unlisted_index=json.loads(unlisted_index_path.read_text(encoding='utf-8'))
    for company in unlisted_index.get('records',[]):
        corporate_number=str(company.get('corporateNumber') or '')
        if corporate_number: urls.append(BASE+'/unlisted-companies/'+quote(corporate_number,safe='')+'/')
company_path=ROOT/'src'/'data'/'companies.json'
if company_path.exists():
    for company in json.loads(company_path.read_text(encoding='utf-8')):
        cid=str(company.get('id') or '')
        if cid: urls.append(BASE+'/procurement/companies/'+quote(cid,safe='')+'/')
urls=sorted(set(urls))
for old in DIST.glob('sitemap-*.xml'): old.unlink()
chunk_size=45000
if len(urls)<=50000:
    xml=['<?xml version="1.0" encoding="UTF-8"?>','<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls: xml.append(f'  <url><loc>{escape(u)}</loc></url>')
    xml.append('</urlset>')
    (DIST/'sitemap.xml').write_text('\n'.join(xml)+'\n',encoding='utf-8')
    print(f'sitemap: {len(urls)} URLs -> {DIST/"sitemap.xml"}')
else:
    names=[]
    for part,start in enumerate(range(0,len(urls),chunk_size),1):
        name=f'sitemap-{part:03d}.xml'; names.append(name)
        xml=['<?xml version="1.0" encoding="UTF-8"?>','<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        for u in urls[start:start+chunk_size]: xml.append(f'  <url><loc>{escape(u)}</loc></url>')
        xml.append('</urlset>')
        (DIST/name).write_text('\n'.join(xml)+'\n',encoding='utf-8')
    index=['<?xml version="1.0" encoding="UTF-8"?>','<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for name in names:index.append(f'  <sitemap><loc>{escape(BASE+"/"+name)}</loc></sitemap>')
    index.append('</sitemapindex>')
    (DIST/'sitemap.xml').write_text('\n'.join(index)+'\n',encoding='utf-8')
    print(f'sitemap: {len(urls)} URLs -> {len(names)} shards + sitemap.xml index')
