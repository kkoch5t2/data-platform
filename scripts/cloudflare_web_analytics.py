#!/usr/bin/env python3
import argparse, json, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

ACCOUNT='0889f537a65cecd76c67d146250b6a4b'
HOST='datlume.pages.dev'
TOKEN_FILE=Path.home()/'.datlume-cloudflare-token'
API='https://api.cloudflare.com/client/v4'

def api(method,path,body=None):
    token=TOKEN_FILE.read_text().strip()
    data=None if body is None else json.dumps(body).encode()
    req=urllib.request.Request(API+path,data=data,method=method,headers={'Authorization':f'Bearer {token}','Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=30) as r:return json.load(r)
    except urllib.error.HTTPError as e:return json.load(e)

def site_tag():
    x=api('GET',f'/accounts/{ACCOUNT}/rum/site_info/list')
    site=next((s for s in (x.get('result') or []) if s.get('host')==HOST),None)
    if not site: raise RuntimeError(f'Web Analytics site not found: {x.get("errors")}')
    return site['site_tag']

def graphql(query,variables):
    x=api('POST','/graphql',{'query':query,'variables':variables})
    if x.get('errors'): raise RuntimeError(x['errors'])
    return x['data']

def fetch(days):
    end=datetime.now(timezone.utc).replace(microsecond=0)
    start=end-timedelta(days=days)
    tag=site_tag()
    flt={'datetime_geq':start.isoformat().replace('+00:00','Z'),'datetime_lt':end.isoformat().replace('+00:00','Z'),'siteTag':tag,'requestHost':HOST}
    q='''query($accountTag:String!,$filter:AccountRumPageloadEventsAdaptiveGroupsFilter_InputObject){viewer{accounts(filter:{accountTag:$accountTag}){total:rumPageloadEventsAdaptiveGroups(limit:1,filter:$filter){count sum{visits}} topPages:rumPageloadEventsAdaptiveGroups(limit:20,filter:$filter,orderBy:[count_DESC]){count sum{visits} dimensions{requestPath}} daily:rumPageloadEventsAdaptiveGroups(limit:100,filter:$filter,orderBy:[date_ASC]){count sum{visits} dimensions{date}}}}}'''
    data=graphql(q,{'accountTag':ACCOUNT,'filter':flt})
    account=data['viewer']['accounts'][0]
    total=(account.get('total') or [{}])[0]
    return {'host':HOST,'range':{'days':days,'start':flt['datetime_geq'],'end':flt['datetime_lt']},'pageviews':total.get('count',0),'visits':(total.get('sum') or {}).get('visits',0),'topPages':[{'path':x['dimensions']['requestPath'],'pageviews':x['count'],'visits':(x.get('sum') or {}).get('visits',0)} for x in account.get('topPages',[])],'daily':[{'date':x['dimensions']['date'],'pageviews':x['count'],'visits':(x.get('sum') or {}).get('visits',0)} for x in account.get('daily',[])]}

def main():
    p=argparse.ArgumentParser(description='Fetch DATLUME Cloudflare Web Analytics')
    p.add_argument('--days',type=int,default=7)
    p.add_argument('--json',action='store_true')
    a=p.parse_args(); data=fetch(a.days)
    if a.json:
        print(json.dumps(data,ensure_ascii=False,indent=2)); return
    print(f"DATLUME Web Analytics / last {a.days} days")
    print(f"PV: {data['pageviews']}  Visits: {data['visits']}")
    print('\nTop pages')
    for i,x in enumerate(data['topPages'],1): print(f"{i:>2}. {x['pageviews']:>6} PV  {x['visits']:>6} visits  {x['path']}")
    print('\nDaily')
    for x in data['daily']: print(f"{x['date']}  {x['pageviews']} PV  {x['visits']} visits")

if __name__=='__main__': main()
