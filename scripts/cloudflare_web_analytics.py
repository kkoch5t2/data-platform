#!/usr/bin/env python3
import argparse, json, os, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

ACCOUNT='0889f537a65cecd76c67d146250b6a4b'
HOST='datlume.pages.dev'
TOKEN_FILE=Path.home()/'.datlume-cloudflare-token'
API='https://api.cloudflare.com/client/v4'

def token():
    value=os.environ.get('CLOUDFLARE_API_TOKEN','').strip()
    if value: return value
    if TOKEN_FILE.exists(): return TOKEN_FILE.read_text().strip()
    raise RuntimeError('CLOUDFLARE_API_TOKEN is not configured')

def api(method,path,body=None):
    data=None if body is None else json.dumps(body).encode()
    req=urllib.request.Request(API+path,data=data,method=method,headers={'Authorization':f'Bearer {token()}','Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=30) as r:return json.load(r)
    except urllib.error.HTTPError as e:
        payload=json.load(e)
        raise RuntimeError(payload.get('errors') or payload) from e

def site_tag():
    x=api('GET',f'/accounts/{ACCOUNT}/rum/site_info/list')
    site=next((s for s in (x.get('result') or []) if s.get('host')==HOST),None)
    if not site: raise RuntimeError('DATLUME Web Analytics site not found')
    return site['site_tag']

def graphql(query,variables):
    x=api('POST','/graphql',{'query':query,'variables':variables})
    if x.get('errors'): raise RuntimeError(x['errors'])
    return x['data']

def fetch(days):
    end=datetime.now(timezone.utc).replace(microsecond=0)
    start=end-timedelta(days=days)
    base={'datetime_geq':start.isoformat().replace('+00:00','Z'),'datetime_lt':end.isoformat().replace('+00:00','Z'),'siteTag':site_tag(),'requestHost':HOST}
    ref={**base,'refererHost_neq':''}
    q='''query($accountTag:String!,$filter:AccountRumPageloadEventsAdaptiveGroupsFilter_InputObject!,$refFilter:AccountRumPageloadEventsAdaptiveGroupsFilter_InputObject!){viewer{accounts(filter:{accountTag:$accountTag}){total:rumPageloadEventsAdaptiveGroups(limit:1,filter:$filter){count sum{visits}} topPages:rumPageloadEventsAdaptiveGroups(limit:30,filter:$filter,orderBy:[count_DESC]){count sum{visits} dimensions{requestPath}} topReferrers:rumPageloadEventsAdaptiveGroups(limit:20,filter:$refFilter,orderBy:[count_DESC]){count sum{visits} dimensions{refererHost}} daily:rumPageloadEventsAdaptiveGroups(limit:120,filter:$filter,orderBy:[date_ASC]){count sum{visits} dimensions{date}}}}}'''
    data=graphql(q,{'accountTag':ACCOUNT,'filter':base,'refFilter':ref})
    account=data['viewer']['accounts'][0]
    total=(account.get('total') or [{}])[0]
    return {
        'host':HOST,'generatedAt':end.isoformat().replace('+00:00','Z'),
        'range':{'days':days,'start':base['datetime_geq'],'end':base['datetime_lt']},
        'pageviews':total.get('count',0),'visits':(total.get('sum') or {}).get('visits',0),
        'topPages':[{'path':x['dimensions']['requestPath'],'pageviews':x['count'],'visits':(x.get('sum') or {}).get('visits',0)} for x in account.get('topPages',[])],
        'topReferrers':[{'host':x['dimensions']['refererHost'],'pageviews':x['count'],'visits':(x.get('sum') or {}).get('visits',0)} for x in account.get('topReferrers',[])],
        'daily':[{'date':x['dimensions']['date'],'pageviews':x['count'],'visits':(x.get('sum') or {}).get('visits',0)} for x in account.get('daily',[])]
    }

def save_report(report,path):
    path=Path(path)
    previous={}
    if path.exists():
        try: previous=json.loads(path.read_text())
        except Exception: previous={}
    history={x['date']:x for x in previous.get('history',[]) if x.get('date')}
    for row in report['daily']: history[row['date']]=row
    ordered=[history[k] for k in sorted(history)][-400:]
    public={k:v for k,v in report.items() if k!='daily'}
    public['daily']=report['daily']
    public['history']=ordered
    public['measurement']='Cloudflare Web Analytics (RUM)'
    public['privacy']='Aggregated page-load data only; no IP addresses or individual visitor identifiers are published.'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(public,ensure_ascii=False,indent=2)+'\n')
    return public

def print_report(data,days):
    print(f'DATLUME Web Analytics / last {days} days')
    print(f"PV: {data['pageviews']}  Visits: {data['visits']}")
    print('\nTop pages')
    for i,x in enumerate(data['topPages'],1): print(f"{i:>2}. {x['pageviews']:>6} PV  {x['visits']:>6} visits  {x['path']}")
    print('\nTop referrers')
    for i,x in enumerate(data['topReferrers'],1): print(f"{i:>2}. {x['pageviews']:>6} PV  {x['visits']:>6} visits  {x['host']}")

def main():
    p=argparse.ArgumentParser(description='Fetch DATLUME Cloudflare Web Analytics')
    p.add_argument('--days',type=int,default=7)
    p.add_argument('--json',action='store_true')
    p.add_argument('--save',metavar='PATH')
    a=p.parse_args()
    if not 1 <= a.days <= 7: p.error('--days must be between 1 and 7 for this RUM dataset')
    data=fetch(a.days)
    if a.save: data=save_report(data,a.save)
    if a.json: print(json.dumps(data,ensure_ascii=False,indent=2))
    else: print_report(data,a.days)

if __name__=='__main__': main()
