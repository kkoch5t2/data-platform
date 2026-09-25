#!/usr/bin/env python3
import json
from datetime import datetime, timezone
from pathlib import Path

try:
    from core.source_run import SourceRun
    from collect_employment_economy import fetch, parse_wage_xlsx
except ModuleNotFoundError:
    from collector.core.source_run import SourceRun
    from collector.collect_employment_economy import fetch, parse_wage_xlsx

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'public/data/employment-wage-history.json'
RAW=ROOT/'data/raw/employment-wage-history';RAW.mkdir(parents=True,exist_ok=True)
# Same official 47-prefecture reference table for each year.
TABLES={
  2021:('000032183057',4),
  2022:('000040029286',4),
  2023:('000040163846',4),
  2024:('000040247959',4),
  2025:('000040421202',4),
}
SOURCE='https://www.e-stat.go.jp/stat-search/files?toukei=00450091&tstat=000001011429'
FIELDS=['monthlyCashSalaryThousandYen','monthlyScheduledSalaryThousandYen','annualBonusThousandYen','estimatedAnnualCashThousandYen','averageAge','averageTenureYears','scheduledHours','overtimeHours']

def main():
    per_year={}
    for year,(sid,kind) in TABLES.items():
        url=f'https://www.e-stat.go.jp/stat-search/file-download?statInfId={sid}&fileKind={kind}'
        raw=fetch(url);(RAW/f'wage-{year}-{sid}.xlsx').write_bytes(raw)
        data=parse_wage_xlsx(raw)
        if len(data)!=47:raise ValueError(f'{year}: expected 47 prefectures, got {len(data)}')
        per_year[year]=data
        print(f'wage history {year}: {len(data)} prefectures')
    prefs=list(per_year[max(per_year)].keys())
    records=[]
    for pref in prefs:
        values=[]
        for year in sorted(per_year):
            row=per_year[year][pref]
            values.append([year]+[row.get(k) for k in FIELDS])
        records.append({'prefecture':pref,'values':values})
    payload={
      'schemaVersion':1,'generatedAt':datetime.now(timezone.utc).isoformat(),
      'source':'厚生労働省 賃金構造基本統計調査 都道府県別参考表','sourceUrl':SOURCE,
      'years':sorted(TABLES),'fields':['year']+FIELDS,'records':records,
    }
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print(f'employment wage history: {len(records)} prefectures / {min(TABLES)}-{max(TABLES)}')
    return {'records':len(records)*len(TABLES),'prefectures':len(records),'startYear':min(TABLES),'endYear':max(TABLES)}

if __name__=='__main__':
    with SourceRun('employment_wage_history','厚生労働省 賃金構造基本統計 都道府県別時系列') as run:
        run.set_metrics(**main())
