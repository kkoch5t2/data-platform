#!/usr/bin/env python3
import glob, json, math, os, sys
from collections import Counter, defaultdict
from pathlib import Path
from datetime import date, timedelta

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'public'/'data'
SRC=ROOT/'src'/'data'
errors=[]
checks=0

def load(p):
    with open(p,encoding='utf-8') as f:return json.load(f)
def fail(msg): errors.append(msg)
def ok(cond,msg):
    global checks
    checks+=1
    if not cond: fail(msg)
def close(a,b,tol=1e-6):
    return a is not None and b is not None and abs(float(a)-float(b))<=tol
def unique47(rows,label):
    names=[r.get('prefecture') for r in rows]
    ok(len(rows)==47,f'{label}: expected 47 rows, got {len(rows)}')
    ok(len(set(names))==47 and None not in names,f'{label}: prefectures not unique/complete')
def finite_tree(x,path='root'):
    if isinstance(x,float) and (math.isnan(x) or math.isinf(x)): fail(f'{path}: non-finite number')
    elif isinstance(x,dict):
        for k,v in x.items(): finite_tree(v,f'{path}.{k}')
    elif isinstance(x,list):
        for i,v in enumerate(x): finite_tree(v,f'{path}[{i}]')

# Every published JSON must parse and contain no NaN/Infinity.
for p in DATA.glob('*.json'):
    try: finite_tree(load(p),p.name)
    except Exception as e: fail(f'{p.name}: JSON parse failed: {e}')

# Energy: official household-survey arithmetic and subset semantics.
d=load(DATA/'energy.json'); rows=d['records']; unique47(rows,'energy')
ok(d.get('householdYear')==2025,'energy: household year must be 2025')
for r in rows+[d['nationwide']]:
    name=r.get('prefecture','nationwide')
    vals=[r.get('annualElectricityYen'),r.get('annualGasYen'),r.get('annualOtherHeatYen')]
    if all(v is not None for v in vals):
        ok(close(r.get('annualEnergyYen'),sum(vals),1),f'energy {name}: energy total mismatch')
        ok(close(r.get('monthlyEnergyYen'),round(sum(vals)/12),1),f'energy {name}: monthly energy mismatch')
    if r.get('annualOtherHeatYen') is not None and r.get('annualKeroseneYen') is not None:
        ok(r['annualOtherHeatYen']>=r['annualKeroseneYen'],f'energy {name}: kerosene must be subset of other heat')
    if r.get('annualEnergyYen') is not None and r.get('annualWaterYen') is not None and r.get('annualUtilityWaterYen') is not None:
        ok(abs(r['annualUtilityWaterYen']-(r['annualEnergyYen']+r['annualWaterYen']))<=2,f'energy {name}: utility total mismatch')
    if r.get('annualCityGasYen') is not None and r.get('annualPropaneYen') is not None and r.get('annualGasYen') is not None:
        ok(abs(r['annualGasYen']-(r['annualCityGasYen']+r['annualPropaneYen']))<=2,f'energy {name}: gas breakdown mismatch')
    if r.get('monthlyConsumptionYen') and r.get('annualEnergyYen') is not None:
        calc=(r['annualEnergyYen']/12)/r['monthlyConsumptionYen']*100
        ok(abs(calc-r['energyBurdenRate'])<=.02,f'energy {name}: burden rate mismatch')
    if r.get('monthlyConsumptionYen') and r.get('monthlyUtilityWaterYen') is not None:
        calc=r['monthlyUtilityWaterYen']/r['monthlyConsumptionYen']*100
        ok(abs(calc-r['utilityBurdenRate'])<=.02,f'energy {name}: utility burden mismatch')

# Economy / prices.
d=load(DATA/'economy-prices.json'); rows=d['records']; unique47(rows,'economy-prices')
ok(d.get('year')==2025 and d.get('base')==100,'economy-prices: year/base mismatch')
for r in rows:
    for k,v in r.items():
        if k!='prefecture' and v is not None:
            ok(50<=float(v)<=160,f'economy-prices {r["prefecture"]} {k}: implausible {v}')

# Employment / wage formulas and shares.
d=load(DATA/'employment-economy-2026.json'); rows=d['records']; unique47(rows,'employment')
ok(d.get('wageYear')==2025,'employment: wage year mismatch')
for r in rows:
    name=r['prefecture']
    if r.get('monthlyCashSalaryThousandYen') is not None and r.get('annualBonusThousandYen') is not None:
        calc=r['monthlyCashSalaryThousandYen']*12+r['annualBonusThousandYen']
        ok(abs(calc-r['estimatedAnnualCashThousandYen'])<=.11,f'employment {name}: annual wage mismatch')
    if r.get('population'):
        ok(abs(r['workingAgePopulation']/r['population']*100-r['workingAgeShare'])<=.02,f'employment {name}: working-age share mismatch')
    for count,share in [('constructionEmployees','constructionEmployeeShare'),('infoEmployees','infoEmployeeShare'),('manufacturingEmployees','manufacturingEmployeeShare'),('retailEmployees','retailEmployeeShare'),('medicalEmployees','medicalEmployeeShare')]:
        if r.get('employees') and r.get(count) is not None:
            ok(abs(r[count]/r['employees']*100-r[share])<=.02,f'employment {name}: {share} mismatch')
    for a in r.get('ageWages',[]):
        if a.get('monthlyCashSalaryThousandYen') is not None and a.get('annualBonusThousandYen') is not None:
            calc=a['monthlyCashSalaryThousandYen']*12+a['annualBonusThousandYen']
            ok(abs(calc-a['estimatedAnnualCashThousandYen'])<=.11,f'employment {name} {a.get("ageBand")}: age annual wage mismatch')
    for t in r.get('jobTrend',[]):
        if t.get('jobSeekers'):
            ok(abs(t['jobOpenings']/t['jobSeekers']-t['jobOpeningRatio'])<=.0015,f'employment {name} {t["year"]}: job ratio mismatch')
    if r.get('jobTrend'):
        ok(close(r.get('jobOpeningRatio'),r['jobTrend'][-1].get('jobOpeningRatio'),.0001),f'employment {name}: latest job ratio mismatch')

# Business / industry.
d=load(DATA/'business-industry-2026.json'); rows=d['records']; unique47(rows,'business-industry')
for r in rows:
    name=r['prefecture']
    if r.get('establishments'):
        ok(abs(r['employees']/r['establishments']-r['employeesPerEstablishment'])<=.011,f'business {name}: employees/establishment mismatch')
    for x in r.get('industries',[]):
        if r.get('employees'):
            ok(abs(x['employees']/r['employees']*100-x['employeeShare'])<=.011,f'business {name} {x["key"]}: employee share mismatch')
        if r.get('establishments'):
            ok(abs(x['establishments']/r['establishments']*100-x['establishmentShare'])<=.011,f'business {name} {x["key"]}: establishment share mismatch')
        if x.get('establishments'):
            ok(abs(x['employees']/x['establishments']-x['employeesPerEstablishment'])<=.011,f'business {name} {x["key"]}: size mismatch')
    if r.get('industries'):
        mx=max(r['industries'],key=lambda x:x['employeeShare'])
        ok(r.get('largestIndustry')==mx['label'] and close(r.get('largestIndustryShare'),mx['employeeShare'],.001),f'business {name}: largest industry mismatch')
tot=d.get('totals',{})
if tot:
    ok(tot.get('establishments')==sum(r['establishments'] for r in rows),'business: establishment total mismatch')
    ok(tot.get('employees')==sum(r['employees'] for r in rows),'business: employee total mismatch')

# Regional trends.
d=load(DATA/'regional-trends-2026.json'); rows=d['records']
years=d.get('years',[])
ok(years==sorted(set(years)),'regional: years not sorted/unique')
for y in years:
    ok(sum(1 for r in rows if r['year']==y)==47,f'regional {y}: not 47 prefectures')
for r in rows:
    name=f'{r["prefecture"]} {r["year"]}'
    if r.get('population'):
        ok(abs(r['elderly']/r['population']*100-r['elderlyRate'])<=.011,f'regional {name}: elderly rate mismatch')
    ok(r['inMigration']-r['outMigration']==r['netMigration'],f'regional {name}: net migration mismatch')
    if r.get('jobSeekers'):
        ok(abs(r['jobOpenings']/r['jobSeekers']-r['jobOpeningRatio'])<=.0015,f'regional {name}: job ratio mismatch')
    if r.get('hotelNights'):
        ok(abs(r['foreignNights']/r['hotelNights']*100-r['foreignStayShare'])<=.011,f'regional {name}: foreign stay share mismatch')

# Real estate: basic source-shape/range integrity.
for fn,expected_min in [('land-prices-2026.json',25000),('land-survey-2026.json',20000)]:
    d=load(DATA/fn); rows=d['records']; ids=[r[0] for r in rows]
    ok(len(rows)>=expected_min,f'{fn}: unexpectedly few rows {len(rows)}')
    ok(len(ids)==len(set(ids)),f'{fn}: duplicate point IDs')
    for r in rows:
        ok(122<=float(r[1])<=154 and 20<=float(r[2])<=46,f'{fn}: coordinate out of Japan range {r[:3]}')
        ok(float(r[3])>0,f'{fn}: nonpositive price {r[0]}')
ok(load(DATA/'land-prices-2026.json').get('year')==2026,'land prices: year mismatch')
ok(load(DATA/'land-survey-2026.json').get('year')==2026,'land survey: year mismatch')

# Municipality layer.
d=load(DATA/'municipality-stats-2026.json'); rows=d['records']
ok(len(rows)>=1700,'municipality: unexpectedly few rows')
# tolerate schema variations while requiring unique primary-looking code if present
codes=[]
for r in rows:
    if isinstance(r,dict):
        c=r.get('code') or r.get('municipalityCode')
        if c: codes.append(c)
if codes: ok(len(codes)==len(set(codes)),'municipality: duplicate codes')

# History datasets: sorted years and expected coverage.
history_specs={
 'energy-consumption-history.json':(19,47),
 'employment-wage-history.json':(5,47),
 'regional-migration-history.json':(50,47),
}
for fn,(minyears,prefs) in history_specs.items():
    d=load(DATA/fn); ys=d.get('years',[])
    ok(len(ys)>=minyears and ys==sorted(set(ys)),f'{fn}: bad year coverage/order')
    rs=d.get('records',[])
    ok(len(rs)==prefs,f'{fn}: expected {prefs} prefectures, got {len(rs)}')
for fn,minyears in [('land-price-history.json',7),('economy-prices-history.json',4),('business-industry-history.json',2)]:
    d=load(DATA/fn); ys=d.get('years',[])
    ok(len(ys)>=minyears and ys==sorted(set(ys)),f'{fn}: bad year coverage/order')

# Procurement agency-quality gate.
import re
INVALID_AGENCY_EXACT = {'原子力安全庁','不明','未設定','未定','unknown','UNKNOWN'}
INVALID_AGENCY_RE = re.compile(r'(?:^府省コード\s*\S+|架空|テスト機関|ダミー|仮称)')
def valid_agency_name(name):
    if not isinstance(name,str) or not name.strip():
        return False
    s=name.strip()
    if s in INVALID_AGENCY_EXACT or INVALID_AGENCY_RE.search(s):
        return False
    if len(s)>120 or any(ord(ch)<32 for ch in s):
        return False
    return True

# Procurement: source shards, browser shards, summary and aggregate consistency.
summary=load(SRC/'summary.json'); meta=load(DATA/'dashboard-meta.json')
shards=sorted(SRC.glob('procurements-*.json'))
agency_idx={v:i for i,v in enumerate(meta['a'])}; category_idx={v:i for i,v in enumerate(meta['c'])}; winner_idx={v:i for i,v in enumerate(meta['w'])}
total=0; ids=set(); awards=0; award_total=0.0; companies=set(); orgs=set(); first=None; last=None
company_stats=defaultdict(lambda:[0,0.0]); org_stats=defaultdict(lambda:[0,0.0,0])
for p in shards:
    rs=load(p); year=int(p.stem.split('-')[-1]); total+=len(rs)
    dashboard=[]
    for dp in sorted(DATA.glob(f'dashboard-{year}*.json')):
        if dp.name!='dashboard-meta.json': dashboard.extend(load(dp))
    ok(len(dashboard)==len(rs),f'procurement {year}: dashboard/source count mismatch')
    expected=Counter(); actual=Counter()
    for row in dashboard:
        actual[(str(row[0]),row[1],row[2],row[3],row[4],row[9],float(row[10] or 0),row[11])]+=1
    for r in rs:
        rid=r.get('id'); ok(bool(rid),f'procurement {year}: missing id')
        if rid: ok(rid not in ids,f'procurement: duplicate id {rid}'); ids.add(rid)
        nd=r.get('noticeDate')
        if nd:
            ok(nd.startswith(str(year)),f'procurement {rid}: notice year mismatch {nd}')
            first=nd if first is None or nd<first else first; last=nd if last is None or nd>last else last
        ok(bool(r.get('title')) and bool(r.get('agency')) and bool(r.get('sourceUrl')),f'procurement {rid}: missing core fields')
        ok(valid_agency_name(r.get('agency')),f'procurement {rid}: invalid agency {r.get("agency")!r}')
        amount=float(r.get('awardAmount') or 0)
        if r.get('awardAmount') is not None: ok(amount>=0,f'procurement {rid}: negative award amount')
        if amount>0: awards+=1; award_total+=amount
        if r.get('companyId'):
            companies.add(r['companyId']); company_stats[r['companyId']][0]+=1; company_stats[r['companyId']][1]+=amount
        if r.get('organizationId'):
            org_stats[r['organizationId']][0]+=1; org_stats[r['organizationId']][1]+=amount; org_stats[r['organizationId']][2]+=int(bool(r.get('isIt')))
        if r.get('agency'): orgs.add(r['agency'])
        if rid.startswith('jetro-local:'): sid=rid.split(':',2)[-1]; kind=1
        elif rid.startswith('geps:'): sid=rid.split(':',2)[1]; kind=2
        elif rid.startswith('yokohama:'): sid=rid[9:]; kind=3
        elif rid.startswith('sapporo:'): sid=rid[8:]; kind=4
        else: sid=rid[6:] if rid.startswith('jetro:') else rid; kind=0
        expected[(sid,r.get('title') or '',(nd or '').replace('-',''),agency_idx[r.get('agency') or ''],category_idx[r.get('category') or 'その他'],winner_idx[r.get('winnerName') or ''],amount,kind)]+=1
    ok(expected==actual,f'procurement {year}: dashboard content mismatch')
ok(summary.get('records')==total,f'procurement summary records {summary.get("records")} != {total}')
ok(summary.get('firstDate')==first,f'procurement firstDate mismatch {summary.get("firstDate")} != {first}')
ok(summary.get('lastDate')==last,f'procurement lastDate mismatch {summary.get("lastDate")} != {last}')
ok(summary.get('awardRecords')==awards,f'procurement awardRecords mismatch {summary.get("awardRecords")} != {awards}')
ok(abs(float(summary.get('awardTotal') or 0)-award_total)<=.02,f'procurement awardTotal mismatch {summary.get("awardTotal")} != {award_total}')
ok(summary.get('companies')==len(companies),f'procurement companies mismatch {summary.get("companies")} != {len(companies)}')
ok(summary.get('organizations')==len(orgs),f'procurement organizations mismatch {summary.get("organizations")} != {len(orgs)}')
for x in load(SRC/'companies.json'):
    s=company_stats.get(x['id'],[0,0.0]); ok(x.get('awardCount')==s[0] and abs(float(x.get('awardTotal') or 0)-s[1])<=.02,f'company aggregate mismatch {x["id"]}')
org_master=load(SRC/'organizations.json')
for x in org_master:
    s=org_stats.get(x['id'],[0,0.0,0]); ok(x.get('recordCount')==s[0] and x.get('itCount')==s[2] and abs(float(x.get('awardTotal') or 0)-s[1])<=.02,f'organization aggregate mismatch {x["id"]}')
published_org_names={x.get('name') for x in org_master}
ok(all(valid_agency_name(n) for n in published_org_names),'procurement organizations: invalid/placeholder organization name')
ok(published_org_names==orgs,f'procurement organizations master mismatch: master={len(published_org_names)} referenced={len(orgs)}')
ok(last is not None and date.fromisoformat(last)>=date.today()-timedelta(days=1),f'procurement not fresh: lastDate={last}')

print(f'data audit: {checks} checks, {len(errors)} failures')
for e in errors[:100]: print('FAIL',e)
if len(errors)>100: print(f'... and {len(errors)-100} more')
sys.exit(1 if errors else 0)
