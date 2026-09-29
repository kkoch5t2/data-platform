#!/usr/bin/env python3
import csv, io, json, math, urllib.request, zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'public' / 'data'
UA = {'User-Agent':'Mozilla/5.0 PublicMarketData/1.0'}
SSDSE_A = 'https://www.nstac.go.jp/files/SSDSE-A-2026.csv'
SSDSE_E = 'https://www.nstac.go.jp/files/SSDSE-E-2026.csv'
CRIME = 'https://www.npa.go.jp/publications/whitepaper/r08/toukei/02/1.csv'
ACCIDENT = 'https://www.npa.go.jp/publications/statistics/koutsuu/opendata/2024/honhyo_2024.csv'
SCHOOL = 'https://nlftp.mlit.go.jp/ksj/gml/data/P29/P29-23/P29-23_GML.zip'
HOSPITAL = 'https://nlftp.mlit.go.jp/ksj/gml/data/P04/P04-20/P04-20_GML.zip'
STATION = 'https://nlftp.mlit.go.jp/ksj/gml/data/N02/N02-25/N02-25_GML.zip'
ADMIN_AREA = 'https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03-2025/N03-20250101_{pref}_GML.zip'

def fetch(url, timeout=120):
    req=urllib.request.Request(url,headers=UA)
    with urllib.request.urlopen(req,timeout=timeout) as r: return r.read()

def write(name,obj):
    OUT.mkdir(parents=True,exist_ok=True)
    p=OUT/name; p.write_text(json.dumps(obj,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print(name, p.stat().st_size)

def read_csv_url(url):
    raw=fetch(url)
    for enc in ('utf-8-sig','cp932','shift_jis'):
        try: return list(csv.reader(io.StringIO(raw.decode(enc))))
        except UnicodeDecodeError: pass
    raise ValueError('unsupported encoding: '+url)

def to_int(v):
    try: return int(str(v).replace(',','').strip())
    except: return 0

def build_municipal_stats():
    rows=read_csv_url(SSDSE_A)
    codes, names = rows[0], rows[2]
    by_code={code:i for i,code in enumerate(codes)}
    by_name={name:i for i,name in enumerate(names)}
    required_codes=['A1101','A1303','A1700','A4101','A4200','A5101','A5102','A7101','A810105','A8201','A8301']
    miss=[x for x in required_codes if x not in by_code]
    miss += [x for x in ['一般病院数','一般診療所数','歯科診療所数'] if x not in by_name]
    if miss: raise ValueError('SSDSE columns missing: '+','.join(miss))
    stats=[]
    for r in rows[3:]:
        if len(r)<3 or not r[0].startswith('R'): continue
        pop=to_int(r[by_code['A1101']]); old=to_int(r[by_code['A1303']])
        foreign=to_int(r[by_code['A1700']]); households=to_int(r[by_code['A7101']])
        single=to_int(r[by_code['A810105']]); elderly_single=to_int(r[by_code['A8301']])
        moved_in=to_int(r[by_code['A5101']]); moved_out=to_int(r[by_code['A5102']])
        births=to_int(r[by_code['A4101']]); deaths=to_int(r[by_code['A4200']])
        stats.append({'code':r[0][1:6],'prefecture':r[1],'municipality':r[2],
          'population':pop,'elderlyRate':round(old/pop*100,1) if pop else None,
          'foreignPopulation':foreign,'foreignRate':round(foreign/pop*100,2) if pop else None,
          'households':households,'singleHouseholds':single,
          'singleHouseholdRate':round(single/households*100,1) if households else None,
          'elderlyCoupleHouseholds':to_int(r[by_code['A8201']]),'elderlySingleHouseholds':elderly_single,
          'inMigrants':moved_in,'outMigrants':moved_out,'netMigration':moved_in-moved_out,
          'births':births,'deaths':deaths,'naturalChange':births-deaths,
          'hospitalCount':to_int(r[by_name['一般病院数']]),'clinicCount':to_int(r[by_name['一般診療所数']]),
          'dentalCount':to_int(r[by_name['歯科診療所数']])})
    return stats

def polygon_centroid(ring):
    if not ring or len(ring) < 3: return None
    area2=cx=cy=0.0
    for a,b in zip(ring,ring[1:]+ring[:1]):
        cross=a[0]*b[1]-b[0]*a[1]
        area2+=cross; cx+=(a[0]+b[0])*cross; cy+=(a[1]+b[1])*cross
    if abs(area2)<1e-12:
        return (sum(x for x,_ in ring)/len(ring),sum(y for _,y in ring)/len(ring),1.0)
    return (cx/(3*area2),cy/(3*area2),abs(area2)/2)

def geometry_centroid(geometry):
    if not geometry: return None
    coords=geometry.get('coordinates') or []
    polys=[coords] if geometry.get('type')=='Polygon' else coords if geometry.get('type')=='MultiPolygon' else []
    parts=[]
    for poly in polys:
        if poly:
            c=polygon_centroid(poly[0])
            if c: parts.append(c)
    if not parts: return None
    w=sum(x[2] for x in parts)
    return (sum(x[0]*x[2] for x in parts)/w,sum(x[1]*x[2] for x in parts)/w,w)

def attach_centroids(stats):
    land=[]
    for name in ('land-prices-2026.json','land-survey-2026.json'):
        path=OUT/name
        if path.exists():
            land.extend(json.loads(path.read_text(encoding='utf-8'))['records'])
    if not land: return stats
    by_pref=defaultdict(list)
    for s in stats: by_pref[s['prefecture']].append(s['municipality'])
    for p in by_pref: by_pref[p].sort(key=len,reverse=True)
    pts=defaultdict(list)
    for r in land:
        lon,lat,address,pref=r[1],r[2],r[6],r[7]
        rest=address.replace(pref,'',1).strip()
        starts=[rest]
        if '郡' in rest:
            starts.append(rest.split('郡',1)[1])
        muni=next((m for m in by_pref.get(pref,[]) if any(x.startswith(m) for x in starts)),None)
        if muni: pts[(pref,muni)].append((lon,lat))
    for s in stats:
        p=pts.get((s['prefecture'],s['municipality']))
        if p:
            s['lon']=round(sum(x for x,_ in p)/len(p),5)
            s['lat']=round(sum(y for _,y in p)/len(p),5)
    try:
        schools=geojson_from_zip(SCHOOL,'P29-23.geojson'); by_code=defaultdict(list)
        for f in schools.get('features',[]):
            p=f.get('properties') or {}; c=f.get('geometry',{}).get('coordinates')
            if c and p.get('P29_001'): by_code[str(p['P29_001'])].append(c)
        for s in stats:
            if 'lon' in s: continue
            p=by_code.get(s['code'],[])
            if p:
                s['lon']=round(sum(x[0] for x in p)/len(p),5); s['lat']=round(sum(x[1] for x in p)/len(p),5)
    except Exception as e: print('school centroid warning',e)
    # Final fallback: official MLIT administrative boundaries. Some small villages
    # have neither land-price observations nor school points in the source layers.
    missing=[s for s in stats if 'lon' not in s]
    for pref in sorted({s['code'][:2] for s in missing}):
        try:
            obj=geojson_from_zip(ADMIN_AREA.format(pref=pref),f'_{pref}.geojson')
            centers=defaultdict(list)
            for f in obj.get('features',[]):
                props=f.get('properties') or {}; code=str(props.get('N03_007') or '')
                c=geometry_centroid(f.get('geometry'))
                if code and c: centers[code].append(c)
            for row in missing:
                if row['code'][:2]!=pref or not centers.get(row['code']): continue
                pts=centers[row['code']]; weight=sum(x[2] for x in pts)
                row['lon']=round(sum(x[0]*x[2] for x in pts)/weight,5)
                row['lat']=round(sum(x[1]*x[2] for x in pts)/weight,5)
        except Exception as e: print('admin centroid warning',pref,e)
    return stats

def build_pref_population():
    rows=read_csv_url(SSDSE_E); idx={n:i for i,n in enumerate(rows[2])}
    out={}
    for r in rows[3:]:
        if len(r)>2 and r[1] and r[1] != '全国':
            out[r[1]]=to_int(r[idx['総人口']])
    return out

def build_crime(stats):
    pop=build_pref_population(); rows=read_csv_url(CRIME)
    counts={}
    def resolve(token):
        token=(token or '').strip()
        if token in pop: return token
        return next((p for p in pop if p.startswith(token) and token),None)
    for r in rows[5:]:
        if len(r)<4: continue
        a=(r[0] or '').strip(); b=(r[1] or '').strip(); pref=None
        if a in pop: pref=a
        elif a == '東京': pref='東京都'
        elif a not in ('全国総数','東北','関東','中部','近畿','中国','四国','九州'):
            pref=resolve(a)
        if pref is None and a in ('東北','関東','中部','近畿','中国','四国','九州',''):
            pref=resolve(b)
        value=to_int(r[3])
        if pref and value and pref not in counts: counts[pref]=value
    coords=defaultdict(list)
    for s in stats:
        if 'lon' in s: coords[s['prefecture']].append((s['lon'],s['lat']))
    out=[]
    for pref,count in counts.items():
        pts=coords.get(pref,[]); population=pop.get(pref,0)
        if not pts or not population: continue
        out.append({'prefecture':pref,'count':count,'population':population,
          'ratePer1000':round(count/population*1000,2),
          'lon':round(sum(x for x,_ in pts)/len(pts),4),'lat':round(sum(y for _,y in pts)/len(pts),4)})
    return {'year':2025,'populationYear':2024,'unit':'人口千人当たり刑法犯認知件数','records':out}

def dms_coord(v):
    s=str(v).strip()
    if not s.isdigit() or len(s)<8: return None
    deg_len=3 if len(s)>=10 else 2
    deg=int(s[:deg_len]); minute=int(s[deg_len:deg_len+2])
    sec=int(s[deg_len+2:deg_len+4]); frac=s[deg_len+4:]
    seconds=sec+(int(frac)/(10**len(frac)) if frac else 0)
    return deg+minute/60+seconds/3600

def build_accidents():
    rows=read_csv_url(ACCIDENT); head=rows[0]
    ix={n:i for i,n in enumerate(head)}
    grid=defaultdict(lambda:[0,0,0])
    for r in rows[1:]:
        try:
            lat=dms_coord(r[ix['地点　緯度（北緯）']]); lon=dms_coord(r[ix['地点　経度（東経）']])
        except Exception: continue
        if lat is None or lon is None: continue
        key=(round(lon,2),round(lat,2)); g=grid[key]
        g[0]+=1; g[1]+=to_int(r[ix['死者数']]); g[2]+=to_int(r[ix['負傷者数']])
    records=[[lon,lat,v[0],v[1],v[2]] for (lon,lat),v in grid.items()]
    return {'year':2024,'gridDegrees':0.01,'fields':['lon','lat','accidents','deaths','injuries'],'records':records}

def geojson_from_zip(url,suffix):
    blob=fetch(url); z=zipfile.ZipFile(io.BytesIO(blob))
    name=next(n for n in z.namelist() if n.endswith(suffix))
    return json.loads(z.read(name).decode('utf-8-sig'))

def midpoint(coords):
    if not coords: return None
    if isinstance(coords[0][0],(int,float)):
        a=coords[len(coords)//2]; return [round(a[0],6),round(a[1],6)]
    flat=[]
    for x in coords: flat.extend(x)
    return midpoint(flat)

def build_schools():
    obj=geojson_from_zip(SCHOOL,'P29-23.geojson'); out=[]
    for f in obj.get('features',[]):
        p=f.get('properties') or {}; c=f.get('geometry',{}).get('coordinates')
        if not c or p.get('P29_007') not in (0,'0',None): continue
        out.append([round(c[0],6),round(c[1],6),p.get('P29_004') or '',p.get('P29_003') or '',p.get('P29_005') or ''])
    return {'year':2023,'fields':['lon','lat','name','type','address'],'records':out}

def build_hospitals():
    obj=geojson_from_zip(HOSPITAL,'P04-20.geojson'); out=[]
    for f in obj.get('features',[]):
        p=f.get('properties') or {}; c=f.get('geometry',{}).get('coordinates')
        if not c or int(p.get('P04_001') or 0) != 1: continue
        out.append([round(c[0],6),round(c[1],6),p.get('P04_002') or '',p.get('P04_003') or '',p.get('P04_008') or 0])
    return {'year':2020,'fields':['lon','lat','name','address','beds'],'records':out}

def build_stations():
    obj=geojson_from_zip(STATION,'N02-25_Station.geojson'); out=[]; seen=set()
    for f in obj.get('features',[]):
        p=f.get('properties') or {}; c=midpoint(f.get('geometry',{}).get('coordinates') or [])
        if not c: continue
        key=(p.get('N02_005'),p.get('N02_004'),round(c[0],4),round(c[1],4))
        if key in seen: continue
        seen.add(key); out.append([c[0],c[1],p.get('N02_005') or '',p.get('N02_003') or '',p.get('N02_004') or ''])
    return {'year':2025,'fields':['lon','lat','name','line','operator'],'records':out}

def main():
    stats=attach_centroids(build_municipal_stats())
    write('municipality-stats-2026.json',{'source':'SSDSE-A-2026','years':{'population':2020,'households':2020,'vital':2023,'migration':2024,'medical':2023},'records':stats})
    write('crime-prefecture-2025.json',build_crime(stats))
    write('traffic-accidents-2024.json',build_accidents())
    write('poi-schools-2023.json',build_schools())
    write('poi-hospitals-2020.json',build_hospitals())
    write('poi-stations-2025.json',build_stations())

if __name__=='__main__':
    main()
