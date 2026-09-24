#!/usr/bin/env python3
import os
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape
ROOT=Path(__file__).resolve().parents[1]
DIST=ROOT/'dist'
BASE=os.environ.get('SITE_URL','https://datlume.pages.dev').rstrip('/')
urls=[]
for p in sorted(DIST.rglob('index.html')):
    rel=p.relative_to(DIST)
    parts=list(rel.parts[:-1])
    if any(x.startswith('_') for x in parts): continue
    route='/'+'/'.join(quote(x,safe='') for x in parts)
    if route!='/' and not route.endswith('/'): route+='/'
    urls.append(BASE+route)
xml=['<?xml version="1.0" encoding="UTF-8"?>','<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
for u in urls: xml.append(f'  <url><loc>{escape(u)}</loc></url>')
xml.append('</urlset>')
(DIST/'sitemap.xml').write_text('\n'.join(xml)+'\n',encoding='utf-8')
print(f'sitemap: {len(urls)} URLs -> {DIST/"sitemap.xml"}')
