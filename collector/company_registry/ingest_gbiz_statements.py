from __future__ import annotations

import argparse, json, os, re, sqlite3, tempfile, unicodedata, zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from .common import RAW, ensure_dirs, valid_corporate_number

GBIZ_STATEMENTS_DB = RAW / 'gbiz-statements.sqlite'
CURRENT_DOWNLOAD_URL = 'https://info.gbiz.go.jp/hojin/DownloadTop'
UNIT_MULTIPLIERS = {'単位:円':1,'単位:千円':1000,'単位:万円':10000,'単位:百万円':1000000,'単位:億円':100000000}
REVENUE_SUBJECTS = [('売上高','売上高'),('営業収益','営業収益'),('完成工事高','完成工事高'),('収益','収益')]

def norm(v: str | None) -> str:
    return re.sub(r'[\s　]+', '', unicodedata.normalize('NFKC', v or ''))

def parse_amount(v: str | None) -> int | None:
    t = norm(v).replace(',', '')
    if t in ('', '-', '(-)'): return None
    sign = -1 if t[:1] in ('△','▲','-') else 1
    t = t.lstrip('△▲-')
    if not re.fullmatch(r'\d+(?:\.\d+)?', t): raise ValueError(f'unexpected amount {v!r}')
    return int(round(float(t) * sign))

def iso_date(v: str | None) -> str | None:
    m = re.search(r'(20\d{2})年(\d{1,2})月(\d{1,2})日', unicodedata.normalize('NFKC', v or ''))
    return f'{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}' if m else None

def source_date(path: Path) -> str | None:
    m = re.search(r'(20\d{6})', path.name)
    return f'{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}' if m else None

def metric(subjects: dict[str,int|None], names: tuple[str,...], negative_names: tuple[str,...]=()) -> int | None:
    for name in names:
        if name in subjects and subjects[name] is not None: return subjects[name]
    for name in negative_names:
        if name in subjects and subjects[name] is not None: return -abs(subjects[name])
    return None

def parse_xml(data: bytes, filename: str, multiplier: int | None) -> dict | None:
    root = ET.fromstring(data); ci = root.find('./CorporateInformation'); kp = root.find('./KanpouPostedInformation')
    if ci is None: return None
    cn = (ci.findtext('CorporateNumber') or '').strip()
    if not valid_corporate_number(cn): return None
    bs_all: dict[str,int|None] = {}; assets: dict[str,int|None] = {}; liabilities: dict[str,int|None] = {}; pl: dict[str,int|None] = {}
    balance_date=None; pl_period=None; reports=[]
    for rn in root.findall('.//ReportName'):
        rname=(rn.attrib.get('表名') or '').strip(); reports.append(rname)
        date_node=rn.find('./BsPlDate'); date_text=(date_node.attrib.get('日付') if date_node is not None else '') or ''
        is_bs='貸借対照表' in rname or '財政状態計算書' in rname
        is_pl='損益計算書' in rname
        if is_bs and balance_date is None: balance_date=iso_date(date_text)
        if is_pl and not pl_period: pl_period=date_text.strip()
        if not (is_bs or is_pl): continue
        for row in rn.findall('.//Meisai'):
            subject=norm(row.findtext('Subject')); raw=parse_amount(row.findtext('Amount'))
            value=raw*multiplier if raw is not None and multiplier is not None else None
            target=pl if is_pl else bs_all
            if subject and (subject not in target or target[subject] is None): target[subject]=value
        if is_bs:
            for div in rn.findall('.//Division'):
                d=norm(div.attrib.get('部'))
                target=assets if '資産の部' in d and '負債' not in d else liabilities if ('負債' in d or '純資産' in d) else None
                if target is None: continue
                for row in div.findall('./Meisai'):
                    subject=norm(row.findtext('Subject')); raw=parse_amount(row.findtext('Amount'))
                    value=raw*multiplier if raw is not None and multiplier is not None else None
                    if subject and (subject not in target or target[subject] is None): target[subject]=value
    current_assets=metric(bs_all,('流動資産',)); fixed_assets=metric(bs_all,('固定資産',))
    total_assets=metric(bs_all,('資産合計',))
    if total_assets is None: total_assets=metric(assets,('合計',))
    if total_assets is None and current_assets is not None and fixed_assets is not None: total_assets=current_assets+fixed_assets
    primary_revenue=primary_label=None
    for subject,label in REVENUE_SUBJECTS:
        if pl.get(subject) is not None: primary_revenue,primary_label=pl[subject],label; break
    net_income=metric(pl,('当期純利益','税引後当期純利益'),('当期純損失','税引後当期純損失'))
    if net_income is None:
        income_names=('うち当期純利益','内当期純利益','うち、当期純利益','当期純利益')
        loss_names=('うち当期純損失','内当期純損失','うち、当期純損失','当期純損失')
        net_income=metric(bs_all,income_names,loss_names)
    return {
      'corporateNumber':cn,'name':(ci.findtext('CompanyName') or '').strip(),'periodLabel':(ci.findtext('Period') or '').strip(),
      'releaseDate':iso_date(ci.findtext('Release')),'balanceDate':balance_date,'plPeriod':pl_period,
      'status':(kp.findtext('Status') or '').strip() if kp is not None else None,'issueDate':iso_date(kp.findtext('IssueDate')) if kp is not None else None,
      'kanpouClassification':(kp.findtext('Classification') or '').strip() if kp is not None else None,
      'kanpouNumber':(kp.findtext('Number') or '').strip() if kp is not None else None,'kanpouPage':(kp.findtext('Page') or '').strip() if kp is not None else None,
      'reportTypes':reports,'currentAssets':current_assets,'fixedAssets':fixed_assets,'totalAssets':total_assets,
      'currentLiabilities':metric(bs_all,('流動負債',)),'fixedLiabilities':metric(bs_all,('固定負債',)),'totalLiabilities':metric(bs_all,('負債合計',)),
      'shareholdersEquity':metric(bs_all,('株主資本',)),'netAssets':metric(bs_all,('純資産合計',)),'capitalStock':metric(bs_all,('資本金',)),
      'retainedEarnings':metric(bs_all,('利益剰余金',)),'primaryRevenue':primary_revenue,'primaryRevenueLabel':primary_label,
      'operatingIncomeLoss':metric(pl,('営業利益',),('営業損失',)),'ordinaryIncomeLoss':metric(pl,('経常利益','当期経常利益'),('経常損失','当期経常損失')),
      'netIncomeLoss':net_income,'sourceFile':filename,
    }

def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript('''
    PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
    CREATE TABLE statements (
      source_file TEXT PRIMARY KEY, corporate_number TEXT NOT NULL, name TEXT, period_label TEXT,
      release_date TEXT, balance_date TEXT, pl_period TEXT, status TEXT, issue_date TEXT,
      kanpou_classification TEXT, kanpou_number TEXT, kanpou_page TEXT, unit_text TEXT, unit_multiplier INTEGER,
      report_types_json TEXT NOT NULL, current_assets INTEGER, fixed_assets INTEGER, total_assets INTEGER,
      current_liabilities INTEGER, fixed_liabilities INTEGER, total_liabilities INTEGER,
      shareholders_equity INTEGER, net_assets INTEGER, capital_stock INTEGER, retained_earnings INTEGER,
      primary_revenue INTEGER, primary_revenue_label TEXT, operating_income_loss INTEGER,
      ordinary_income_loss INTEGER, net_income_loss INTEGER
    );
    CREATE INDEX idx_statements_corporate ON statements(corporate_number);
    CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    ''')

def default_input() -> Path:
    files=sorted((RAW/'gbiz').glob('Kessanjoho_*.zip'), key=lambda p:p.stat().st_mtime, reverse=True)
    if not files: raise SystemExit('No gBizINFO statements ZIP found. Run collect_gbiz_bulk --type statements first.')
    return files[0]

def build_database(path: Path) -> dict:
    ensure_dirs(); fd,tmp=tempfile.mkstemp(prefix='gbiz-statements-',suffix='.sqlite',dir=RAW); os.close(fd); temp=Path(tmp)
    try:
      conn=sqlite3.connect(temp); create_schema(conn); rows=0; companies=set(); unsupported=0
      with zipfile.ZipFile(path) as archive:
        names=[n for n in archive.namelist() if n.lower().endswith('.xml')]
        for name in names:
          root=ET.fromstring(archive.read(name)); unit=(root.findtext('./CorporateInformation/Unit') or '').strip(); multiplier=UNIT_MULTIPLIERS.get(norm(unit))
          if multiplier is None: unsupported += 1
          rec=parse_xml(ET.tostring(root,encoding='utf-8'),name,multiplier)
          if not rec or rec['status']=='Delete': continue
          conn.execute('''INSERT INTO statements VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(
            rec['sourceFile'],rec['corporateNumber'],rec['name'],rec['periodLabel'],rec['releaseDate'],rec['balanceDate'],rec['plPeriod'],rec['status'],rec['issueDate'],rec['kanpouClassification'],rec['kanpouNumber'],rec['kanpouPage'],unit,multiplier,
            json.dumps(rec['reportTypes'],ensure_ascii=False),rec['currentAssets'],rec['fixedAssets'],rec['totalAssets'],rec['currentLiabilities'],rec['fixedLiabilities'],rec['totalLiabilities'],rec['shareholdersEquity'],rec['netAssets'],rec['capitalStock'],rec['retainedEarnings'],rec['primaryRevenue'],rec['primaryRevenueLabel'],rec['operatingIncomeLoss'],rec['ordinaryIncomeLoss'],rec['netIncomeLoss']))
          rows+=1; companies.add(rec['corporateNumber'])
      meta={'dataset':'gBizINFO statements','sourceFile':path.name,'sourceDate':source_date(path) or '','sourceUrl':CURRENT_DOWNLOAD_URL,'generatedAt':datetime.now(timezone.utc).isoformat(),'rows':str(rows),'companies':str(len(companies)),'unsupportedUnitFiles':str(unsupported)}
      conn.executemany('INSERT INTO metadata(key,value) VALUES (?,?)',meta.items()); conn.commit(); conn.close(); temp.replace(GBIZ_STATEMENTS_DB)
      return {'rows':rows,'companies':len(companies),'sourceDate':meta['sourceDate'],'unsupportedUnitFiles':unsupported,'db':str(GBIZ_STATEMENTS_DB)}
    except Exception:
      temp.unlink(missing_ok=True); raise

def main(input_path: str|None=None) -> dict:
    path=Path(input_path).expanduser().resolve() if input_path else default_input().resolve()
    result=build_database(path); print(f'gbiz statements ingest {result}',flush=True); return result

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--input'); a=p.parse_args(); main(a.input)
