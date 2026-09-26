#!/usr/bin/env python3
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote
import json, re, sys

ROOT=Path(__file__).resolve().parents[1]
DIST=ROOT/'dist'
errors=[]
checks=0
target_cache={}
company_path=ROOT/'src'/'data'/'companies.json'
company_ids={x.get('id') for x in json.loads(company_path.read_text(encoding='utf-8'))} if company_path.exists() else set()

def check(cond,msg):
    global checks
    checks+=1
    if not cond: errors.append(msg)

class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_title=False; self.in_script=0; self.in_style=0
        self.title=[]; self.visible=[]; self.refs=[]; self.h1=[]; self.in_h1=0
        self.viewport=False; self.favicon=False; self.canonical=False
        self.brand_depth=0; self.brand_has_logo=False; self.brand_seen=False
    def handle_starttag(self,tag,attrs):
        d=dict(attrs)
        if tag=='title': self.in_title=True
        if tag=='script': self.in_script+=1
        if tag=='style': self.in_style+=1
        if tag=='h1': self.in_h1+=1
        if tag=='meta' and d.get('name')=='viewport': self.viewport=True
        if tag=='link' and d.get('rel')=='icon' and d.get('href')=='/favicon.svg': self.favicon=True
        if tag=='link' and d.get('rel')=='canonical' and d.get('href'): self.canonical=True
        classes=set((d.get('class') or '').split())
        if tag=='a' and 'brand' in classes:
            self.brand_seen=True; self.brand_depth=1
        elif self.brand_depth:
            self.brand_depth+=1
        if tag=='img' and self.brand_depth and d.get('src')=='/favicon.svg':
            self.brand_has_logo=True
        for k in ('href','src'):
            if d.get(k): self.refs.append(d[k])
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if self.brand_depth: self.brand_depth=max(0,self.brand_depth-1)
    def handle_endtag(self,tag):
        if tag=='title': self.in_title=False
        if tag=='script' and self.in_script: self.in_script-=1
        if tag=='style' and self.in_style: self.in_style-=1
        if tag=='h1' and self.in_h1: self.in_h1-=1
        if self.brand_depth:
            self.brand_depth-=1
    def handle_data(self,data):
        if self.in_title: self.title.append(data)
        if self.in_h1: self.h1.append(data)
        if not self.in_script and not self.in_style: self.visible.append(data)

def route_for(file):
    rel=file.relative_to(DIST).as_posix()
    if rel=='index.html': return '/'
    if rel.endswith('/index.html'): return '/'+rel[:-10]
    return '/'+rel

def target_exists(route,ref):
    key=(route,ref)
    if key in target_cache:return target_cache[key]
    if not ref or ref.startswith(('#','mailto:','tel:','javascript:','data:','blob:')):
        target_cache[key]=True;return True
    u=urlparse(ref)
    if u.scheme in ('http','https') or u.netloc:
        target_cache[key]=True;return True
    path=unquote(urlparse(urljoin('https://datlume.com'+route,ref)).path)
    m=re.fullmatch(r'/procurement/companies/(co_[0-9a-f]{12})/?',path)
    if m:
        exists=m.group(1) in company_ids; target_cache[key]=exists; return exists
    rel=path.lstrip('/')
    cand=DIST/rel
    if path.endswith('/'): cand=cand/'index.html'
    elif cand.exists(): pass
    elif not Path(path).suffix: cand=cand/'index.html'
    exists=cand.exists()
    target_cache[key]=exists
    return exists

files=sorted(DIST.rglob('*.html'))
check(1000<len(files)<5000,f'generated html count outside dynamic-company architecture range: {len(files)}')
for file in files:
    route=route_for(file)
    try: raw=file.read_text(encoding='utf-8')
    except Exception as e:
        errors.append(f'{route}: read failed {e}');continue
    p=PageParser()
    try:p.feed(raw)
    except Exception as e:
        errors.append(f'{route}: parse failed {e}');continue
    is404=route=='/404.html'
    title=' '.join(''.join(p.title).split())
    h1=' '.join(''.join(p.h1).split())
    text=' '.join(' '.join(p.visible).split())
    check(bool(title),f'{route}: missing title')
    check(p.viewport,f'{route}: missing viewport')
    check(p.favicon,f'{route}: missing favicon link')
    if not is404:
        check(bool(h1),f'{route}: missing h1')
        check(p.canonical,f'{route}: missing canonical')
        header_match=re.search(r'<header\b[\s\S]*?</header>',raw,re.I)
        header_logo=bool(header_match and re.search(r'<img\b[^>]*src=["\']/favicon\.svg["\']',header_match.group(0),re.I))
        check(header_logo,f'{route}: header logo icon missing')
    if p.brand_seen:
        check(p.brand_has_logo,f'{route}: brand logo icon missing')
    check(not re.search(r'(^|\W)(?:undefined|NaN)(\W|$)',text),f'{route}: visible undefined/NaN')
    for ref in p.refs:
        if not target_exists(route,ref):
            errors.append(f'{route}: broken local ref {ref}')
            if len(errors)>500: break
    if len(errors)>500: break

print(f'html audit: {len(files)} pages, {checks} checks, {len(errors)} failures')
for e in errors[:120]: print('FAIL',e)
if len(errors)>120: print(f'... and {len(errors)-120} more')
sys.exit(1 if errors else 0)
