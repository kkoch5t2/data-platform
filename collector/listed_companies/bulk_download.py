from __future__ import annotations

import argparse
import concurrent.futures
import time
from pathlib import Path

from .common import RAW, edinet_api_key
from .download_edinet_data import download_document
from .normalize_financials import choose_documents


def _download(doc_id: str, kind: int, path: Path, key: str, retries: int):
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            download_document(doc_id, kind, path, key)
            return None
        except Exception as exc:
            last_error = exc
            path.unlink(missing_ok=True)
            if attempt < retries:
                time.sleep(min(30, 2 ** attempt))
    return last_error


def fetch_one(doc: dict, key: str, retries: int) -> tuple[str, str]:
    doc_id = doc.get("docID")
    if not doc_id:
        return "skip", "missing-doc-id"
    csv_path = RAW / "csv" / f"{doc_id}.zip"
    xbrl_path = RAW / "xbrl" / f"{doc_id}.zip"
    if csv_path.exists() and csv_path.stat().st_size > 0:
        return "exists", doc_id
    if xbrl_path.exists() and xbrl_path.stat().st_size > 0:
        return "xbrl", doc_id

    csv_error = None
    if str(doc.get("csvFlag")) == "1":
        csv_error = _download(doc_id, 5, csv_path, key, retries)
        if csv_error is None:
            return "downloaded", doc_id

    if str(doc.get("xbrlFlag")) == "1":
        xbrl_error = _download(doc_id, 1, xbrl_path, key, retries)
        if xbrl_error is None:
            return "xbrl", doc_id
        return "error", (
            f"{doc_id}: csv={type(csv_error).__name__ if csv_error else 'unavailable'}; "
            f"xbrl={type(xbrl_error).__name__}: {xbrl_error}"
        )

    if csv_error is not None:
        return "error", f"{doc_id}: {type(csv_error).__name__}: {csv_error}"
    return "skip", doc_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    key = edinet_api_key()
    docs = choose_documents()
    if args.limit:
        docs = docs[:args.limit]
    counts = {"downloaded": 0, "exists": 0, "xbrl": 0, "skip": 0, "error": 0}
    errors: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(fetch_one, doc, key, args.retries) for doc in docs]
        for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
            status, detail = future.result()
            counts[status] += 1
            if status == "error":
                errors.append(detail)
            if i % 250 == 0 or i == len(futures):
                print(f"processed={i}/{len(futures)} {counts}", flush=True)
    print(f"complete {counts}", flush=True)
    err_path = RAW / "bulk-download-errors.txt"
    if errors:
        err_path.write_text("\n".join(errors) + "\n", encoding="utf-8")
        raise SystemExit(f"download errors={len(errors)}; see {err_path}")
    err_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
