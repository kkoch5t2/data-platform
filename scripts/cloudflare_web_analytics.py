#!/usr/bin/env python3
import argparse, json, os, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

ACCOUNT='0889f537a65cecd76c67d146250b6a4b'
SITE_HOST='datlume.com'
HOST='datlume.com'
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
    site=next((s for s in (x.get('result') or []) if SITE_HOST in str(s.get('host') or '')),None)
    if not site: raise RuntimeError('DATLUME Web Analytics site not found')
    return site['site_tag']

def graphql(query,variables):
    x=api('POST','/graphql',{'query':query,'variables':variables})
    if x.get('errors'): raise RuntimeError(x['errors'])
    return x['data']

def fetch_daily(start,end,site):
    # A seven-day date grouping can be adaptively sampled even when a total is not.
    # Query each UTC date separately and cover the same rolling [start, end) interval.
    q='''query($accountTag:String!,$filter:AccountRumPageloadEventsAdaptiveGroupsFilter_InputObject!){viewer{accounts(filter:{accountTag:$accountTag}){daily:rumPageloadEventsAdaptiveGroups(limit:2,filter:$filter,orderBy:[date_ASC]){count sum{visits} dimensions{date}}}}}'''
    rows=[]
    current=start
    while current<end:
        next_midnight=(current+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)
        stop=min(end,next_midnight)
        filt={'datetime_geq':current.isoformat().replace('+00:00','Z'),
              'datetime_lt':stop.isoformat().replace('+00:00','Z'),
              'siteTag':site,'requestHost':HOST}
        account=graphql(q,{'accountTag':ACCOUNT,'filter':filt})['viewer']['accounts'][0]
        batch=account.get('daily') or []
        if len(batch)>1 or any(x['dimensions']['date']!=current.date().isoformat() for x in batch):
            raise RuntimeError(f'Unexpected Web Analytics date groups for {current.date()}')
        for x in batch:
            pv=x['count']; visits=x['sum']['visits']
            if not isinstance(pv,int) or not isinstance(visits,int) or pv<0 or visits<0:
                raise RuntimeError(f'Invalid Web Analytics counts for {current.date()}')
            rows.append({'date':x['dimensions']['date'],'pageviews':pv,'visits':visits})
        current=stop
    return rows

def fetch(days):
    end=datetime.now(timezone.utc).replace(microsecond=0)
    start=end-timedelta(days=days)
    site=site_tag()
    base={'datetime_geq':start.isoformat().replace('+00:00','Z'),'datetime_lt':end.isoformat().replace('+00:00','Z'),'siteTag':site,'requestHost':HOST}
    ref={**base,'refererHost_neq':''}
    q='''query($accountTag:String!,$filter:AccountRumPageloadEventsAdaptiveGroupsFilter_InputObject!,$refFilter:AccountRumPageloadEventsAdaptiveGroupsFilter_InputObject!){viewer{accounts(filter:{accountTag:$accountTag}){topPages:rumPageloadEventsAdaptiveGroups(limit:30,filter:$filter,orderBy:[count_DESC]){count sum{visits} dimensions{requestPath}} topReferrers:rumPageloadEventsAdaptiveGroups(limit:20,filter:$refFilter,orderBy:[count_DESC]){count sum{visits} dimensions{refererHost}}}}}'''
    data=graphql(q,{'accountTag':ACCOUNT,'filter':base,'refFilter':ref})
    account=data['viewer']['accounts'][0]
    daily=fetch_daily(start,end,site)
    return {
        'host':HOST,'generatedAt':end.isoformat().replace('+00:00','Z'),
        'range':{'days':days,'start':base['datetime_geq'],'end':base['datetime_lt']},
        'pageviews':sum(x['pageviews'] for x in daily),'visits':sum(x['visits'] for x in daily),
        'topPages':[{'path':x['dimensions']['requestPath'],'pageviews':x['count'],'visits':(x.get('sum') or {}).get('visits',0)} for x in account.get('topPages',[])],
        'topReferrers':[{'host':x['dimensions']['refererHost'],'pageviews':x['count'],'visits':(x.get('sum') or {}).get('visits',0)} for x in account.get('topReferrers',[])],
        'daily':daily
    }

def save_report(report,path):
    path=Path(path)
    previous={}
    if path.exists():
        try: previous=json.loads(path.read_text())
        except Exception: previous={}
    history={x['date']:x for x in previous.get('history',[]) if x.get('date')}
    # The first UTC date in a rolling window is partial; retain its earlier full-day history.
    start=datetime.fromisoformat(report['range']['start'].replace('Z','+00:00'))
    partial_start=start.date().isoformat() if start.time()!=datetime.min.time() else None
    for row in report['daily']:
        if row['date']!=partial_start: history[row['date']]=row
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
