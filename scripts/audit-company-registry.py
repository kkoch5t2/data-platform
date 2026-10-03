#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from collector.collect_jetro import DB_PATH, prepare_canonical_procurements
from collector.company_registry.common import NTA_DB, normalize_company_name
from collector.company_registry.build_registry import exact_name_match, listed_issuer_name_key
from collector.company_registry.gbiz_finance import GBIZ_FINANCE_DB
from collector.company_registry.gbiz_statements import GBIZ_STATEMENTS_DB
from collector.listed_companies.collect_master import load_edinet_rows

PUBLIC = ROOT / "public" / "data" / "company-registry"
LISTED = ROOT / "public" / "data" / "listed-companies" / "master.json"
EDINET_CODES = ROOT / "data" / "raw" / "listed-companies" / "edinet" / "Edinetcode.zip"
COMPANY_KINDS = {"301", "302", "303", "304", "305"}
errors: list[str] = []
checks = 0


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def check(condition: bool, message: str) -> None:
    global checks
    checks += 1
    if not condition:
        errors.append(message)


summary = load(PUBLIC / "summary.json")
index_rows = load(PUBLIC / "unlisted-index.json").get("records", [])
name_groups = load(PUBLIC / "name-groups.json").get("records", [])
index = {row["entityKey"]: row for row in index_rows}
check(len(index) == len(index_rows), "duplicate entityKey in unlisted index")
check(len(index) == summary.get("unlistedCompanies"), "summary/unlisted index count mismatch")
check(summary.get("publicEntities") == len(index), "summary publicEntities mismatch")
check(not (PUBLIC / "index.json").exists(), "obsolete full public registry index exists")

details: dict[str, dict] = {}
shards = sorted((PUBLIC / "details").glob("*.json"))
check(len(shards) == 64, f"detail shard count mismatch: {len(shards)}")
for path in shards:
    payload = load(path)
    check(payload.get("v") == 1, f"{path.name}: invalid detail version")
    for key, entity in (payload.get("c") or {}).items():
        check(key not in details, f"duplicate detail entity {key}")
        details[key] = entity
check(set(details) == set(index), "detail/unlisted index entity set mismatch")

listed_master = load(LISTED).get("records", [])
jpx_corporate_numbers = {
    str(row.get("corporateNumber")) for row in listed_master if row.get("corporateNumber")
}
unresolved_listed_names = {
    listed_issuer_name_key(row.get("name"))
    for row in listed_master if not row.get("corporateNumber")
} - {""}
_, edinet_rows = load_edinet_rows(EDINET_CODES)
edinet_listed_numbers = {
    str(row.get("提出者法人番号") or "").strip()
    for row in edinet_rows
    if row.get("上場区分") == "上場" and str(row.get("提出者法人番号") or "").strip()
}

nta = sqlite3.connect(NTA_DB)
published_source_ids: dict[str, str] = {}
published_company_ids: set[str] = set()
for key, entity in details.items():
    row = index[key]
    corporate_number = entity.get("corporateNumber")
    nta_payload = entity.get("nta") or {}
    procurement = entity.get("procurement") or {}
    check(bool(re.fullmatch(r"\d{13}", str(corporate_number or ""))), f"{key}: invalid corporate number")
    check(key == corporate_number, f"{key}: detail key/corporate number mismatch")
    check(entity.get("unlistedEligible") is True, f"{key}: published entity is not unlistedEligible")
    check(entity.get("legalStatus") == "active", f"{key}: published company is not active")
    check(str(nta_payload.get("kind") or "") in COMPANY_KINDS, f"{key}: non-company legal form")
    check(entity.get("listingStatus") == "notListedInJpxMaster", f"{key}: incompatible listing status")
    check(corporate_number not in jpx_corporate_numbers, f"{key}: JPX-listed company published as unlisted")
    check(listed_issuer_name_key(entity.get("name")) not in unresolved_listed_names,
          f"{key}: JPX issuer without corporate number published as unlisted")
    check(corporate_number not in edinet_listed_numbers, f"{key}: EDINET-listed company published as unlisted")
    check(not entity.get("listed"), f"{key}: listed payload exists on unlisted company")
    check(row.get("corporateNumber") == corporate_number, f"{key}: index/detail corporate number mismatch")
    check(row.get("name") == entity.get("name"), f"{key}: index/detail name mismatch")
    check(row.get("awardCount") == procurement.get("awardCount"), f"{key}: awardCount mismatch")
    check(row.get("awardTotal") == procurement.get("awardTotal"), f"{key}: awardTotal mismatch")
    finance = entity.get("finance")
    statements = entity.get("financialStatements")
    check(bool(finance) == bool(row.get("hasFinance")), f"{key}: finance index/detail mismatch")
    check(bool(statements) == bool(row.get("hasFinancialStatements")), f"{key}: statements index/detail mismatch")
    check(entity.get("financeSourceType") == row.get("financeSourceType"), f"{key}: finance source type mismatch")
    if finance:
        periods = finance.get("periods") or []
        check(len(periods) == int(row.get("financePeriods") or 0), f"{key}: finance period count mismatch")
        check([period.get("periodOrder") for period in periods] == list(range(len(periods))), f"{key}: finance period order mismatch")
        check(finance.get("source") in ("gBizINFO", "gBizINFO 決算情報"), f"{key}: unexpected finance source")
        meta_key = "gbizStatements" if finance.get("source") == "gBizINFO 決算情報" else "gbizFinance"
        check(finance.get("sourceDate") == (summary.get("sources") or {}).get(meta_key, {}).get("sourceDate"), f"{key}: finance source date mismatch")
        latest = periods[0] if periods else {}
        analysis = finance.get("analysis") or {}
        check(analysis.get("primaryRevenue") == latest.get("primaryRevenue"), f"{key}: primary revenue analysis mismatch")
        check(analysis.get("netIncomeLoss") == latest.get("netIncomeLoss"), f"{key}: net income analysis mismatch")
        money_fields = ("netSales","operatingRevenue1","operatingRevenue2","grossOperatingRevenue","ordinaryRevenue","netPremiums","ordinaryIncomeLoss","netIncomeLoss","capitalStock","netAssets","totalAssets")
        for period in periods:
            for field in money_fields:
                if period.get(field) is not None:
                    check(period.get(field + "Unit") == "JPY", f"{key}: {field} unexpected unit")
            if period.get("employees") is not None:
                check(period.get("employeesUnit") == "pure", f"{key}: employees unexpected unit")
    source = nta.execute(
        "SELECT name,kind,close_date FROM corporations WHERE corporate_number=?", (corporate_number,)
    ).fetchone()
    check(source is not None, f"{key}: company missing from NTA source DB")
    if source:
        check(source[0] == nta_payload.get("name"), f"{key}: NTA name differs from source")
        check(str(source[1] or "") in COMPANY_KINDS, f"{key}: source kind is not a company")
        check(not source[2], f"{key}: source corporation is closed")
    source_ids = procurement.get("sourceIds") or []
    evidence = procurement.get("identityEvidence") or []
    check(len(source_ids) == len(set(source_ids)) == procurement.get("awardCount"), f"{key}: verified record count mismatch")
    check({item.get("sourceId") for item in evidence} == set(source_ids), f"{key}: evidence/source IDs mismatch")
    for item in evidence:
        check(item.get("corporateNumber") == key, f"{key}: evidence corporate number mismatch")
        check(item.get("verification") == "sourceWinnerFieldAndNtaName", f"{key}: evidence not verified")
        check(str(item.get("sourceUrl") or "").startswith("https://www.city.chiba.jp/"), f"{key}: invalid evidence URL")
    for source_id in source_ids:
        check(source_id not in published_source_ids, f"{key}: source record assigned twice: {source_id}")
        published_source_ids[source_id] = key
    for company_id in procurement.get("companyIds") or []:
        check(bool(re.fullmatch(r"co_[0-9a-f]{12}", company_id)), f"{key}: invalid procurement companyId {company_id}")
        published_company_ids.add(company_id)
proc = sqlite3.connect(DB_PATH)
prepare_canonical_procurements(proc)
proc.execute("CREATE TEMP TABLE published_sources(source_id TEXT PRIMARY KEY, corporate_number TEXT NOT NULL)")
proc.executemany(
    "INSERT INTO published_sources(source_id,corporate_number) VALUES (?,?)",
    sorted(published_source_ids.items()),
)
source_count, source_total, source_ids = proc.execute("""
  SELECT COUNT(*),COALESCE(SUM(p.award_amount),0),COUNT(DISTINCT p.company_id)
  FROM canonical_procurements p
  JOIN published_sources i ON i.source_id=p.source_id
""").fetchone()
for source_id, number, actual_number, company_id, winner_name, detail, url in proc.execute("""
  SELECT p.source_id,i.corporate_number,l.corporate_number,p.company_id,
         p.winner_name,p.detail_text,p.source_url
  FROM published_sources i
  JOIN canonical_procurements p ON p.source_id=i.source_id
  LEFT JOIN company_corporate_numbers l
    ON l.source_id=p.source_id AND l.company_id=p.company_id AND l.corporate_number=i.corporate_number
"""):
    check(actual_number == number, f"{source_id}: no same-record corporate-number link")
    check(bool(winner_name) and bool(detail) and bool(url), f"{source_id}: missing official record evidence")
    nta_name = nta.execute("SELECT name FROM corporations WHERE corporate_number=?", (number,)).fetchone()
    normalized = normalize_company_name(winner_name)
    registered = normalize_company_name(nta_name[0]) if nta_name else ""
    check(bool(nta_name) and (normalized == registered or any(
        normalized == registered + suffix for suffix in ("千葉支店", "千葉営業所")
    )) and "共同企業体" not in (winner_name or ""), f"{source_id}: source winner/NTA name mismatch")
    check(f"法人番号:{number}" in (detail or ""), f"{source_id}: number missing from source excerpt")
    check(str(url or "").startswith("https://www.city.chiba.jp/"), f"{source_id}: unsupported official source")
check(len(name_groups) == 12, "name-based ranking must contain 12 candidates")
check(len({row.get("companyId") for row in name_groups}) == len(name_groups), "duplicate name-group ID")
check(name_groups == sorted(name_groups, key=lambda row: (-row["awardTotal"], -row["awardCount"], row["name"])),
      "name-based ranking not sorted by award amount")
for group in name_groups:
    company_id, name = group.get("companyId"), group.get("name")
    check(bool(re.fullmatch(r"co_[0-9a-f]{12}", company_id or "")), f"invalid name-group ID: {company_id}")
    check("corporateNumber" not in group and "entityKey" not in group, f"{company_id}: legal ID leaked into name-only ranking")
    corporate_number, method = exact_name_match(nta, name)
    check(method == "exactNormalizedName" and corporate_number in index,
          f"{company_id}: no unique active unlisted name candidate")
    source = proc.execute("""
        SELECT c.company_name,COUNT(*),COALESCE(SUM(p.award_amount),0),
               SUM(CASE WHEN p.award_amount IS NOT NULL THEN 1 ELSE 0 END)
        FROM companies c JOIN canonical_procurements p ON p.company_id=c.company_id
        WHERE c.company_id=? GROUP BY c.company_id
    """, (company_id,)).fetchone()
    check(source == (name, group.get("awardCount"), group.get("awardTotal"), group.get("awardAmountCount")),
          f"{company_id}: name-group totals differ from source")
check(any(row.get("name") == "アクセンチュア株式会社" for row in name_groups),
      "Accenture name group missing from unlisted name-based ranking")
check(any("NTTデータ" in unicodedata.normalize("NFKC", row.get("name", "")) for row in name_groups),
      "NTT Data name group missing from unlisted name-based ranking")
all_source_companies = proc.execute(
    "SELECT COUNT(DISTINCT company_id) FROM canonical_procurements WHERE company_id IS NOT NULL"
).fetchone()[0]
proc.close()
nta.close()

published_count = sum((entity.get("procurement") or {}).get("awardCount", 0) for entity in details.values())
published_total = sum((entity.get("procurement") or {}).get("awardTotal", 0) for entity in details.values())
check(published_count == source_count, "published/source procurement count mismatch")
check(published_total == source_total, "published/source procurement award total mismatch")
check(source_ids == len(published_company_ids), "published procurement companyId coverage mismatch")
check(summary.get("publicVerifiedProcurementRecords") == source_count, "summary verified record count mismatch")
check(summary.get("publicMatchedCompanyIds") == source_ids, "summary matched company IDs mismatch")
check(summary.get("exactNameCandidates", 0) + summary.get("ambiguousNames", 0) + summary.get("procurementMatched", 0) <= all_source_companies, "candidate groups exceed source")
check(summary.get("procurementCompanies") == all_source_companies, "summary/source procurement company count mismatch")
check(summary.get("unlistedCompanies") == len(details), "summary/detail unlisted count mismatch")
check(summary.get("publicEntities") == len(details), "summary/detail public entity count mismatch")
finance_index_count = sum(1 for row in index_rows if row.get("hasFinance"))
statement_index_count = sum(1 for row in index_rows if row.get("hasFinancialStatements"))
check(summary.get("unlistedFinanceCompanies") == finance_index_count, "summary/index finance company count mismatch")
check(summary.get("unlistedStatementCompanies") == statement_index_count, "summary/index statement company count mismatch")
if GBIZ_FINANCE_DB.exists():
    gbiz = sqlite3.connect(GBIZ_FINANCE_DB)
    source_finance_numbers = {row[0] for row in gbiz.execute("SELECT DISTINCT corporate_number FROM finance_records")}
    gbiz_meta = dict(gbiz.execute("SELECT key,value FROM metadata"))
    gbiz.close()
    published_finance_numbers = {key for key, entity in details.items() if entity.get("financeSourceType") == "finance"}
    check(published_finance_numbers == (source_finance_numbers & set(details)), "gBizINFO source/public finance CSV company set mismatch")
    check(gbiz_meta.get("sourceDate") == (summary.get("sources") or {}).get("gbizFinance", {}).get("sourceDate"), "summary/gBizINFO source date mismatch")

if GBIZ_STATEMENTS_DB.exists():
    gbiz = sqlite3.connect(GBIZ_STATEMENTS_DB)
    source_statement_numbers = {row[0] for row in gbiz.execute("SELECT DISTINCT corporate_number FROM statements")}
    statement_meta = dict(gbiz.execute("SELECT key,value FROM metadata"))
    gbiz.close()
    published_statement_numbers = {key for key, entity in details.items() if entity.get("financialStatements")}
    check(published_statement_numbers == (source_statement_numbers & set(details)), "gBizINFO source/public statement company set mismatch")
    check(statement_meta.get("sourceDate") == (summary.get("sources") or {}).get("gbizStatements", {}).get("sourceDate"), "summary/gBizINFO statements source date mismatch")
    statement_only = sum(1 for entity in details.values() if entity.get("financeSourceType") == "statements")
    check(summary.get("unlistedStatementOnlyCompanies") == statement_only, "summary statement-only company count mismatch")

nta = sqlite3.connect(NTA_DB)
nta_meta = dict(nta.execute("SELECT key,value FROM metadata"))
nta.close()
check(int(nta_meta.get("corporations", 0)) == int((summary.get("sources") or {}).get("nta", {}).get("corporations", 0)), "summary/NTA corporation count mismatch")
check(nta_meta.get("sourceDate") == (summary.get("sources") or {}).get("nta", {}).get("sourceDate"), "summary/NTA source date mismatch")

print(f"company registry audit: {checks} checks, {len(errors)} failures")
for error in errors[:100]:
    print("ERROR", error)
if len(errors) > 100:
    print(f"... and {len(errors) - 100} more")
if errors:
    raise AssertionError("company registry audit failed")
