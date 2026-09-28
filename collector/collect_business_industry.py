#!/usr/bin/env python3
import io, json, re, urllib.request, zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
try:
    from core.source_run import SourceRun
except ModuleNotFoundError:
    from collector.core.source_run import SourceRun

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'public/data/business-industry-2026.json'
RAW=ROOT/'data/raw/business-industry'; RAW.mkdir(parents=True,exist_ok=True)
STAT_ID='000040389329'
SOURCE_URL=f'https://www.e-stat.go.jp/stat-search/file-download?fileKind=0&statInfId={STAT_ID}'
SOURCE_PAGE='https://www.e-stat.go.jp/stat-search/files?bunya_l=07&cycle=0&layout=datalist&page=1&tclass1=000001223947&tclass2=000001223949&tclass3=000001223953&tclass4val=0&toukei=00200552&tstat=000001223942'
UA={'User-Agent':'Mozilla/5.0 DATLUME/1.0'}
TOTAL='AR_全産業（S_公務を除く）'
INDUSTRIES=[('construction','D_建設業'),('manufacturing','E_製造業'),('information','G_情報通信業'),('wholesaleRetail','I_卸売業、小売業'),('hospitality','M_宿泊業、飲食サービス業'),('lifestyle','N_生活関連サービス業、娯楽業'),('medicalWelfare','P_医療、福祉')]
NS='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'

def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=120) as r:return r.read()

def num(v):
    s=str(v or '').replace(',','').strip()
    if not s or s in {'-','…','X'}: return None
    x=float(s); return int(x) if x.is_integer() else x

def rows_from_xlsx(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        shared=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            root=ET.fromstring(z.read('xl/sharedStrings.xml'))
            shared=[''.join(n.text or '' for n in item.iter(NS+'t')) for item in root]
        sheet=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
    rows=[]
    for row in sheet.findall('.//'+NS+'sheetData/'+NS+'row'):
        d={}
        for c in row.findall(NS+'c'):
            m=re.match(r'[A-Z]+',c.get('r','')); v=c.find(NS+'v')
            if not m or v is None: continue
            x=v.text or ''
            if c.get('t')=='s' and x: x=shared[int(x)]
            d[m.group()]=x
        rows.append(d)
    return rows

def label(code_label): return code_label.split('_',1)[1]

def make_industry(key,code_label,row,total_est,total_emp):
    est=num(row.get('F')); emp=num(row.get('G'))
    if est is None or emp is None: raise ValueError(f'missing {code_label}: {row}')
    return {'key':key,'label':label(code_label),'establishments':est,'employees':emp,
            'employeeShare':round(emp/total_emp*100,2) if total_emp else None,
            'establishmentShare':round(est/total_est*100,2) if total_est else None,
            'employeesPerEstablishment':round(emp/est,2) if est else None}

def main():
    raw=fetch(SOURCE_URL)
    raw_path=RAW/f'economic-census-2024-table5-{STAT_ID}.xlsx'; raw_path.write_bytes(raw)
    rows=rows_from_xlsx(raw)
    title=rows[0].get('A','') if rows else ''
    table_title=rows[1].get('A','') if len(rows)>1 else ''
    if '令和６年経済センサス' not in title or '雇用者のいない個人経営の事業所を除く' not in table_title:
        raise ValueError('unexpected Economic Census workbook/table')
    base=[r for r in rows if r.get('C')=='0_総数' and r.get('D')=='0_総数' and r.get('E')=='00_総数']
    lookup={(r.get('A'),r.get('B')):r for r in base}
    areas=sorted({r['A'] for r in base if re.fullmatch(r'\d{2}_.+',r.get('A',''))})
    if len(areas)!=48 or areas[0]!='00_全国': raise ValueError(f'expected national + 47 prefectures, got {len(areas)}')
    def build(area):
        total=lookup.get((area,TOTAL))
        if not total: raise ValueError(f'missing total row: {area}')
        est=num(total.get('F')); emp=num(total.get('G'))
        if not est or not emp: raise ValueError(f'invalid total values: {area}')
        inds=[]
        for key,code_label in INDUSTRIES:
            row=lookup.get((area,code_label))
            if not row: raise ValueError(f'missing industry row: {area} {code_label}')
            inds.append(make_industry(key,code_label,row,est,emp))
        best=max(inds,key=lambda x:x['employeeShare'])
        code,name=area.split('_',1)
        return {'prefecture':name,'code':f'R{code}000','establishments':est,'employees':emp,
                'employeesPerEstablishment':round(emp/est,2),'industries':inds,
                'largestIndustry':best['label'],'largestIndustryShare':best['employeeShare']}
    national=build('00_全国')
    records=[build(a) for a in areas if a!='00_全国']
    if len(records)!=47: raise ValueError(f'expected 47 prefectures, got {len(records)}')
    if sum(r['establishments'] for r in records)!=national['establishments']: raise ValueError('prefecture establishment sum differs from national total')
    if sum(r['employees'] for r in records)!=national['employees']: raise ValueError('prefecture employee sum differs from national total')
    for n in national['industries']:
        pe=sum(next(x for x in r['industries'] if x['key']==n['key'])['establishments'] for r in records)
        pm=sum(next(x for x in r['industries'] if x['key']==n['key'])['employees'] for r in records)
        if pe!=n['establishments'] or pm!=n['employees']: raise ValueError(f'prefecture industry sum mismatch: {n["key"]}')
    totals={k:national[k] for k in ('establishments','employees','employeesPerEstablishment')}; totals['industries']=national['industries']
    payload={'schemaVersion':2,'generatedAt':datetime.now(timezone.utc).isoformat(),
      'source':'総務省統計局 令和6年経済センサス‐基礎調査 甲調査（確報）','sourceUrl':SOURCE_PAGE,'downloadUrl':SOURCE_URL,
      'statInfId':STAT_ID,'sourceTable':'第5表 産業（大分類）別の民営事業所数・従業者数（全国、都道府県）',
      'establishmentYear':2024,'employeeYear':2024,
      'surveyScopeNote':'甲調査の民営事業所。雇用者のいない個人経営の事業所を除く。公務を除く全産業を総数として使用。',
      'historicalComparisonNote':'2024年甲調査は調査対象範囲が2021年経済センサス‐活動調査と異なるため、2016年・2021年の履歴値との単純な増減比較には使用しない。',
      'industryCoverageNote':'産業別表示は2024年経済センサスの産業大分類から主要7産業を抜粋。比率の分母は同調査の全民営従業者・事業所。',
      'industries':[{'key':k,'label':label(v)} for k,v in INDUSTRIES],'totals':totals,'records':records}
    OUT.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print(f'business-industry 2024: {len(records)} prefectures / {totals["establishments"]:,} establishments / {totals["employees"]:,} employees')
    return {'records':len(records),'prefectures':len(records),'year':2024,'establishments':totals['establishments'],'employees':totals['employees']}

if __name__=='__main__':
    with SourceRun('business_industry','総務省統計局 令和6年経済センサス‐基礎調査（確報）') as run: run.set_metrics(**main())
