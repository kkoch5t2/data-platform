#!/usr/bin/env python3
"""Private Search Console SEO opportunity snapshot (never published to site)."""
import datetime as dt
import importlib.util
import json
import pathlib
import urllib.parse
import urllib.request

spec=importlib.util.spec_from_file_location('gsc','scripts/check-gsc-sitemap.py')
g=importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
end=dt.date.today()-dt.timedelta(days=3)
start=end-dt.timedelta(days=27)
url=f'{g.API_BASE}/sites/{urllib.parse.quote(g.SITE,safe="")}/searchAnalytics/query'
token=g.access_token()
out={'start':start.isoformat(),'end':end.isoformat(),'site':g.SITE}
for dimension in ('page','query'):
    rows=[]
    for offset in range(0,100000,25000):
        body={'startDate':start.isoformat(),'endDate':end.isoformat(),'dimensions':[dimension],'rowLimit':25000,'startRow':offset}
        req=urllib.request.Request(url,data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method='POST')
        with urllib.request.urlopen(req,timeout=90) as response:
            batch=json.load(response).get('rows',[])
        rows.extend(batch)
        if len(batch)<25000:break
    out[dimension+'s']=rows
out['opportunities']=[r for r in out['pages'] if r.get('impressions',0)>=5 and (r.get('ctr',0)<0.03 or 8<=r.get('position',100)<=20)]
out['opportunities'].sort(key=lambda r:r['impressions'],reverse=True)
folder=pathlib.Path.home()/'.local/share/datlume/gsc'
folder.mkdir(parents=True,exist_ok=True)
folder.chmod(0o700)
dest=folder/('seo-'+end.isoformat()+'.json')
dest.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
dest.chmod(0o600)
print(json.dumps({'ok':True,'period':[out['start'],out['end']],'pages':len(out['pages']),'queries':len(out['querys']),'opportunities':len(out['opportunities']),'privateReport':str(dest)},ensure_ascii=False))
