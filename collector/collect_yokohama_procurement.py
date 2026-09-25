#!/usr/bin/env python3
import argparse, hashlib, html, json, re, sqlite3, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path
try:
    from core.source_run import SourceRun
    from collect_jetro import DB_PATH, init_db, classify, export_json, stable_id, norm, clean
except ModuleNotFoundError:
    from collector.core.source_run import SourceRun
    from collector.collect_jetro import DB_PATH, init_db, classify, export_json, stable_id, norm, clean

ROOT=Path(__file__).resolve().parents[1]
RAW=ROOT/'data/raw/yokohama-procurement';RAW.mkdir(parents=True,exist_ok=True)
BASE='https://keiyaku.city.yokohama.lg.jp/epco/servlet/p'
UA={'User-Agent':'Mozilla/5.0 DATLUME/1.0'}

def fetch(url):
    req=urllib.request.Request(url,headers=UA)
    with urllib.request.urlopen(req,timeout=60) as r:return r.read().decode('shift_jis','ignore')

def text_only(s):
    s=re.sub(r'<br\s*/?>',' ',s,flags=re.I);s=re.sub(r'<[^>]+>',' ',s)
    return clean(html.unescape(s))

def list_bulletins(year):
    url=BASE+'?'+urllib.parse.urlencode({'job':'KokokuList','nendo':str(year)})
    raw=fetch(url);(RAW/f'bulletins-{year}.html').write_text(raw,encoding='utf-8')
    out=[]
    for tr in re.findall(r'<tr[^>]*>([\s\S]*?)</tr>',raw,re.I):
        tds=re.findall(r'<td[^>]*>([\s\S]*?)</td>',tr,re.I)
        if len(tds)<3:continue
        href=re.search(r'KokokuAnkenList&kokoku_no=(\d+)',tds[0],re.I)
        date=text_only(tds[1]).replace('/','-')
        remark=text_only(tds[2])
        if href and re.fullmatch(r'20\d{2}-\d{2}-\d{2}',date):
            out.append({'bulletin':href.group(1),'date':date,'remark':remark})
    # duplicated anchors/rows are possible in old HTML
    uniq={x['bulletin']:x for x in out}
    return sorted(uniq.values(),key=lambda x:x['date'])

def bulletin_items(b):
    no=b['bulletin'];url=BASE+'?'+urllib.parse.urlencode({'job':'KokokuAnkenList','kokoku_no':no})
    raw=fetch(url);(RAW/f'bulletin-{no}.html').write_text(raw,encoding='utf-8')
    out=[]
    for tr in re.findall(r'<tr[^>]*>([\s\S]*?)</tr>',raw,re.I):
        tds=re.findall(r'<td[^>]*>([\s\S]*?)</td>',tr,re.I)
        if len(tds)<2:continue
        contract=text_only(tds[0]); title=text_only(tds[1])
        if not re.fullmatch(r'\d{8,12}',contract) or not title:continue
        method=text_only(tds[3]) if len(tds)>3 else ''
        bureau=text_only(tds[5]) if len(tds)>5 else ''
        out.append({'contract':contract,'title':title,'method':method,'bureau':bureau,'date':b['date'],'bulletin':no,'url':url})
    return out

def save(conn,items):
    existing={(d,norm(t)) for d,t in conn.execute("SELECT notice_date,title FROM procurements WHERE agency='横浜市'")}
    now=datetime.now(timezone.utc).isoformat();added=0;skipped=0
    org='横浜市';org_id=stable_id('org',org);conn.execute('INSERT OR IGNORE INTO organizations VALUES (?,?)',(org_id,org))
    for x in items:
        key=(x['date'],norm(x['title']))
        if key in existing:
            skipped+=1;continue
        is_it,tags,category,category_tags=classify(x['title'])
        sid=f"yokohama:{x['bulletin']}:{x['contract']}"
        xid=int(x['bulletin']);aid=x['contract']
        conn.execute('''INSERT INTO procurements
          (source_id,xid,aid,title,notice_date,agency,organization_id,notice_type,source_url,is_it,category,category_tags_json,tags_json,
           detail_fetched,contract_method,detail_text,collected_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(source_id) DO UPDATE SET title=excluded.title,notice_date=excluded.notice_date,agency=excluded.agency,
          organization_id=excluded.organization_id,notice_type=excluded.notice_type,source_url=excluded.source_url,is_it=excluded.is_it,
          category=excluded.category,category_tags_json=excluded.category_tags_json,tags_json=excluded.tags_json,
          contract_method=excluded.contract_method,detail_text=excluded.detail_text,collected_at=excluded.collected_at''',(
            sid,xid,aid,x['title'],x['date'],org,org_id,'横浜市報調達公告',x['url'],int(is_it),category,
            json.dumps(category_tags,ensure_ascii=False),json.dumps(tags,ensure_ascii=False),0,x['method'],
            clean(f"横浜市 / {x['bureau']} / {x['method']}")[:1000],now))
        existing.add(key);added+=1
    conn.commit();return added,skipped

def main(years,delay=0.03,do_export=True):
    conn=sqlite3.connect(DB_PATH);init_db(conn)
    all_items=[];bulletins=0
    for year in years:
        bs=list_bulletins(year);bulletins+=len(bs);print(f'yokohama {year}: bulletins={len(bs)}')
        for i,b in enumerate(bs,1):
            try: all_items.extend(bulletin_items(b))
            except Exception as e: print(f'WARNING bulletin {b["bulletin"]}: {e}')
            if delay:time.sleep(delay)
    added,skipped=save(conn,all_items)
    if do_export: summary=export_json(conn)
    else: summary={'records':conn.execute('select count(*) from procurements').fetchone()[0]}
    conn.close();print(f'yokohama: parsed={len(all_items)} added={added} duplicateSkipped={skipped} total={summary["records"]}')
    return {'records':len(all_items),'added':added,'duplicates':skipped,'bulletins':bulletins,'years':len(years)}

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--years',default=str(datetime.now().year));ap.add_argument('--no-export',action='store_true');ap.add_argument('--delay',type=float,default=.03);args=ap.parse_args()
    years=[]
    for part in args.years.split(','):
        if '-' in part:
            a,b=map(int,part.split('-',1));years.extend(range(a,b+1))
        else:years.append(int(part))
    with SourceRun('yokohama_procurement','横浜市 横浜市報調達公告版') as run:run.set_metrics(**main(sorted(set(years)),args.delay,not args.no_export))
