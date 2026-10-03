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


def direct_record_rows(conn: sqlite3.Connection, nta_conn: sqlite3.Connection) -> tuple[list[dict], dict]:
    """Only an official winner field with a number on the same source record is evidence."""
    prepare_canonical_procurements(conn)
    rows = []
    rejected = defaultdict(int)
    conflicts = {source_id for source_id, in conn.execute("""
        SELECT source_id FROM company_corporate_numbers
        GROUP BY source_id HAVING COUNT(DISTINCT corporate_number)>1
    """)}
    seen = set()
    for source_id, company_id, name, number, method, url, excerpt, amount, date, agency in conn.execute("""
        SELECT p.source_id,p.company_id,p.winner_name,l.corporate_number,l.method,
               p.source_url,p.detail_text,p.award_amount,
               COALESCE(p.award_date,p.contract_date,p.notice_date,p.bid_date),p.agency
        FROM company_corporate_numbers l
        JOIN canonical_procurements p ON p.source_id=l.source_id AND p.company_id=l.company_id
        WHERE l.method IN ('officialSource','officialSourceBackfill')
        ORDER BY p.source_id,l.corporate_number
    """):
        if source_id in conflicts:
            rejected["conflictingSourceNumbers"] += 1
            continue
        if source_id in seen:
            rejected["duplicateSourceEvidence"] += 1
            continue
        seen.add(source_id)
        nta = nta_company(nta_conn, number)
        if not nta:
            rejected["notInNta"] += 1
            continue
        normalized = normalize_company_name(name)
        registered = normalize_company_name(nta["name"])
        # Branch names can identify the numbered company; joint ventures cannot.
        branch = any(normalized == registered + suffix for suffix in ("千葉支店", "千葉営業所"))
        if "共同企業体" in (name or "") or not (normalized == registered or branch):
            rejected["nameOrJointVenture"] += 1
            continue
        if f"法人番号:{number}" not in (excerpt or ""):
            rejected["missingSourceNumber"] += 1
            continue
        if not url or not url.startswith("https://www.city.chiba.jp/"):
            rejected["unsupportedSource"] += 1
            continue
        rows.append({
            "sourceId": source_id, "companyId": company_id, "name": name,
            "corporateNumber": number, "method": method, "sourceUrl": url,
            "sourceExcerpt": excerpt, "awardAmount": amount, "date": date,
            "agency": agency,
        })
    return rows, dict(rejected)


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
            "companyIds": [], "sourceIds": [], "identityEvidence": [], "aliases": [], "awardCount": 0, "awardTotal": 0,
            "awardAmountCount": 0, "firstAwardDate": None,
            "lastAwardDate": None,
        },
    }


def merge_verified_record(entity: dict, row: dict) -> None:
    procurement = entity["procurement"]
    if row["companyId"] not in procurement["companyIds"]:
        procurement["companyIds"].append(row["companyId"])
    if row["name"] not in procurement["aliases"]:
        procurement["aliases"].append(row["name"])
    procurement["sourceIds"].append(row["sourceId"])
    procurement["identityEvidence"].append({
        "sourceId": row["sourceId"], "sourceUrl": row["sourceUrl"],
        "sourceExcerpt": row["sourceExcerpt"], "corporateNumber": row["corporateNumber"],
        "method": row["method"], "verification": "sourceWinnerFieldAndNtaName",
    })
    procurement["awardCount"] += 1
    if row["awardAmount"] is not None:
        procurement["awardTotal"] += row["awardAmount"]
        procurement["awardAmountCount"] += 1
    date = row["date"]
    if date and (not procurement["firstAwardDate"] or date < procurement["firstAwardDate"]):
        procurement["firstAwardDate"] = date
    if date and (not procurement["lastAwardDate"] or date > procurement["lastAwardDate"]):
        procurement["lastAwardDate"] = date


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
    procurement = procurement_rows(procurement_conn)
    nta_conn = sqlite3.connect(NTA_DB)
    direct_records, rejected_direct = direct_record_rows(procurement_conn, nta_conn)
    meta = nta_metadata(nta_conn)
    finance_map, finance_meta = load_finance_map()
    statements_map, statements_meta = load_statements_map()

    entities: dict[str, dict] = {}
    counters = defaultdict(int)
    direct_company_ids = {row["companyId"] for row in direct_records}
    name_group_candidates = []
    for row in procurement:
        # A name match identifies a candidate for discovery and the separate
        # name-based view; it never assigns these records to a legal entity.
        corporate_number, method = exact_name_match(nta_conn, row["name"])
        if method == "exactNormalizedName":
            name_group_candidates.append((corporate_number, row))
        if row["companyId"] in direct_company_ids:
            continue
        if method == "exactNormalizedName":
            counters["exactNameCandidates"] += 1
            entity = entities.setdefault(corporate_number, blank_entity(corporate_number))
            entity["corporateNumber"] = corporate_number
            entity["identityStatus"] = "candidate"
            entity["identityMethod"] = "exactNormalizedName"
        elif method == "ambiguousNormalizedName":
            counters["ambiguousNames"] += 1

    for row in direct_records:
        number = row["corporateNumber"]
        entity = entities.setdefault(number, blank_entity(number))
        entity["corporateNumber"] = number
        entity["identityStatus"] = "matched"
        entity["identityMethod"] = "officialWinnerRecord"
        merge_verified_record(entity, row)
    counters["directSourceMatches"] = len(direct_company_ids)
    counters["verifiedProcurementRecords"] = len(direct_records)

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
        entity["procurement"]["sourceIds"].sort()
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
    # The name-group ranking links to procurement name pages, never to a
    # corporate-number page. It is intentionally separate from verified awards.
    name_groups = [
        {key: row[key] for key in ("companyId", "name", "awardCount", "awardTotal", "awardAmountCount")}
        for number, row in name_group_candidates
        if number in public_entities and row["awardAmountCount"] > 0 and row["awardTotal"] > 0
    ]
    name_groups.sort(key=lambda row: (-row["awardTotal"], -row["awardCount"], row["name"]))
    write_json(PUBLIC / "name-groups.json", {
        "dataset": "unlisted-name-group-candidates", "generatedAt": generated_at,
        "records": name_groups[:12],
    })
    write_json(PUBLIC / "unlisted-index.json", {
        "dataset": "unlisted-companies-index", "generatedAt": generated_at,
        "ntaSourceDate": meta.get("sourceDate"), "records": unlisted_rows,
    })
    matched_procurement = counters["directSourceMatches"]
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
        "exactNameCandidates": counters["exactNameCandidates"],
        "verifiedProcurementRecords": counters["verifiedProcurementRecords"],
        "publicVerifiedProcurementRecords": sum(e["procurement"]["awardCount"] for e in public_entities.values()),
        "publicMatchedCompanyIds": len({cid for e in public_entities.values() for cid in e["procurement"]["companyIds"]}),
        "rejectedDirectEvidence": rejected_direct,
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
