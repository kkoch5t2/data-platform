from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from collector.collect_jetro import DB_PATH, init_db, prepare_canonical_procurements
from collector.listed_companies.collect_master import load_edinet_rows
from .common import NTA_DB, PUBLIC, ROOT, normalize_company_name, write_json
from .gbiz_finance import load_finance_map
from .gbiz_statements import load_statements_map

LISTED_MASTER = ROOT / "public" / "data" / "listed-companies" / "master.json"
EDINET_CODE_ZIP = ROOT / "data" / "raw" / "listed-companies" / "edinet" / "Edinetcode.zip"
COMPANY_KINDS = {"301", "302", "303", "304", "305"}
DETAIL_SHARDS = 64


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def detail_bucket(key: str) -> str:
    value = int(hashlib.sha1(key.encode("utf-8")).hexdigest()[:8], 16)
    return f"{value % DETAIL_SHARDS:02x}"


def edinet_listed_corporate_numbers() -> set[str]:
    if not EDINET_CODE_ZIP.exists():
        return set()
    _, rows = load_edinet_rows(EDINET_CODE_ZIP)
    return {
        str(row.get("提出者法人番号") or "").strip()
        for row in rows
        if row.get("上場区分") == "上場" and str(row.get("提出者法人番号") or "").strip()
    }


def nta_metadata(conn: sqlite3.Connection) -> dict[str, str]:
    return dict(conn.execute("SELECT key,value FROM metadata"))


def nta_company(conn: sqlite3.Connection, corporate_number: str) -> dict | None:
    row = conn.execute(
        "SELECT corporate_number,name,kind,prefecture_name,city_name,street_number,"
        "post_code,close_date,close_cause,successor_corporate_number,assignment_date,"
        "en_name,en_prefecture_name,en_address,furigana,hihyoji,update_date,change_date "
        "FROM corporations WHERE corporate_number=?", (corporate_number,)
    ).fetchone()
    if not row:
        return None
    keys = (
        "corporateNumber", "name", "kind", "prefecture", "city", "street",
        "postCode", "closeDate", "closeCause", "successorCorporateNumber",
        "assignmentDate", "nameEn", "prefectureEn", "addressEn", "furigana",
        "hidden", "updateDate", "changeDate",
    )
    return dict(zip(keys, row))


def exact_name_match(conn: sqlite3.Connection, name: str) -> tuple[str | None, str | None]:
    normalized = normalize_company_name(name)
    if not normalized:
        return None, None
    rows = conn.execute(
        "SELECT corporate_number,close_date FROM corporations "
        "WHERE normalized_name=? AND latest=1 LIMIT 3", (normalized,)
    ).fetchall()
    if len(rows) == 1:
        return rows[0][0], "exactNormalizedName"
    return None, "ambiguousNormalizedName" if len(rows) > 1 else None


def load_direct_links(conn: sqlite3.Connection) -> dict[str, list[str]]:
    links: dict[str, set[str]] = defaultdict(set)
    for company_id, corporate_number in conn.execute(
        "SELECT company_id,corporate_number FROM company_corporate_numbers"
    ):
        links[company_id].add(corporate_number)
    return {key: sorted(values) for key, values in links.items()}


def procurement_rows(conn: sqlite3.Connection) -> list[dict]:
    prepare_canonical_procurements(conn)
    rows = conn.execute("""
      SELECT c.company_id,c.company_name,
             COUNT(p.source_id),COALESCE(SUM(p.award_amount),0),
             SUM(CASE WHEN p.award_amount IS NOT NULL THEN 1 ELSE 0 END),
             MIN(COALESCE(p.award_date,p.contract_date,p.notice_date,p.bid_date)),
             MAX(COALESCE(p.award_date,p.contract_date,p.notice_date,p.bid_date)),
             COUNT(DISTINCT p.agency)
      FROM companies c
      JOIN canonical_procurements p ON p.company_id=c.company_id
      GROUP BY c.company_id,c.company_name
      ORDER BY c.company_id
    """).fetchall()
    return [{
        "companyId": row[0], "name": row[1], "awardCount": row[2],
        "awardTotal": row[3], "awardAmountCount": row[4],
        "firstAwardDate": row[5], "lastAwardDate": row[6], "agencyCount": row[7],
    } for row in rows]


def blank_entity(key: str) -> dict:
    return {
        "entityKey": key, "corporateNumber": None, "name": None,
        "identityMethod": None, "identityStatus": "unmatched",
        "nta": None, "listed": None,
        "procurement": {
            "companyIds": [], "aliases": [], "awardCount": 0, "awardTotal": 0,
            "awardAmountCount": 0, "firstAwardDate": None,
            "lastAwardDate": None,
        },
    }


def merge_procurement(entity: dict, row: dict) -> None:
    procurement = entity["procurement"]
    procurement["companyIds"].append(row["companyId"])
    if row["name"] not in procurement["aliases"]:
        procurement["aliases"].append(row["name"])
    procurement["awardCount"] += row["awardCount"]
    procurement["awardTotal"] += row["awardTotal"]
    procurement["awardAmountCount"] += row["awardAmountCount"]
    first = row["firstAwardDate"]
    last = row["lastAwardDate"]
    if first and (not procurement["firstAwardDate"] or first < procurement["firstAwardDate"]):
        procurement["firstAwardDate"] = first
    if last and (not procurement["lastAwardDate"] or last > procurement["lastAwardDate"]):
        procurement["lastAwardDate"] = last


def compact_row(entity: dict) -> dict:
    procurement = entity["procurement"]
    listed = entity.get("listed") or {}
    nta = entity.get("nta") or {}
    return {
        "entityKey": entity["entityKey"],
        "corporateNumber": entity.get("corporateNumber"),
        "name": entity.get("name"),
        "prefecture": nta.get("prefecture"),
        "city": nta.get("city"),
        "listingStatus": entity["listingStatus"],
        "identityStatus": entity["identityStatus"],
        "securityCode": listed.get("securityCode"),
        "market": listed.get("market"),
        "industry33": listed.get("industry33"),
        "awardCount": procurement["awardCount"],
        "awardTotal": procurement["awardTotal"],
        "hasFinance": bool(entity.get("finance")),
        "financeSourceType": entity.get("financeSourceType"),
        "hasFinancialStatements": bool(entity.get("financialStatements")),
        "financePeriods": len((entity.get("finance") or {}).get("periods", [])),
        "latestRevenue": ((entity.get("finance") or {}).get("analysis") or {}).get("primaryRevenue"),
        "latestRevenueLabel": ((entity.get("finance") or {}).get("analysis") or {}).get("primaryRevenueLabel"),
        "latestNetIncome": ((entity.get("finance") or {}).get("analysis") or {}).get("netIncomeLoss"),
        "detailBucket": detail_bucket(entity["entityKey"]),
    }


def main() -> dict:
    if not NTA_DB.exists():
        raise SystemExit(f"NTA registry is missing: {NTA_DB}")
    listed_payload = load_json(LISTED_MASTER, {"records": [], "counts": {}})
    listed_rows = listed_payload.get("records", [])
    edinet_listed = edinet_listed_corporate_numbers()
    listed_by_corp = {
        str(row.get("corporateNumber")): row
        for row in listed_rows if str(row.get("corporateNumber") or "").isdigit()
    }

    procurement_conn = sqlite3.connect(DB_PATH)
    init_db(procurement_conn)
    direct_links = load_direct_links(procurement_conn)
    procurement = procurement_rows(procurement_conn)
    nta_conn = sqlite3.connect(NTA_DB)
    meta = nta_metadata(nta_conn)
    finance_map, finance_meta = load_finance_map()
    statements_map, statements_meta = load_statements_map()

    entities: dict[str, dict] = {}
    counters = defaultdict(int)
    for row in procurement:
        direct = direct_links.get(row["companyId"], [])
        corporate_number = None
        method = None
        if len(direct) == 1:
            corporate_number, method = direct[0], "officialSource"
            counters["directSourceMatches"] += 1
        elif len(direct) > 1:
            counters["ambiguousDirect"] += 1
        else:
            corporate_number, method = exact_name_match(nta_conn, row["name"])
            if method == "exactNormalizedName":
                counters["exactNameMatches"] += 1
            elif method == "ambiguousNormalizedName":
                counters["ambiguousNames"] += 1
        key = corporate_number or f"proc:{row['companyId']}"
        entity = entities.setdefault(key, blank_entity(key))
        if corporate_number:
            entity["corporateNumber"] = corporate_number
            entity["identityStatus"] = "matched"
            entity["identityMethod"] = method
        elif len(direct) > 1:
            entity["identityStatus"] = "ambiguous"
            entity["identityMethod"] = "conflictingOfficialNumbers"
            entity["corporateNumberCandidates"] = direct
        elif method == "ambiguousNormalizedName":
            entity["identityStatus"] = "ambiguous"
            entity["identityMethod"] = method
        merge_procurement(entity, row)

    for listed in listed_rows:
        corporate_number = str(listed.get("corporateNumber") or "").strip() or None
        key = corporate_number or f"listed:{listed['securityCode']}"
        entity = entities.setdefault(key, blank_entity(key))
        if corporate_number:
            entity["corporateNumber"] = corporate_number
            if entity["identityStatus"] == "unmatched":
                entity["identityStatus"] = "matched"
                entity["identityMethod"] = "edinetCorporateNumber"
        entity["listed"] = {
            "securityCode": listed.get("securityCode"),
            "name": listed.get("name"), "market": listed.get("market"),
            "industry33": listed.get("industry33"), "edinetCode": listed.get("edinetCode"),
        }

    listing_counts = defaultdict(int)
    corporate_entities = 0
    for entity in entities.values():
        corporate_number = entity.get("corporateNumber")
        if corporate_number:
            corporate_entities += 1
            entity["nta"] = nta_company(nta_conn, corporate_number)
        nta = entity.get("nta") or {}
        listed = entity.get("listed") or {}
        aliases = entity["procurement"]["aliases"]
        entity["name"] = nta.get("name") or listed.get("name") or (aliases[0] if aliases else None)
        if entity.get("listed"):
            entity["listingStatus"] = "listed"
        elif corporate_number in edinet_listed:
            entity["listingStatus"] = "listedElsewhere"
        elif corporate_number and entity.get("nta"):
            entity["listingStatus"] = "notListedInJpxMaster"
        else:
            entity["listingStatus"] = "unknown"
        entity["legalStatus"] = (
            "closed" if nta.get("closeDate") else ("active" if entity.get("nta") else "unknown")
        )
        entity["unlistedEligible"] = bool(
            corporate_number and entity["listingStatus"] == "notListedInJpxMaster"
            and entity["legalStatus"] == "active" and str(nta.get("kind") or "") in COMPANY_KINDS
        )
        csv_finance = finance_map.get(corporate_number) if entity["unlistedEligible"] else None
        statement_finance = statements_map.get(corporate_number) if entity["unlistedEligible"] else None
        entity["financialStatements"] = statement_finance
        entity["finance"] = csv_finance or statement_finance
        entity["financeSourceType"] = "finance" if csv_finance else ("statements" if statement_finance else None)
        entity["procurement"]["companyIds"].sort()
        entity["procurement"]["aliases"].sort()
        listing_counts[entity["listingStatus"]] += 1

    details_dir = PUBLIC / "details"
    details_dir.mkdir(parents=True, exist_ok=True)
    for old in details_dir.glob("*.json"):
        old.unlink()
    # Public shards contain only verified unlisted companies. The full registry remains
    # reconstructible from the local NTA SQLite + procurement DB and is not shipped to browsers.
    public_entities = {key: entity for key, entity in entities.items() if entity.get("unlistedEligible")}
    shards: dict[str, dict[str, dict]] = defaultdict(dict)
    for key, entity in sorted(public_entities.items()):
        shards[detail_bucket(key)][key] = entity
    for number in range(DETAIL_SHARDS):
        bucket = f"{number:02x}"
        write_json(details_dir / f"{bucket}.json", {"v": 1, "c": shards.get(bucket, {})})

    obsolete_index = PUBLIC / "index.json"
    obsolete_index.unlink(missing_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()
    unlisted_rows = [compact_row(entity) for entity in public_entities.values()]
    unlisted_rows.sort(key=lambda row: (-row["awardTotal"], -row["awardCount"], row["name"] or ""))
    write_json(PUBLIC / "unlisted-index.json", {
        "dataset": "unlisted-companies-index", "generatedAt": generated_at,
        "ntaSourceDate": meta.get("sourceDate"), "records": unlisted_rows,
    })
    matched_procurement = counters["directSourceMatches"] + counters["exactNameMatches"]
    finance_public_count = sum(1 for entity in public_entities.values() if entity.get("finance"))
    finance_csv_public_count = sum(1 for entity in public_entities.values() if entity.get("financeSourceType") == "finance")
    statements_public_count = sum(1 for entity in public_entities.values() if entity.get("financialStatements"))
    statements_only_count = sum(1 for entity in public_entities.values() if entity.get("financeSourceType") == "statements")
    summary = {
        "dataset": "company-registry-summary", "generatedAt": generated_at,
        "entities": len(entities), "corporateNumberEntities": corporate_entities,
        "procurementCompanies": len(procurement),
        "procurementMatched": matched_procurement,
        "procurementUnmatched": len(procurement) - matched_procurement,
        "directSourceMatches": counters["directSourceMatches"],
        "exactNameMatches": counters["exactNameMatches"],
        "ambiguousOfficialNumbers": counters["ambiguousDirect"],
        "ambiguousNames": counters["ambiguousNames"],
        "listedCompanies": len(listed_rows),
        "edinetListedCorporateNumbers": len(edinet_listed),
        "unlistedCompanies": len(unlisted_rows),
        "unlistedFinanceCompanies": finance_public_count,
        "unlistedFinanceCsvCompanies": finance_csv_public_count,
        "unlistedStatementCompanies": statements_public_count,
        "unlistedStatementOnlyCompanies": statements_only_count,
        "publicEntities": len(public_entities),
        "listingStatus": dict(sorted(listing_counts.items())),
        "detailShards": DETAIL_SHARDS,
        "sources": {
            "nta": {"url": meta.get("source"), "sourceDate": meta.get("sourceDate"),
                    "region": meta.get("region"), "corporations": int(meta.get("corporations", 0))},
            "listedMasterSourceDate": listed_payload.get("sourceDate"),
            "procurementDatabase": "DATLUME canonical procurements",
            "gbizFinance": {"sourceDate": finance_meta.get("sourceDate") or None,
                            "sourceUrl": finance_meta.get("sourceUrl") or None,
                            "snapshotStatus": "legacy" if "20251204" in (finance_meta.get("sourceFile") or "") else ("current" if finance_meta else None),
                            "companies": int(finance_meta.get("companies", 0) or 0)},
            "gbizStatements": {"sourceDate": statements_meta.get("sourceDate") or None,
                               "sourceUrl": statements_meta.get("sourceUrl") or None,
                               "snapshotStatus": "current" if statements_meta else None,
                               "companies": int(statements_meta.get("companies", 0) or 0),
                               "rows": int(statements_meta.get("rows", 0) or 0)},
        },
    }
    write_json(PUBLIC / "summary.json", summary)
    procurement_conn.close()
    nta_conn.close()
    print(f"company registry {summary}")
    return summary


if __name__ == "__main__":
    main()
