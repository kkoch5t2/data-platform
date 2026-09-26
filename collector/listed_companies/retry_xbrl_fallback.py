from __future__ import annotations

import argparse
import concurrent.futures
import time
from pathlib import Path

from .common import RAW, edinet_api_key
from .download_edinet_data import download_document
from .normalize_financials import choose_documents


def error_doc_ids() -> set[str]:
    path = RAW / "bulk-download-errors.txt"
    if not path.exists():
        return set()
    return {
        line.split(":", 1)[0].strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def fetch_xbrl(doc: dict, key: str, retries: int) -> tuple[str, str]:
    doc_id = doc.get("docID")
    if not doc_id or str(doc.get("xbrlFlag")) != "1":
        return "skip", doc_id or "missing-doc-id"
    path = RAW / "xbrl" / f"{doc_id}.zip"
    if path.exists() and path.stat().st_size > 0:
        return "exists", doc_id
    for attempt in range(retries + 1):
        try:
            download_document(doc_id, 1, path, key)
            return "downloaded", doc_id
        except Exception as exc:
            path.unlink(missing_ok=True)
            if attempt >= retries:
                return "error", f"{doc_id}: {type(exc).__name__}: {exc}"
            time.sleep(min(30, 2 ** attempt))
    return "error", doc_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--retries", type=int, default=3)
    args = parser.parse_args()
    wanted = error_doc_ids()
    docs = [doc for doc in choose_documents() if doc.get("docID") in wanted]
    key = edinet_api_key()
    counts = {"downloaded": 0, "exists": 0, "skip": 0, "error": 0}
    errors: list[str] = []
    print(f"fallback targets={len(docs)}", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(fetch_xbrl, doc, key, args.retries) for doc in docs]
        for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
            status, detail = future.result()
            counts[status] += 1
            if status == "error":
                errors.append(detail)
            if i % 100 == 0 or i == len(futures):
                print(f"processed={i}/{len(futures)} {counts}", flush=True)
    error_path = RAW / "xbrl-fallback-errors.txt"
    if errors:
        error_path.write_text("\n".join(errors) + "\n", encoding="utf-8")
    else:
        error_path.unlink(missing_ok=True)
    print(f"complete {counts}", flush=True)
    if errors:
        raise SystemExit(f"fallback errors={len(errors)}; see {error_path}")


if __name__ == "__main__":
    main()
