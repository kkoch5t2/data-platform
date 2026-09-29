#!/usr/bin/env python3
import argparse, hashlib, html, http.cookiejar, json, math, re, sqlite3, threading, time, unicodedata, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
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

def result_opener():
    jar=http.cookiejar.CookieJar()
    op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    op.addheaders=list(UA.items())
    op.open(BASE+'?job=NyusatsuKeiyakuKekkaBuppinSearch',timeout=60).read()
    return op

def post_result_page(op,year,page=1):
    params={'job':'NyusatsuKeiyakuKekkaBuppinList','nendo':str(year),'selectNyusatsuDate':'1'}
    if page<=1:
        params.update({'messageFlg':'','nendoOld':'','textKeiyakuBango':'','textkenmei':'',
          'textNyusatsubiKaiYear':'','textNyusatsubiKaiMonth':'','textNyusatsubiKaiDay':'',
          'textNyusatsubiShuYear':'','textNyusatsubiShuMonth':'','textNyusatsubiShuDay':'','regist':'検索'})
    else: params['page']=str(page)
    body=urllib.parse.urlencode(params,encoding='shift_jis').encode('ascii')
    req=urllib.request.Request(BASE,data=body,headers={**UA,'Content-Type':'application/x-www-form-urlencoded'})
    last=None
    for attempt in range(4):
        try:
            with op.open(req,timeout=20) as r:return r.read().decode('cp932','ignore')
        except Exception as exc:
            last=exc
            if attempt<3: time.sleep(1.5*(attempt+1))
    raise last

def yokohama_date(value):
    s=unicodedata.normalize('NFKC',value or '')
    m=re.search(r'令和\s*(\d+)年\s*(\d+)月\s*(\d+)日',s)
    if not m:return ''
    y,mo,d=map(int,m.groups());return f'{2018+y:04d}-{mo:02d}-{d:02d}'

def result_rows(raw,year):
    out=[]
    for tr in re.findall(r'<tr[^>]*>([\s\S]*?)</tr>',raw,re.I):
        tds=re.findall(r'<td[^>]*>([\s\S]*?)</td>',tr,re.I)
        if len(tds)<9:continue
        m=re.search(r"detail\(['\"]?\d+['\"]?,['\"]?(\d+)['\"]?\)",tds[0],re.I)
        if not m:continue
        vals=[text_only(x) for x in tds[:9]];amount=re.sub(r'[^0-9]','',vals[3])
        award_date=yokohama_date(vals[4]);bid_date=yokohama_date(vals[5])
        out.append({'year':year,'contract':m.group(1),'title':vals[0],'kind':vals[1],
          'winner':vals[2] if vals[2].lower()!='null' else '', 'amount':int(amount) if amount else None,
          'award_date':award_date,'notice_date':bid_date or award_date,'bureau':vals[6],
          'contract_bureau':vals[7],'method':vals[8]})
    return out

def post_result_detail(op,year,contract,page):
    params={'job':'NyusatsuKeiyakuKekkaBuppinDetail','nendoDetail':str(year),'keiyakuBango':contract,'page':str(page)}
    body=urllib.parse.urlencode(params,encoding='shift_jis').encode('ascii')
    req=urllib.request.Request(BASE,data=body,headers={**UA,'Content-Type':'application/x-www-form-urlencoded'})
    last=None
    for attempt in range(4):
        try:
            with op.open(req,timeout=20) as r:return r.read().decode('cp932','ignore')
        except Exception as exc:
            last=exc
            if attempt<3:time.sleep(1.5*(attempt+1))
    raise last

def detail_contract_amount(raw,winner):
    target=norm(winner)
    if not target:return None
    for tr in re.findall(r'<tr[^>]*>([\s\S]*?)</tr>',raw,re.I):
        tds=re.findall(r'<td[^>]*>([\s\S]*?)</td>',tr,re.I)
        if len(tds)<2:continue
        vals=[text_only(x) for x in tds]
        if norm(vals[0])!=target:continue
        for value in vals[1:]:
            digits=re.sub(r'[^0-9]','',value)
            if digits:
                # Detail bid values are tax-exclusive; the result list contract amount is
                # tax-inclusive and truncates sub-yen fractions (verified against official rows).
                return int(digits)*110//100
    return None

def fill_missing_result_amounts(items,year,delay=.03):
    missing=[x for x in items if not x.get('amount') and x.get('winner')]
    if not missing:return 0
    op=result_opener();post_result_page(op,year,1);filled=0
    for x in missing:
        raw=post_result_detail(op,year,x['contract'],x.get('page') or 1)
        amount=detail_contract_amount(raw,x['winner'])
        if amount:
            x['amount']=amount;filled+=1
        if delay:time.sleep(delay)
    print(f'yokohama results {year}: detailAmountFilled={filled}/{len(missing)}',flush=True)
    return filled

def list_results(year,delay=.03,workers=4):
    op=result_opener();first=post_result_page(op,year,1)
    total_match=re.search(r'全\s*([0-9,]+)\s*件中',text_only(first));total=int(total_match.group(1).replace(',','')) if total_match else 0
    pages=max(1,math.ceil(total/50)) if total else 1
    first_cache=RAW/f'results-{year}-0001.html';first_cache.write_text(first,encoding='utf-8')
    def cache_ok(path):
        if not path.exists() or path.stat().st_size < 1000:
            return False
        try:
            sample=path.read_text(encoding='utf-8')
        except Exception:
            return False
        return 'NyusatsuKeiyakuKekkaBuppinList' in sample and '<html' in sample.lower()
    missing=[page for page in range(2,pages+1) if not cache_ok(RAW/f'results-{year}-{page:04d}.html')]
    tls=threading.local()
    def fetch_page(page):
        if not hasattr(tls,'op'):
            tls.op=result_opener()
            post_result_page(tls.op,year,1)
        raw=post_result_page(tls.op,year,page)
        if delay:time.sleep(delay)
        return page,raw
    if missing:
        with ThreadPoolExecutor(max_workers=max(1,min(workers,4))) as pool:
            for idx,(page,raw) in enumerate(pool.map(fetch_page,missing),1):
                (RAW/f'results-{year}-{page:04d}.html').write_text(raw,encoding='utf-8')
                if idx==1 or idx%10==0 or idx==len(missing):
                    print(f'yokohama results {year}: fetched={idx}/{len(missing)} page={page}/{pages}',flush=True)
    items=[];html_rows=0
    for page in range(1,pages+1):
        raw=(RAW/f'results-{year}-{page:04d}.html').read_text(encoding='utf-8')
        trs=re.findall(r'<tr[^>]*>([\s\S]*?)</tr>',raw,re.I)
        for tr in trs:
            tds=re.findall(r'<td[^>]*>([\s\S]*?)</td>',tr,re.I)
            if len(tds)<9:
                continue
            html_rows += 1
            if not re.search(r"detail\(['\"]?\d+['\"]?,['\"]?\d+['\"]?\)",tds[0],re.I):
                status=text_only(tds[2])
                if status!='不調':
                    raise RuntimeError(f'yokohama unexpected no-award status year={year} page={page}: {status}')
        page_items=result_rows(raw,year)
        for x in page_items:x['page']=page
        items.extend(page_items)
    fill_missing_result_amounts(items,year,delay)
    print(f'yokohama results {year}: page={pages}/{pages} rows={len(items)}',flush=True)
    if html_rows != total:
        raise RuntimeError(f'yokohama result row mismatch year={year} official={total} htmlRows={html_rows}')
    return items,total,pages,total-len(items)

def save_results(conn,items):
    now=datetime.now(timezone.utc).isoformat();updated=added=amounts=0
    org='横浜市';org_id=stable_id('org',org);conn.execute('INSERT OR IGNORE INTO organizations VALUES (?,?)',(org_id,org))
    existing_by_aid={aid:sid for aid,sid in conn.execute("SELECT aid,MIN(source_id) FROM procurements WHERE agency='横浜市' GROUP BY aid")}
    for x in items:
        winner=clean(x.get('winner') or '');company_id=stable_id('co',winner) if winner else None
        if company_id:conn.execute('INSERT OR IGNORE INTO companies VALUES (?,?,?)',(company_id,winner,norm(winner)))
        existing=existing_by_aid.get(x['contract'])
        if existing:
            conn.execute('''UPDATE procurements SET detail_fetched=1,award_date=?,contract_method=?,winner_name=?,company_id=?,award_amount=?,collected_at=? WHERE source_id=?''',
              (x['award_date'],x['method'],winner or None,company_id,x['amount'],now,existing));updated+=1
        else:
            is_it,tags,category,category_tags=classify(x['title']);sid=f"yokohama:{x['year']}:{x['contract']}"
            conn.execute('''INSERT INTO procurements
              (source_id,xid,aid,title,notice_date,agency,organization_id,notice_type,source_url,is_it,category,category_tags_json,tags_json,
               detail_fetched,award_date,contract_method,winner_name,company_id,award_amount,detail_text,collected_at)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET
               detail_fetched=excluded.detail_fetched,award_date=excluded.award_date,contract_method=excluded.contract_method,
               winner_name=excluded.winner_name,company_id=excluded.company_id,award_amount=excluded.award_amount,collected_at=excluded.collected_at''',(
              sid,int(x['year']),x['contract'],x['title'],x['notice_date'],org,org_id,'横浜市入札・契約結果',
              BASE+'?job=NyusatsuKeiyakuKekkaBuppinSearch',int(is_it),category,json.dumps(category_tags,ensure_ascii=False),json.dumps(tags,ensure_ascii=False),
              1,x['award_date'],x['method'],winner or None,company_id,x['amount'],clean(f"横浜市 / {x['kind']} / {x['bureau']} / {x['contract_bureau']}")[:1000],now));added+=1
            existing_by_aid[x['contract']]=sid
        if x.get('amount'):amounts+=1
    conn.commit();return added,updated,amounts

def main(years,delay=0.03,do_export=True,results_only=False):
    conn=sqlite3.connect(DB_PATH);init_db(conn)
    all_items=[];bulletins=0
    if not results_only:
        for year in years:
            bs=list_bulletins(year);bulletins+=len(bs);print(f'yokohama {year}: bulletins={len(bs)}')
            for b in bs:
                try: all_items.extend(bulletin_items(b))
                except Exception as e: print(f'WARNING bulletin {b["bulletin"]}: {e}')
                if delay:time.sleep(delay)
    added,skipped=save(conn,all_items)
    result_rows_count=result_added=result_updated=result_amounts=result_pages=result_no_award=0
    for year in years:
        rows,total,pages,no_award=list_results(year,delay);result_rows_count+=len(rows);result_pages+=pages;result_no_award+=no_award
        a,u,m=save_results(conn,rows);result_added+=a;result_updated+=u;result_amounts+=m
        print(f'yokohama results {year}: official={total} parsed={len(rows)} noAward={no_award} pages={pages} amounts={m}')
    if do_export: summary=export_json(conn)
    else: summary={'records':conn.execute('select count(*) from procurements').fetchone()[0]}
    conn.close();print(f'yokohama: bulletinsParsed={len(all_items)} resultsParsed={result_rows_count} resultAmounts={result_amounts} total={summary["records"]}')
    return {'records':len(all_items),'added':added,'duplicates':skipped,'bulletins':bulletins,'years':len(years),
      'resultRows':result_rows_count,'resultAdded':result_added,'resultUpdated':result_updated,'resultAmounts':result_amounts,'resultPages':result_pages,'resultNoAward':result_no_award}

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--years',default=str(datetime.now().year));ap.add_argument('--no-export',action='store_true');ap.add_argument('--results-only',action='store_true');ap.add_argument('--delay',type=float,default=.03);args=ap.parse_args()
    years=[]
    for part in args.years.split(','):
        if '-' in part:
            a,b=map(int,part.split('-',1));years.extend(range(a,b+1))
        else:years.append(int(part))
    with SourceRun('yokohama_procurement','横浜市 入札公告・契約結果') as run:run.set_metrics(**main(sorted(set(years)),args.delay,not args.no_export,args.results_only))
