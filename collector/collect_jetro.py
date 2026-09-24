#!/usr/bin/env python3
import argparse, calendar, hashlib, html, http.cookiejar, json, re, sqlite3, time, unicodedata
import urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    from core.raw_store import save_json as save_raw_json
    from core.source_run import SourceRun
except ModuleNotFoundError:
    from collector.core.raw_store import save_json as save_raw_json
    from collector.core.source_run import SourceRun

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / 'data' / 'public_it.db'
DATA_DIR = ROOT / 'src' / 'data'
JSON_PATH = DATA_DIR / 'procurements.json'
COMPANY_PATH = DATA_DIR / 'companies.json'
ORG_PATH = DATA_DIR / 'organizations.json'
SUMMARY_PATH = DATA_DIR / 'summary.json'
DASHBOARD_DIR = ROOT / 'public' / 'data'
DASHBOARD_META_PATH = DASHBOARD_DIR / 'dashboard-meta.json'
DASHBOARD_LEGACY_PATH = DASHBOARD_DIR / 'dashboard.json'
DASHBOARD_SHARD_ROWS = 50000
BASE = 'https://www.jetro.go.jp'
LIST_PATH = '/gov_procurement/national/list.html'
API_PATH = '/view_interface.php?blockId=33235812'

TAG_RULES = {
    '生成AI': ['生成ai', '生成ａｉ', 'llm', '大規模言語モデル', 'rag'],
    'クラウド': ['クラウド', 'aws', 'azure', 'gcp', 'amazon web services'],
    'セキュリティ': ['セキュリティ', 'サイバー', '認証', '脆弱性', 'フォレンジック'],
    'ネットワーク': ['ネットワーク', 'lan', 'wan', '回線', '通信網'],
    'システム開発': ['システム', 'アプリ', 'ソフトウェア', 'プログラム', '情報基盤'],
    'データ': ['データ', 'データベース', '分析基盤', 'bi', '統計'],
    'IT機器': ['サーバ', 'pc', 'パソコン', '端末', 'ライセンス', 'ストレージ'],
}
IT_TERMS = sorted({t for terms in TAG_RULES.values() for t in terms} | {
    'it', 'ict', 'デジタル', '電子計算機', '情報処理', 'web', 'ウェブ', 'ホームページ'
})
BACKFILL_KEYWORDS = ['システム','ソフトウェア','クラウド','ネットワーク','セキュリティ','サーバ','データ','デジタル','情報処理','ライセンス']

MARKET_RULES = {
    'IT・デジタル': [
        'システム','ソフトウェア','クラウド','ネットワーク','セキュリティ','サーバ','データベース',
        '情報処理','デジタル','ict','it','pc','パソコン','端末','ライセンス','ホームページ','web',
        '電子計算機','アプリ','プログラム','ai','人工知能','通信回線','プリンタ','ファイアウォール','ハードウェア','wi-fi','wifi','スマートフォン','通信装置','無線装置','情報サービス','計算機資源','ポータル','電子化','ソフトウエア','sase','モバイルデバイス','共通基盤','インターネットアクセス','インターネット接続','インターネット基盤','freewi-fi','脅威管理','ip伝送','情報伝送'
    ],
    '建設・土木': [
        '工事','建築','土木','舗装','改修','改築','新築','解体','施工','道路','橋梁','トンネル','河川',
        '港湾','測量','設計業務','営繕','耐震','電気設備','機械設備','空調設備','整備事業'
    ],
    '医療・福祉': [
        '医療','病院','医薬','薬品','ワクチン','診療','検査薬','医療機器','福祉','介護','障害者',
        '健康診断','健診','看護','衛生材料','予防接種','x線','麻酔','内視鏡','人工心肺','人工呼吸器','酸素濃縮器','ナースコール','臨床','手術支援','透視診断','点滴静注','髄注','注射','遺伝子組換'
    ],
    '研究・調査・コンサル': [
        '調査','研究','分析','コンサル','検討業務','実証','実験','評価業務','統計調査','市場調査',
        'アンケート','計画策定','支援業務'
    ],
    '教育・研修': [
        '教育','研修','講習','教材','学校','大学','学習','授業','訓練','セミナー','eラーニング','教科書'
    ],
    '交通・物流': [
        '運送','輸送','配送','物流','車両','自動車','バス','鉄道','航空','船舶','タクシー','運行','郵便','発送','引越','レンタカー','監視艇','トラック','散布車','除雪車','照明車','救難車','消防車','巡視船','練習船'
    ],
    '施設管理・清掃': [
        '清掃','警備','保守管理','施設管理','設備管理','ビル管理','点検','維持管理','受付業務',
        '廃棄物','ごみ処理','除草','剪定','保守業務','保守契約','修理','庁舎管理','建物等総合管理','保安管理','ビルメンテナンス','設備運転'
    ],
    '広報・広告・制作': [
        '広報','広告','印刷','パンフレット','ポスター','動画制作','映像制作','冊子','デザイン',
        'イベント運営','展示','プロモーション','刷成'
    ],
    'エネルギー・環境': [
        '電力','電気需給','電気の供給','使用する電気','ガス','燃料','石油','重油','灯油','軽油','ガソリン','再生可能エネルギー','環境影響評価','環境再生','環境保全','環境モニタリング','自然環境','環境政策','環境調査','環境測定','環境対策','脱炭素','省エネ',
        '太陽光','蓄電池','水質','大気'
    ],
    '食品・給食': [
        '給食','食材','食品','弁当','飲料','米穀','野菜','肉類','魚介','食堂','精白米','玄米','備蓄食料','菓子'
    ],
    '科学・研究機器': [
        '測定装置','分析装置','実験装置','研究装置','顕微鏡','レーザー','検出器','シーケンサー','分光',
        '核磁気共鳴','量子デバイス','ビームライン','試薬','センサ','センサー','トランスデューサー','研究機器','実験機器','計測装置','解析装置','評価装置','ナノインデンター'
    ],
    '出版・情報資料': [
        '書籍','雑誌','電子ジャーナル','図書','新聞','購読','六法','電子ブック','sciencedirect','wiley','springer','nature'
    ],
    '化学・素材': [
        '塩化ナトリウム','凍結防止剤','液体窒素','原糸','鋼材','合金','樹脂','セメント','コンクリート','化学品','薬剤','原材料'
    ],
    '衣類・装備品': [
        'ジャケット','ブルゾン','ポロシャツ','シャツ','制服','被服','キャップ','帽子','防寒','レインジャケット','作業服','ズックぐつ','安全靴','防護服','ネクタイ'
    ],
    '機械・設備': [
        '装置','機器','機械','設備','ポンプ','ボイラ','エアコン','空調機','冷凍機','発電機','変圧器','ロボット','据付','クレーン','フォークリフト','圧縮機'
    ],
    '製造・製作': [
        '製造','製作'
    ],
    '人材・業務委託': [
        '業務委託','委託','労働者派遣','人材派遣','コールセンター','電話応対','運営業務','事務補助','翻訳','通訳'
    ],
    '一般物品・備品': [
        '備品','事務用品','家具','什器','消耗品','用紙','文具','コピー用紙','複合機','机','椅子','トナー','封筒','帳票','バッテリ','物品','鉛筆','クリアファイル','冷蔵庫','シュレッダー','マットレス','寝具','寝台'
    ],
}
MARKET_PRIORITY = list(MARKET_RULES)
ENERGY_PRIMARY_TERMS = [
    '使用する電気','電気の供給','電力供給','電気の調達','電気契約','電力契約',
    '重油','灯油','軽油','ガソリン','燃料購入','燃料の購入'
]

def clean(value=''):
    value = re.sub(r'<br\s*/?>', ' ', str(value or ''), flags=re.I)
    return re.sub(r'\s+', ' ', html.unescape(value)).strip()

def norm(value=''):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', clean(value))).lower()

def stable_id(prefix, value):
    return prefix + '_' + hashlib.sha1(norm(value).encode()).hexdigest()[:12]

def parse_date(value):
    m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', value or '')
    return f'{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}' if m else ''

def parse_reiwa_date(value):
    s = unicodedata.normalize('NFKC', value or '')
    m = re.search(r'(?<!\d)(\d{1,2})\s*[.．/]\s*(\d{1,2})\s*[.．/]\s*(\d{1,2})(?!\d)', s)
    if not m: return ''
    y, mo, d = map(int, m.groups())
    y = 2018 + y if y < 100 else y
    return f'{y:04d}-{mo:02d}-{d:02d}'

def parse_yen(value):
    s = unicodedata.normalize('NFKC', value or '').replace(',', '')
    m = re.search(r'(\d+)\s*円', s)
    return int(m.group(1)) if m else None

TERM_MATCHERS = {}

def term_match(raw, compact, term):
    matcher = TERM_MATCHERS.get(term)
    if matcher is None:
        t = unicodedata.normalize('NFKC', clean(term)).lower()
        if re.fullmatch(r'[a-z0-9.+#-]+', t):
            matcher = ('regex', re.compile(r'(?<![a-z0-9])' + re.escape(t) + r'(?![a-z0-9])'))
        else:
            matcher = ('text', re.sub(r'\s+', '', t))
        TERM_MATCHERS[term] = matcher
    return bool(matcher[1].search(raw)) if matcher[0] == 'regex' else matcher[1] in compact

def classify(title):
    subject = re.sub(r'^\s*【[^】]*地方整備局[^】]*】\s*', '', clean(title))
    raw = unicodedata.normalize('NFKC', subject).lower()
    compact = re.sub(r'\s+', '', raw)
    match = lambda t: term_match(raw, compact, t)
    tags = [tag for tag, terms in TAG_RULES.items() if any(match(t) for t in terms)]
    is_it = any(match(t) for t in IT_TERMS)
    category_tags = [cat for cat, terms in MARKET_RULES.items() if any(match(t) for t in terms)]
    if is_it and 'IT・デジタル' not in category_tags:
        category_tags.insert(0, 'IT・デジタル')
    if 'エネルギー・環境' in category_tags and any(match(t) for t in ENERGY_PRIMARY_TERMS):
        category = 'エネルギー・環境'
    else:
        category = next((c for c in MARKET_PRIORITY if c in category_tags), 'その他')
    return is_it, tags, category, category_tags

def open_with_retry(op, req, timeout=30, attempts=6):
    last=None
    for i in range(attempts):
        try:
            return op.open(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            last=e
            if e.code not in (403,429,500,502,503,504) or i == attempts-1:
                raise
            delay=min(30, 2 ** (i + 1))
            print(f'http_retry status={e.code} delay={delay}s')
            time.sleep(delay)
    raise last

def make_opener(params=None):
    qs = urllib.parse.urlencode(params or {})
    referer = BASE + LIST_PATH + (('?' + qs) if qs else '')
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    req = urllib.request.Request(referer, headers={'User-Agent':'Mozilla/5.0 PublicMarketData/0.3'})
    with open_with_retry(op, req, timeout=30) as res: res.read()
    return op, referer

def fetch_page(op, referer, offset=0, params=None):
    q = dict(params or {}); q['current'] = offset
    url = BASE + API_PATH + '&' + urllib.parse.urlencode(q)
    headers = {'User-Agent':'Mozilla/5.0 PublicMarketData/0.3','Referer':referer,
      'Accept':'application/json, text/javascript, */*; q=0.01','X-Requested-With':'XMLHttpRequest'}
    with open_with_retry(op, urllib.request.Request(url, headers=headers), timeout=30) as res:
        data = json.loads(res.read().decode('utf-8'))
    save_raw_json('jetro', json.dumps(q, ensure_ascii=False, sort_keys=True), data)
    return data
def visible_text(raw_html):
    s = re.sub(r'<script[\s\S]*?</script>|<style[\s\S]*?</style>', ' ', raw_html, flags=re.I)
    s = re.sub(r'<br\s*/?>|</(?:p|div|li|tr|h\d)>', '\n', s, flags=re.I)
    s = re.sub(r'<[^>]+>', ' ', s)
    lines = [clean(x) for x in html.unescape(s).splitlines()]
    return '\n'.join(x for x in lines if x)

def extract_numbered_fields(text):
    marker = '①品目分類番号'
    pos = text.find(marker)
    if pos >= 0: text = text[pos + len(marker):]
    # Indexed/cached historical copies may collapse line breaks, so split on every next ① marker.
    blocks = re.findall(r'①([\s\S]*?)(?=①|$)', text)
    parsed = []
    for block in blocks:
        fields = {}
        for idx, num in enumerate('①②③④⑤⑥⑦⑧⑨⑩⑪⑫'):
            target = block if num == '①' else num + block.split(num,1)[1] if num in block else ''
        chunks = re.split(r'([②③④⑤⑥⑦⑧⑨⑩⑪⑫])', '①' + block)
        current = None
        for chunk in chunks:
            if chunk in '①②③④⑤⑥⑦⑧⑨⑩⑪⑫': current = chunk
            elif current: fields[current] = clean(fields.get(current,'') + ' ' + chunk)
        if fields.get('②'): parsed.append(fields)
    return parsed

def choose_detail_block(blocks, title):
    nt = norm(title)
    for b in blocks:
        if nt and (nt in norm(b.get('②','')) or norm(b.get('②','')) in nt): return b
    return blocks[0] if blocks else {}

PREFECTURES = ['北海道','青森県','岩手県','宮城県','秋田県','山形県','福島県','茨城県','栃木県','群馬県','埼玉県','千葉県','東京都','神奈川県','新潟県','富山県','石川県','福井県','山梨県','長野県','岐阜県','静岡県','愛知県','三重県','滋賀県','京都府','大阪府','兵庫県','奈良県','和歌山県','鳥取県','島根県','岡山県','広島県','山口県','徳島県','香川県','愛媛県','高知県','福岡県','佐賀県','長崎県','熊本県','大分県','宮崎県','鹿児島県','沖縄県']
LEGAL_SUFFIXES = ['株式会社','有限会社','合同会社','合資会社','合名会社','一般社団法人','一般財団法人','公益社団法人','公益財団法人']

def canonical_company_name(value):
    s = clean(unicodedata.normalize('NFKC', value or ''))
    s = s.replace('(株)', '株式会社').replace('（株）', '株式会社')
    s = s.replace('(有)', '有限会社').replace('（有）', '有限会社')
    return re.sub(r'\s+', '', s).strip(' 、,')

def extract_company_name(value):
    s = clean(value).strip(' 、,')
    s = re.split(r'[（(]', s, maxsplit=1)[0].strip()
    for suffix in LEGAL_SUFFIXES:
        pos = s.find(suffix)
        if pos > 0:
            return canonical_company_name(s[:pos+len(suffix)])
    cut = len(s)
    for pref in PREFECTURES:
        pos = s.find(pref, 3)
        if 0 < pos < cut: cut = pos
    return canonical_company_name(s[:cut])

def clean_award_method(value):
    s = clean(value)
    for label in ['総合評価','最低価格','最高価格','価格競争']:
        if label in s:
            return label
    return s[:80] if len(s) <= 80 else ''

def fetch_detail(op, url, title):
    headers = {'User-Agent':'Mozilla/5.0 PublicMarketData/0.3','Referer':BASE + LIST_PATH}
    with open_with_retry(op, urllib.request.Request(url, headers=headers), timeout=30) as res:
        raw = res.read().decode('utf-8','ignore')
    block = choose_detail_block(extract_numbered_fields(visible_text(raw)), title)
    if not block: return {}
    winner_field = block.get('⑥','')
    winner = extract_company_name(winner_field)
    return {
      'contract_method': clean(block.get('④','')),
      'award_date': parse_reiwa_date(block.get('⑤','')),
      'winner_name': winner,
      'award_amount': parse_yen(block.get('⑦','')),
      'award_method': clean_award_method(block.get('⑪','')),
      'estimated_amount': parse_yen(block.get('⑫','')),
      'detail_text': clean(' '.join(block.values()))[:8000],
    }

def init_db(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS procurements (
      source_id TEXT PRIMARY KEY, xid INTEGER NOT NULL, aid TEXT NOT NULL,
      title TEXT NOT NULL, notice_date TEXT, agency TEXT, organization_id TEXT,
      notice_type TEXT, source_url TEXT NOT NULL, is_it INTEGER NOT NULL DEFAULT 0,
      category TEXT NOT NULL DEFAULT 'その他', category_tags_json TEXT NOT NULL DEFAULT '[]',
      tags_json TEXT NOT NULL DEFAULT '[]', detail_fetched INTEGER NOT NULL DEFAULT 0,
      award_date TEXT, contract_method TEXT, award_method TEXT, winner_name TEXT,
      company_id TEXT, award_amount INTEGER, estimated_amount INTEGER,
      detail_text TEXT, collected_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS companies (
      company_id TEXT PRIMARY KEY, company_name TEXT NOT NULL, normalized_name TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS organizations (
      organization_id TEXT PRIMARY KEY, organization_name TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_proc_notice_date ON procurements(notice_date);
    CREATE INDEX IF NOT EXISTS idx_proc_is_it ON procurements(is_it);
    CREATE INDEX IF NOT EXISTS idx_proc_company ON procurements(company_id);
    CREATE INDEX IF NOT EXISTS idx_proc_org ON procurements(organization_id);
    ''')
    cols = {row[1] for row in conn.execute('PRAGMA table_info(procurements)')}
    if 'category' not in cols:
        conn.execute("ALTER TABLE procurements ADD COLUMN category TEXT NOT NULL DEFAULT 'その他'")
    if 'category_tags_json' not in cols:
        conn.execute("ALTER TABLE procurements ADD COLUMN category_tags_json TEXT NOT NULL DEFAULT '[]'")
    conn.execute('CREATE INDEX IF NOT EXISTS idx_proc_category ON procurements(category)')
    conn.commit()
def seed_from_json(conn):
    paths=sorted(DATA_DIR.glob('procurements-*.json'))
    if not paths and JSON_PATH.exists(): paths=[JSON_PATH]
    if not paths: return 0
    records=[]
    for path in paths:
        try: records.extend(json.loads(path.read_text(encoding='utf-8')))
        except Exception as e:
            print(f'seed_error {path.name}: {e}')
    now = datetime.now(timezone.utc).isoformat(); count = 0
    for r in records:
        parts = str(r.get('id','')).split(':')
        if len(parts) != 3 or parts[0] not in ('jetro','jetro-local','geps'): continue
        scope=parts[0]; xid=int(parts[1]); aid=parts[2]
        agency = r.get('agency',''); org_id = stable_id('org', agency) if agency else None
        winner = canonical_company_name(r.get('winnerName') or ''); company_id = stable_id('co', winner) if winner else None
        if org_id: conn.execute('INSERT OR IGNORE INTO organizations VALUES (?,?)',(org_id,agency))
        if company_id: conn.execute('INSERT OR IGNORE INTO companies VALUES (?,?,?)',(company_id,winner,norm(winner)))
        is_it, tags, category, category_tags = classify(r.get('title',''))
        source_url=r.get('sourceUrl') or (f'{BASE}/gov_procurement/local/articles/{aid}.html' if scope=='jetro-local' else (f'https://www.p-portal.go.jp/pps-web-biz/UAB02/OAB0201?caseNo={aid}' if scope=='geps' else f'{BASE}/gov_procurement/national/articles/{xid}/{aid}.html'))
        conn.execute('''INSERT OR IGNORE INTO procurements
          (source_id,xid,aid,title,notice_date,agency,organization_id,notice_type,source_url,is_it,category,category_tags_json,tags_json,
           detail_fetched,award_date,contract_method,award_method,winner_name,company_id,award_amount,estimated_amount,detail_text,collected_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(
          r['id'],xid,aid,r.get('title',''),r.get('noticeDate',''),agency,org_id,
          r.get('noticeType',''),source_url,int(is_it),r.get('category') or category,
          json.dumps(r.get('categoryTags') or category_tags,ensure_ascii=False),json.dumps(r.get('tags') or tags,ensure_ascii=False),
          int(bool(r.get('detailFetched'))),r.get('awardDate'),r.get('contractMethod'),r.get('awardMethod'),winner or None,
          company_id,r.get('awardAmount'),r.get('estimatedAmount'),r.get('detailText'),now))
        count += 1
    conn.commit(); return count

def reclassify_existing(conn):
    rows=conn.execute('SELECT source_id,title FROM procurements').fetchall()
    for source_id,title in rows:
        is_it,tags,category,category_tags=classify(title)
        conn.execute('''UPDATE procurements SET is_it=?,category=?,category_tags_json=?,tags_json=? WHERE source_id=?''',
          (int(is_it),category,json.dumps(category_tags,ensure_ascii=False),json.dumps(tags,ensure_ascii=False),source_id))
    conn.commit()
    return len(rows)

def save_items(conn, items):
    now = datetime.now(timezone.utc).isoformat(); saved = 0
    for item in items:
        title = clean(item.get('title','')); is_it, tags, category, category_tags = classify(title)
        xid, aid = int(item['xid']), str(item['aid']); agency = clean(item.get('agency',''))
        org_id = stable_id('org',agency) if agency else None
        if org_id: conn.execute('INSERT OR IGNORE INTO organizations VALUES (?,?)',(org_id,agency))
        conn.execute('''INSERT INTO procurements
          (source_id,xid,aid,title,notice_date,agency,organization_id,notice_type,source_url,is_it,category,category_tags_json,tags_json,collected_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(source_id) DO UPDATE SET title=excluded.title,notice_date=excluded.notice_date,
            agency=excluded.agency,organization_id=excluded.organization_id,notice_type=excluded.notice_type,
            source_url=excluded.source_url,is_it=excluded.is_it,category=excluded.category,
            category_tags_json=excluded.category_tags_json,tags_json=excluded.tags_json,collected_at=excluded.collected_at''',(
          f'jetro:{xid}:{aid}',xid,aid,title,parse_date(item.get('date','')),agency,org_id,clean(item.get('paKind','')),
          f'{BASE}/gov_procurement/national/articles/{xid}/{aid}.html',int(is_it),category,
          json.dumps(category_tags,ensure_ascii=False),json.dumps(tags,ensure_ascii=False),now))
        saved += 1
    conn.commit(); return saved

def enrich_awards(conn, op, limit=None, delay=0.08):
    if limit == 0:
        return 0
    q = '''SELECT source_id,title,source_url FROM procurements
           WHERE notice_type LIKE '%落札者等の公示%' AND detail_fetched=0
           ORDER BY notice_date DESC'''
    rows = conn.execute(q).fetchall()
    if limit and len(rows) > limit:
        dated = conn.execute('''SELECT source_id,title,source_url,substr(COALESCE(notice_date,''),1,7) m FROM procurements
          WHERE notice_type LIKE '%落札者等の公示%' AND detail_fetched=0 ORDER BY notice_date''').fetchall()
        buckets = {}
        for row in dated: buckets.setdefault(row[3] or 'unknown', []).append(row[:3])
        spread=[]
        while len(spread)<limit and any(buckets.values()):
            for key in sorted(buckets):
                if buckets[key] and len(spread)<limit: spread.append(buckets[key].pop(0))
        rows=spread
    ok = 0
    for source_id,title,url in rows:
        try:
            d = fetch_detail(op,url,title); winner = d.get('winner_name') or ''
            company_id = stable_id('co',winner) if winner else None
            if company_id: conn.execute('INSERT OR IGNORE INTO companies VALUES (?,?,?)',(company_id,winner,norm(winner)))
            conn.execute('''UPDATE procurements SET detail_fetched=1,award_date=?,contract_method=?,award_method=?,
              winner_name=?,company_id=?,award_amount=?,estimated_amount=?,detail_text=? WHERE source_id=?''',(
              d.get('award_date'),d.get('contract_method'),d.get('award_method'),winner or None,company_id,
              d.get('award_amount'),d.get('estimated_amount'),d.get('detail_text'),source_id))
            conn.commit(); ok += 1
        except Exception as e:
            print(f'detail_error {source_id}: {e}')
        if delay: time.sleep(delay)
    return ok
def export_json(conn):
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    cols = ['source_id','title','notice_date','agency','organization_id','notice_type','source_url','is_it','category','category_tags_json','tags_json',
      'detail_fetched','award_date','contract_method','award_method','winner_name','company_id','award_amount','estimated_amount','detail_text']
    rows = conn.execute('SELECT '+','.join(cols)+' FROM procurements ORDER BY notice_date DESC,source_id DESC').fetchall()
    out=[]
    for r in rows:
        d=dict(zip(cols,r)); out.append({
          'id':d['source_id'],'title':d['title'],'noticeDate':d['notice_date'],'agency':d['agency'],
          'organizationId':d['organization_id'],'noticeType':d['notice_type'],'sourceUrl':d['source_url'],
          'source':'geps' if d['source_id'].startswith('geps:') else 'jetro',
          'isIt':bool(d['is_it']),'category':d['category'] or 'その他','categoryTags':json.loads(d['category_tags_json'] or '[]'),
          'tags':json.loads(d['tags_json']),'detailFetched':bool(d['detail_fetched']),
          'awardDate':d['award_date'],'contractMethod':d['contract_method'],'awardMethod':d['award_method'],
          'winnerName':d['winner_name'],'companyId':d['company_id'],'awardAmount':d['award_amount'],
          'estimatedAmount':d['estimated_amount'],'detailText':d['detail_text']})
    # Gitで保持する静的ページ用データは、未使用の詳細本文等を除外して50MB未満に抑える。
    page_records = [{
      'id':x['id'],'title':x['title'],'noticeDate':x['noticeDate'],'agency':x['agency'],
      'organizationId':x['organizationId'],'noticeType':x['noticeType'],'sourceUrl':x['sourceUrl'],
      'source':x['source'],'isIt':x['isIt'],'category':x['category'],'tags':x['tags'],'detailFetched':x['detailFetched'],
      'awardDate':x['awardDate'],'contractMethod':x['contractMethod'],'awardMethod':x['awardMethod'],
      'winnerName':x['winnerName'],'companyId':x['companyId'],'awardAmount':x['awardAmount']
    } for x in out]
    # 年別に分割してGitHubの単一ファイル上限を避ける。旧モノリスJSONは移行後に削除する。
    by_year={}
    for rec in page_records:
        year=(rec.get('noticeDate') or '')[:4] or 'unknown'
        by_year.setdefault(year,[]).append(rec)
    for old_path in DATA_DIR.glob('procurements-*.json'):
        old_path.unlink()
    for year,recs in sorted(by_year.items()):
        (DATA_DIR / f'procurements-{year}.json').write_text(
          json.dumps(recs,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    if JSON_PATH.exists(): JSON_PATH.unlink()

    # ブラウザ向けは辞書化 + 配列化。URLは source_id から復元し、文字列の重複を極力なくす。
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    agencies=sorted({x['agency'] or '' for x in out})
    categories=sorted({x['category'] or 'その他' for x in out})
    winners=sorted({x['winnerName'] or '' for x in out})
    contract_methods=sorted({x['contractMethod'] or '' for x in out})
    award_methods=sorted({clean_award_method(x.get('awardMethod') or '') for x in out})
    tag_names=sorted({t for x in out for t in (x.get('tags') or [])})
    agency_idx={v:i for i,v in enumerate(agencies)}
    category_idx={v:i for i,v in enumerate(categories)}
    winner_idx={v:i for i,v in enumerate(winners)}
    contract_idx={v:i for i,v in enumerate(contract_methods)}
    award_idx={v:i for i,v in enumerate(award_methods)}
    tag_idx={v:i for i,v in enumerate(tag_names)}
    dashboard_rows=[]
    for x in out:
        is_local=x['id'].startswith('jetro-local:')
        is_geps=x['id'].startswith('geps:')
        if is_local:
            sid=x['id'].split(':',2)[-1]
        elif is_geps:
            sid=x['id'].split(':',2)[1]
        else:
            sid=x['id'][6:] if x['id'].startswith('jetro:') else x['id']
        source_kind=1 if is_local else (2 if is_geps else 0)
        tag_mask=sum(1 << tag_idx[t] for t in (x.get('tags') or []) if t in tag_idx)
        dashboard_rows.append([
          sid,x['title'] or '',(x['noticeDate'] or '').replace('-',''),
          agency_idx[x['agency'] or ''],category_idx[x['category'] or 'その他'],tag_mask,
          (x['awardDate'] or '').replace('-',''),contract_idx[x['contractMethod'] or ''],
          award_idx[clean_award_method(x.get('awardMethod') or '')],winner_idx[x['winnerName'] or ''],
          x['awardAmount'] or 0,source_kind
        ])
    # Cloudflare Pages allows up to 25 MiB per asset, so split the large browser dataset.
    for old_shard in DASHBOARD_DIR.glob('dashboard-*.json'):
        old_shard.unlink()
    shard_names=[]; shard_info=[]
    for i in range(0,len(dashboard_rows),DASHBOARD_SHARD_ROWS):
        name=f'dashboard-{i//DASHBOARD_SHARD_ROWS:02d}.json'
        shard=dashboard_rows[i:i+DASHBOARD_SHARD_ROWS]
        (DASHBOARD_DIR / name).write_text(
          json.dumps(shard,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
        shard_names.append(name)
        years=sorted({str(r[2])[:4] for r in shard if r[2]})
        shard_info.append({'name':name,'years':years,'rows':len(shard)})
    all_years=sorted({str(r[2])[:4] for r in dashboard_rows if r[2]}, reverse=True)
    dashboard_meta={'v':1,'a':agencies,'c':categories,'w':winners,'m':contract_methods,
      'am':award_methods,'t':tag_names,'shards':shard_names,'shardInfo':shard_info,'years':all_years,
      'latestYear':all_years[0] if all_years else ''}
    DASHBOARD_META_PATH.write_text(json.dumps(dashboard_meta,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    if DASHBOARD_LEGACY_PATH.exists(): DASHBOARD_LEGACY_PATH.unlink()
    companies=[]
    for cid,name in conn.execute('SELECT company_id,company_name FROM companies ORDER BY company_name'):
        a=conn.execute('SELECT COUNT(*),COALESCE(SUM(award_amount),0) FROM procurements WHERE company_id=?',(cid,)).fetchone()
        companies.append({'id':cid,'name':name,'awardCount':a[0],'awardTotal':a[1]})
    COMPANY_PATH.write_text(json.dumps(companies,ensure_ascii=False,indent=2),encoding='utf-8')
    orgs=[]
    for oid,name in conn.execute('SELECT organization_id,organization_name FROM organizations ORDER BY organization_name'):
        a=conn.execute('SELECT COUNT(*),COALESCE(SUM(award_amount),0) FROM procurements WHERE organization_id=?',(oid,)).fetchone()
        it=conn.execute('SELECT COUNT(*) FROM procurements WHERE organization_id=? AND is_it=1',(oid,)).fetchone()[0]
        orgs.append({'id':oid,'name':name,'recordCount':a[0],'itCount':it,'awardTotal':a[1]})
    ORG_PATH.write_text(json.dumps(orgs,ensure_ascii=False,indent=2),encoding='utf-8')
    total_it=sum(1 for x in out if x['isIt']); awards=[x for x in out if x['awardAmount']]
    category_counts={}
    for x in out: category_counts[x['category']]=category_counts.get(x['category'],0)+1
    local_records=sum(1 for x in out if x['id'].startswith('jetro-local:'))
    geps_records=sum(1 for x in out if x['id'].startswith('geps:'))
    dates=[x['noticeDate'] for x in out if x.get('noticeDate')]
    summary={'records':len(out),'nationalRecords':len(out)-local_records,'localRecords':local_records,
      'jetroRecords':len(out)-geps_records,'gepsRecords':geps_records,
      'firstDate':min(dates) if dates else None,'lastDate':max(dates) if dates else None,
      'itRecords':total_it,'awardRecords':len(awards),
      'awardTotal':sum(x['awardAmount'] for x in awards),'companies':len(companies),'organizations':len(orgs),
      'categoryCounts':category_counts,'generatedAt':datetime.now(timezone.utc).isoformat()}
    SUMMARY_PATH.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    return summary

def collect_pages(conn, pages, params=None):
    op,ref=make_opener(params); total=0
    for page in range(max(0,pages)):
        data=fetch_page(op,ref,page*30,params); total += save_items(conn,data.get('items',[]))
    return total,op

def month_windows(start_date, end_date):
    sy,sm=map(int,start_date[:7].split('-')); ey,em=map(int,end_date[:7].split('-'))
    y,m=sy,sm
    while (y,m) <= (ey,em):
        last=calendar.monthrange(y,m)[1]
        start=f'{y:04d}-{m:02d}-01'; end=f'{y:04d}-{m:02d}-{last:02d}'
        if start < start_date: start=start_date
        if end > end_date: end=end_date
        yield start,end
        m += 1
        if m==13: y,m=y+1,1

def backfill_monthly(conn, from_date, to_date, pages_per_month):
    seen=set(); fetched=0
    for start,end in month_windows(from_date,to_date):
        month_added=0
        for keyword in BACKFILL_KEYWORDS:
            params={'type':'06','keyword':keyword,'from':start.replace('-','/'),'to':end.replace('-','/')}
            op,ref=make_opener(params); first=fetch_page(op,ref,0,params); total=first['pagination']['total']
            page_count=min(pages_per_month,max(1,(total+29)//30)) if total else 0
            for page in range(page_count):
                data=first if page==0 else fetch_page(op,ref,page*30,params)
                unique=[x for x in data.get('items',[]) if (x['xid'],x['aid']) not in seen]
                for x in unique: seen.add((x['xid'],x['aid']))
                month_added += save_items(conn,unique); fetched += len(unique)
        print(f'backfill month={start[:7]} rows={month_added}')
    return fetched

def backfill_all_monthly(conn, from_date, to_date, pages_limit=0):
    fetched=0
    for start,end in month_windows(from_date,to_date):
        params={'type':'06','from':start.replace('-','/'),'to':end.replace('-','/')}
        op,ref=make_opener(params)
        first=fetch_page(op,ref,0,params)
        total=int(first.get('pagination',{}).get('total') or 0)
        page_count=(total+29)//30 if total else 0
        if pages_limit:
            page_count=min(page_count,pages_limit)
        month_added=0
        for page in range(page_count):
            data=first if page==0 else fetch_page(op,ref,page*30,params)
            rows=data.get('items',[])
            month_added += save_items(conn,rows)
            fetched += len(rows)
            time.sleep(0.12)
        print(f'backfill-all month={start[:7]} rows={month_added} total={total} pages={page_count}', flush=True)
        time.sleep(0.5)
    return fetched

def backfill_all_notices_monthly(conn, from_date, to_date, pages_limit=0):
    fetched=0
    for start,end in month_windows(from_date,to_date):
        params={'from':start.replace('-','/'),'to':end.replace('-','/')}
        op,ref=make_opener(params)
        first=fetch_page(op,ref,0,params)
        total=int(first.get('pagination',{}).get('total') or 0)
        page_count=(total+29)//30 if total else 0
        if pages_limit:
            page_count=min(page_count,pages_limit)
        month_added=0
        for page in range(page_count):
            data=first if page==0 else fetch_page(op,ref,page*30,params)
            rows=data.get('items',[])
            month_added += save_items(conn,rows)
            fetched += len(rows)
            time.sleep(0.12)
        print(f'catchup-all month={start[:7]} rows={month_added} total={total} pages={page_count}', flush=True)
        time.sleep(0.5)
    return fetched

def backfill_keywords(conn, from_date, to_date, pages_per_keyword):
    seen=set(); fetched=0
    for keyword in BACKFILL_KEYWORDS:
        params={'type':'06','keyword':keyword,'from':from_date.replace('-','/'),'to':to_date.replace('-','/')}
        op,ref=make_opener(params)
        first=fetch_page(op,ref,0,params); total=first['pagination']['total']
        page_count=min(pages_per_keyword,max(1,(total+29)//30))
        for page in range(page_count):
            data=first if page==0 else fetch_page(op,ref,page*30,params)
            unique=[x for x in data.get('items',[]) if (x['xid'],x['aid']) not in seen]
            for x in unique: seen.add((x['xid'],x['aid']))
            fetched += save_items(conn,unique)
        print(f'backfill keyword={keyword} pages={page_count} total_matches={total}')
    return fetched

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--pages',type=int,default=10,help='最新一覧を30件単位で取得')
    p.add_argument('--detail-limit',type=int,default=300,help='未解析IT落札詳細の最大取得件数')
    p.add_argument('--backfill-from',default='',help='YYYY-MM-DD')
    p.add_argument('--backfill-to',default=datetime.now().strftime('%Y-%m-%d'))
    p.add_argument('--backfill-pages',type=int,default=0,help='各ITキーワードで遡る30件ページ数')
    p.add_argument('--backfill-monthly-pages',type=int,default=0,help='各月・各ITキーワードで取得する30件ページ数')
    p.add_argument('--backfill-all-monthly',action='store_true',help='指定期間の全分野の落札公示を月単位で全件取得')
    p.add_argument('--backfill-all-notices-monthly',action='store_true',help='指定期間の全公示種別を月単位で全件取得')
    p.add_argument('--backfill-all-pages',type=int,default=0,help='全分野バックフィルの月あたり最大ページ数。0は全件')
    p.add_argument('--refresh-details',action='store_true')
    args=p.parse_args()

    with SourceRun('jetro', 'JETRO 政府公共調達データベース') as run:
        DB_PATH.parent.mkdir(parents=True,exist_ok=True)
        conn=sqlite3.connect(DB_PATH); init_db(conn); seed_from_json(conn); reclassify_existing(conn)
        fetched,op=collect_pages(conn,args.pages)
        if args.refresh_details:
            conn.execute("UPDATE procurements SET detail_fetched=0 WHERE notice_type LIKE '%落札者等の公示%'"); conn.commit()
        if args.backfill_from and args.backfill_all_notices_monthly:
            fetched += backfill_all_notices_monthly(conn,args.backfill_from,args.backfill_to,args.backfill_all_pages)
        elif args.backfill_from and args.backfill_all_monthly:
            fetched += backfill_all_monthly(conn,args.backfill_from,args.backfill_to,args.backfill_all_pages)
        elif args.backfill_from and args.backfill_monthly_pages:
            fetched += backfill_monthly(conn,args.backfill_from,args.backfill_to,args.backfill_monthly_pages)
        elif args.backfill_from and args.backfill_pages:
            fetched += backfill_keywords(conn,args.backfill_from,args.backfill_to,args.backfill_pages)
        enriched=enrich_awards(conn,op,args.detail_limit)
        conn.execute('DELETE FROM companies WHERE company_id NOT IN (SELECT DISTINCT company_id FROM procurements WHERE company_id IS NOT NULL)'); conn.commit()
        summary=export_json(conn)
        run.set_metrics(records=summary['records'], itRecords=summary['itRecords'],
            awardRecords=summary['awardRecords'], companies=summary['companies'],
            organizations=summary['organizations'], fetched=fetched, enriched=enriched)
        print(f'fetched={fetched} enriched={enriched} stored={summary["records"]} it={summary["itRecords"]} awards={summary["awardRecords"]} award_total={summary["awardTotal"]}')

if __name__=='__main__': main()
