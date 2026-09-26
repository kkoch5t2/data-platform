from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path

from .common import EDINET_API_BASE, RAW, edinet_api_key



def download_document(doc_id: str, kind: int, output: Path, key: str) -> None:
    params = urllib.parse.urlencode({"type": kind, "Subscription-Key": key})
    url = f"{EDINET_API_BASE}/documents/{doc_id}?{params}"
    request = urllib.request.Request(url, headers={"User-Agent": "DATLUME/1.0"})
    output.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=180) as response:
        content_type = response.headers.get("Content-Type", "")
        body = response.read()
    if "json" in content_type.lower():
        raise RuntimeError(f"EDINET returned JSON instead of archive for {doc_id}")
    output.write_bytes(body)


def load_documents() -> list[dict]:
    path = RAW / "documents-index.json"
    if not path.exists():
        raise SystemExit("documents-index.json is missing; run collect_documents first.")
    from .normalize_financials import choose_documents
    return choose_documents()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-xbrl", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--period-end-start")
    parser.add_argument("--period-end-end")
    parser.add_argument("--security-code", action="append", default=[])
    args = parser.parse_args()
    key = edinet_api_key()
    documents = load_documents()
    if args.period_end_start:
        documents = [d for d in documents if (d.get("periodEnd") or "") >= args.period_end_start]
    if args.period_end_end:
        documents = [d for d in documents if (d.get("periodEnd") or "") <= args.period_end_end]
    if args.security_code:
        master = json.loads((RAW.parent.parent.parent / "public/data/listed-companies/master.json").read_text(encoding="utf-8"))
        wanted = {x.get("edinetCode") for x in master.get("records", []) if x.get("securityCode") in set(args.security_code)}
        documents = [d for d in documents if d.get("edinetCode") in wanted]
    downloaded = 0
    for doc in documents:
        doc_id = doc.get("docID")
        if not doc_id:
            continue
        if str(doc.get("csvFlag")) == "1":
            path = RAW / "csv" / f"{doc_id}.zip"
            if not path.exists():
                download_document(doc_id, 5, path, key)
        if args.with_xbrl and str(doc.get("xbrlFlag")) == "1":
            path = RAW / "xbrl" / f"{doc_id}.zip"
            if not path.exists():
                download_document(doc_id, 1, path, key)
        downloaded += 1
        if downloaded % 100 == 0:
            print(f"processed {downloaded}/{len(documents)} documents")
        if args.limit and downloaded >= args.limit:
            break
    print(f"processed={downloaded}")


if __name__ == "__main__":
    main()
