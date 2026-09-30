from __future__ import annotations
import json, sqlite3
from .common import RAW

GBIZ_STATEMENTS_DB=RAW/'gbiz-statements.sqlite'

def ratio(n,d):
    if n is None or d in (None,0): return None
    return round(n/d*100,2)

def load_statements_map(limit: int=5):
    if not GBIZ_STATEMENTS_DB.exists(): return {},{}
    conn=sqlite3.connect(GBIZ_STATEMENTS_DB); conn.row_factory=sqlite3.Row
    meta=dict(conn.execute('SELECT key,value FROM metadata')); grouped={}
    for row in conn.execute('SELECT * FROM statements ORDER BY corporate_number, COALESCE(balance_date,release_date,issue_date) DESC, release_date DESC'):
      cn=row['corporate_number']; periods=grouped.setdefault(cn,[])
      if len(periods)>=limit: continue
      p={'periodOrder':len(periods),'fiscalYear':row['balance_date'] or row['period_label'],'periodLabel':row['period_label'],'releaseDate':row['release_date'],'balanceDate':row['balance_date'],'plPeriod':row['pl_period'],'status':row['status'],'unit':'JPY' if row['unit_multiplier'] else row['unit_text'],'unitText':row['unit_text'],'reportTypes':json.loads(row['report_types_json'] or '[]')}
      for src,dst in [('current_assets','currentAssets'),('fixed_assets','fixedAssets'),('total_assets','totalAssets'),('current_liabilities','currentLiabilities'),('fixed_liabilities','fixedLiabilities'),('total_liabilities','totalLiabilities'),('shareholders_equity','shareholdersEquity'),('net_assets','netAssets'),('capital_stock','capitalStock'),('retained_earnings','retainedEarnings'),('primary_revenue','primaryRevenue'),('operating_income_loss','operatingIncomeLoss'),('ordinary_income_loss','ordinaryIncomeLoss'),('net_income_loss','netIncomeLoss')]:
        p[dst]=row[src]
      p['primaryRevenueLabel']=row['primary_revenue_label']; p['primaryRevenueUnit']='JPY' if row['primary_revenue'] is not None and row['unit_multiplier'] else None
      for f in ('totalAssets','netAssets','capitalStock','ordinaryIncomeLoss','netIncomeLoss'): p[f+'Unit']='JPY' if p.get(f) is not None and row['unit_multiplier'] else None
      periods.append(p)
    conn.close(); result={}
    for cn,periods in grouped.items():
      latest=periods[0] if periods else {}; prev=periods[1] if len(periods)>1 else None; growth=None
      if prev and latest.get('primaryRevenue') is not None and (prev.get('primaryRevenue') or 0)>0: growth=round((latest['primaryRevenue']/prev['primaryRevenue']-1)*100,2)
      analysis={'primaryRevenue':latest.get('primaryRevenue'),'primaryRevenueLabel':latest.get('primaryRevenueLabel'),'primaryRevenueUnit':latest.get('primaryRevenueUnit'),'ordinaryIncomeLoss':latest.get('ordinaryIncomeLoss'),'netIncomeLoss':latest.get('netIncomeLoss'),'netIncomeLossUnit':latest.get('netIncomeLossUnit'),'capitalStock':latest.get('capitalStock'),'netAssets':latest.get('netAssets'),'netAssetsUnit':latest.get('netAssetsUnit'),'totalAssets':latest.get('totalAssets'),'totalAssetsUnit':latest.get('totalAssetsUnit'),'employees':None,'revenueGrowthPct':growth,'netMarginPct':ratio(latest.get('netIncomeLoss'),latest.get('primaryRevenue')),'equityRatioPct':ratio(latest.get('netAssets'),latest.get('totalAssets')),'roaEndAssetsPct':ratio(latest.get('netIncomeLoss'),latest.get('totalAssets'))}
      result[cn]={'source':'gBizINFO 決算情報','sourceLabel':'gBizINFO 決算情報（官報決算公告）','datasetType':'statements','sourceDate':meta.get('sourceDate') or None,'sourceUrl':meta.get('sourceUrl') or None,'snapshotStatus':'current','periods':periods,'analysis':analysis}
    return result,meta
