#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
export PATH="$HOME/.nvm/versions/node/v22.23.2/bin:$PATH"
STATE_DIR="$ROOT/data/automation"
RELEASE_LOCK="$STATE_DIR/release.lock"
mkdir -p "$STATE_DIR"
if [[ "${DATLUME_RELEASE_LOCK_HELD:-0}" != "1" ]]; then
  exec 8>"$RELEASE_LOCK"
  echo "Waiting for DATLUME release lock: $RELEASE_LOCK"
  flock 8
fi
TOKEN_FILE="$HOME/.datlume-cloudflare-token"
ACCOUNT_FILE="$HOME/.datlume-cloudflare-account-id"
if [ ! -s "$TOKEN_FILE" ]; then echo 'Cloudflare credential file is missing.'; exit 1; fi
if [ ! -s "$ACCOUNT_FILE" ]; then echo 'Cloudflare account-id file is missing.'; exit 1; fi
export CLOUDFLARE_API_TOKEN="$(tr -d '\r\n' < "$TOKEN_FILE")"
export CLOUDFLARE_ACCOUNT_ID="$(tr -d '\r\n' < "$ACCOUNT_FILE")"
if [ ! -s dist/data/dashboard-meta.json ]; then echo 'Full DATLUME build is missing.'; exit 1; fi
SOURCE_SHARDS=$(find src/data -maxdepth 1 -type f -name 'procurements-*.json' | wc -l)
SOURCE_RECORDS=$(python3 - <<'PY'
import json
from pathlib import Path
p=Path('src/data/summary.json')
try:
    print(int(json.loads(p.read_text(encoding='utf-8')).get('records',0)))
except Exception:
    print(0)
PY
)
if [ "$SOURCE_SHARDS" -lt 1 ] || [ "$SOURCE_RECORDS" -lt 1000 ]; then
  echo "Refusing incomplete deploy: procurement shards=$SOURCE_SHARDS records=$SOURCE_RECORDS"
  exit 2
fi
if [ ! -f "functions/procurement/companies/[id].js" ] || [ ! -s "dist/_routes.json" ]; then
  echo 'Refusing incomplete deploy: company Pages Function or routes config missing.'
  exit 3
fi
COMPANY_DETAIL_SHARDS=$(find dist/data/company-details -maxdepth 1 -type f -name '*.json' 2>/dev/null | wc -l)
if [ "$COMPANY_DETAIL_SHARDS" -ne 256 ]; then
  echo "Refusing incomplete deploy: company detail shards=$COMPANY_DETAIL_SHARDS expected=256"
  exit 3
fi
if [ ! -f "functions/listed-companies/[code].js" ] || [ ! -s "dist/data/listed-companies/summary.json" ]; then
  echo 'Refusing incomplete deploy: listed-company Pages Function or summary missing.'
  exit 3
fi
LISTED_DETAIL_SHARDS=$(find dist/data/listed-companies/details -maxdepth 1 -type f -name '*.json' 2>/dev/null | wc -l)
read -r LISTED_COMPANIES LISTED_FINANCIAL_RECORDS <<EOF
$(python3 - <<'PY2'
import json
try:
    d=json.load(open('dist/data/listed-companies/summary.json', encoding='utf-8'))
    print(int(d.get('companies',0)), int(d.get('financialRecords',0)))
except Exception:
    print(0,0)
PY2
)
EOF
if [ "$LISTED_DETAIL_SHARDS" -ne 64 ] || [ "$LISTED_COMPANIES" -lt 3000 ] || [ "$LISTED_FINANCIAL_RECORDS" -lt 30000 ]; then
  echo "Refusing incomplete deploy: listed shards=$LISTED_DETAIL_SHARDS companies=$LISTED_COMPANIES financialRecords=$LISTED_FINANCIAL_RECORDS"
  exit 3
fi
npx wrangler pages functions build functions --outfile /tmp/datlume-pages-functions.js --output-routes-path /tmp/datlume-pages-routes.json --minify >/dev/null
FILE_COUNT=$(find dist -type f | wc -l)
MAX_SIZE=$(find dist -type f -printf '%s\n' | awk 'BEGIN{m=0} {if ($1>m) m=$1} END{print m}')
if [ "$FILE_COUNT" -gt 20000 ]; then echo "Too many files: $FILE_COUNT"; exit 1; fi
if [ "$MAX_SIZE" -gt 26214400 ]; then echo "Asset exceeds 25 MiB: $MAX_SIZE bytes"; exit 1; fi
echo "Build check OK: $FILE_COUNT files, max asset $MAX_SIZE bytes"
python3 - <<'PY'
import json, os, urllib.request, urllib.error
T=os.environ['CLOUDFLARE_API_TOKEN']
A=os.environ['CLOUDFLARE_ACCOUNT_ID']
H={'Authorization':'Bearer '+T,'Content-Type':'application/json'}
def req(url,method='GET',body=None):
    r=urllib.request.Request(url,headers=H,method=method,data=(json.dumps(body).encode() if body is not None else None))
    try:
        with urllib.request.urlopen(r,timeout=30) as x: return x.status,json.load(x)
    except urllib.error.HTTPError as e:
        try: data=json.loads(e.read().decode() or '{}')
        except: data={}
        return e.code,data
base='https://api.cloudflare.com/client/v4/accounts/'+A+'/pages/projects'
status,p=req(base+'/datlume')
if status==404:
    status,p=req(base,'POST',{'name':'datlume','production_branch':'main'})
    if status not in (200,201) or not p.get('success'):
        print('Cloudflare Pages create failed:',status,p.get('errors')); raise SystemExit(4)
    print('Created Pages project DATLUME')
elif status==200 and p.get('success'):
    print('Pages project DATLUME already exists')
else:
    print('Cloudflare Pages lookup failed:',status,p.get('errors')); raise SystemExit(5)
PY
echo 'Uploading full DATLUME build to Cloudflare Pages...'
npx wrangler pages deploy dist --project-name=datlume --branch=main --commit-dirty=true
