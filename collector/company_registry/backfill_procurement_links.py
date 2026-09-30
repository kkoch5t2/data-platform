from __future__ import annotations

import re
import sqlite3
import unicodedata
from datetime import datetime, timezone

from collector.collect_jetro import DB_PATH, init_db


def corporate_number_from_detail(value: str | None) -> str | None:
    text = unicodedata.normalize("NFKC", value or "")
    match = re.search(r"法人番号\s*[:：]\s*(\d{13})", text)
    return match.group(1) if match else None


def main() -> dict:
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    conn.execute(
        "DELETE FROM company_corporate_numbers WHERE method='officialSourceBackfill'"
    )
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    invalid = 0
    rows = conn.execute(
        "SELECT source_id,company_id,detail_text FROM procurements "
        "WHERE company_id IS NOT NULL AND detail_text IS NOT NULL"
    )
    for source_id, company_id, detail_text in rows:
        corporate_number = corporate_number_from_detail(detail_text)
        if not corporate_number:
            continue
        if not re.fullmatch(r"\d{13}", corporate_number):
            invalid += 1
            continue
        conn.execute(
            "INSERT OR REPLACE INTO company_corporate_numbers "
            "(company_id,corporate_number,method,source_id,updated_at) VALUES (?,?,?,?,?)",
            (company_id, corporate_number, "officialSourceBackfill", source_id, now),
        )
        inserted += 1
    conn.commit()
    unique_links = conn.execute(
        "SELECT COUNT(*) FROM company_corporate_numbers"
    ).fetchone()[0]
    ambiguous = conn.execute(
        "SELECT COUNT(*) FROM (SELECT company_id FROM company_corporate_numbers "
        "GROUP BY company_id HAVING COUNT(DISTINCT corporate_number)>1)"
    ).fetchone()[0]
    conn.close()
    result = {
        "rowsLinked": inserted,
        "uniqueLinks": unique_links,
        "ambiguousCompanyIds": ambiguous,
        "invalid": invalid,
    }
    print(f"procurement corporate-number backfill {result}")
    return result


if __name__ == "__main__":
    main()
