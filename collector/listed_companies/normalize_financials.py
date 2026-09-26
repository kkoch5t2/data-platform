from __future__ import annotations

import csv
import io
import json
import math
import re
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .common import PUBLIC, RAW, write_json

METRICS = {
    "revenue": {
        "period": "duration",
        "concepts": ["NetSales", "Revenue", "OperatingRevenue"],
        "labels": ["売上高", "営業収益", "収益"],
    },
    "operatingIncome": {
        "period": "duration",
        "concepts": ["OperatingIncome", "OperatingProfitLoss"],
        "labels": ["営業利益", "営業利益又は営業損失（△）"],
    },
    "ordinaryIncome": {
        "period": "duration",
        "concepts": ["OrdinaryIncome", "OrdinaryIncomeLoss"],
        "labels": ["経常利益", "経常利益又は経常損失（△）"],
    },
    "netIncome": {
        "period": "duration",
        "concepts": ["ProfitLossAttributableToOwnersOfParent", "ProfitLoss"],
        "labels": ["親会社株主に帰属する当期純利益", "当期純利益"],
    },
}
METRICS.update({
    "assets": {
        "period": "instant", "concepts": ["Assets"], "labels": ["資産合計", "総資産額"]
    },
    "liabilities": {
        "period": "instant", "concepts": ["Liabilities"], "labels": ["負債合計"]
    },
    "equity": {
        "period": "instant",
        "concepts": ["NetAssets", "Equity", "EquityAttributableToOwnersOfParent"],
        "labels": ["純資産合計", "資本合計", "親会社の所有者に帰属する持分合計"],
    },
    "cash": {
        "period": "instant",
        "concepts": ["CashAndDeposits", "CashAndCashEquivalents"],
        "labels": ["現金及び預金", "現金及び現金同等物"],
    },
    "operatingCashFlow": {
        "period": "duration",
        "concepts": ["NetCashProvidedByUsedInOperatingActivities", "CashFlowsFromUsedInOperatingActivities"],
        "labels": ["営業活動によるキャッシュ・フロー"],
    },
    "investingCashFlow": {
        "period": "duration",
        "concepts": ["NetCashProvidedByUsedInInvestmentActivities", "CashFlowsFromUsedInInvestingActivities"],
        "labels": ["投資活動によるキャッシュ・フロー"],
    },
    "financingCashFlow": {
        "period": "duration",
        "concepts": ["NetCashProvidedByUsedInFinancingActivities", "CashFlowsFromUsedInFinancingActivities"],
        "labels": ["財務活動によるキャッシュ・フロー"],
    },
})
METRICS.update({
    "employees": {
        "period": "instant", "concepts": ["NumberOfEmployees"], "labels": ["従業員数"]
    },
    "averageAge": {
        "period": "instant", "concepts": ["AverageAgeYears"], "labels": ["平均年齢（歳）", "平均年齢"]
    },
    "averageTenure": {
        "period": "instant",
        "concepts": ["AverageLengthOfServiceYears"],
        "labels": ["平均勤続年数（年）", "平均勤続年数"],
    },
    "averageSalary": {
        "period": "instant", "concepts": ["AverageAnnualSalary"], "labels": ["平均年間給与"]
    },
    "sharesOutstanding": {
        "period": "instant",
        "concepts": ["TotalNumberOfIssuedSharesSummaryOfBusinessResults", "NumberOfIssuedSharesAsOfFiscalYearEndIssuedSharesTotal"],
        "labels": ["発行済株式総数", "発行済株式数"],
    },
})

# EDINET IFRS filings often use IFRS taxonomy or filer-extension concepts and
# mark consolidated rows as "その他" rather than literally "連結".
# Keep accounting-standard-specific aliases separate so individual J-GAAP facts
# are never preferred merely because their local concept is familiar.
METRICS["profitBeforeTax"] = {
    "period": "duration",
    "concepts": ["IncomeBeforeIncomeTaxes"],
    "labels": ["税引前当期純利益", "税金等調整前当期純利益"],
}
METRICS["parentEquity"] = {
    "period": "instant",
    "concepts": ["EquityAttributableToOwnersOfParent"],
    "labels": ["親会社の所有者に帰属する持分"],
}
METRICS["reportedRoe"] = {"period": "duration", "concepts": ["RateOfReturnOnEquitySummaryOfBusinessResults"], "labels": ["自己資本利益率、経営指標等"]}
METRICS["reportedEquityRatio"] = {"period": "instant", "concepts": ["EquityToAssetRatioSummaryOfBusinessResults"], "labels": ["自己資本比率、経営指標等"]}
METRICS["ordinaryRevenue"] = {"period": "duration", "concepts": ["OrdinaryIncomeSummaryOfBusinessResults", "OrdinaryIncomeBNK"], "labels": ["経常収益、経営指標等", "経常収益、銀行業"]}
METRICS["insuranceRevenue"] = {"period": "duration", "concepts": ["InsuranceRevenueIFRSKeyFinancialData", "InsuranceRevenueIFRS"], "labels": ["保険収益（IFRS）"]}
COMMON_CONCEPT_ALIASES = {
    "revenue": ["NetSalesSummaryOfBusinessResults", "OperatingRevenue1", "OperatingRevenue2", "OperatingRevenueSummaryOfBusinessResults"],
    "averageAge": ["AverageAgeYearsInformationAboutReportingCompanyInformationAboutEmployees"],
    "averageTenure": ["AverageLengthOfServiceYearsInformationAboutReportingCompanyInformationAboutEmployees"],
    "averageSalary": ["AverageAnnualSalaryInformationAboutReportingCompanyInformationAboutEmployees"],
    "operatingCashFlow": ["NetCashProvidedByUsedInOperatingActivitiesSummaryOfBusinessResults"],
    "investingCashFlow": ["NetCashProvidedByUsedInInvestingActivitiesSummaryOfBusinessResults"],
    "financingCashFlow": ["NetCashProvidedByUsedInFinancingActivitiesSummaryOfBusinessResults"],
}
for _metric, _aliases in COMMON_CONCEPT_ALIASES.items():
    METRICS[_metric]["concepts"] = _aliases + METRICS[_metric]["concepts"]

IFRS_METRICS = {
    "revenue": {"concepts": ["RevenueIFRS", "RevenueIFRSSummaryOfBusinessResults", "NetSalesIFRS", "NetSalesIFRSSummaryOfBusinessResults", "OperatingRevenuesIFRSKeyFinancialData", "TotalNetRevenuesIFRS", "SalesRevenuesIFRS"], "labels": ["売上収益（IFRS）", "売上高（IFRS）"]},
    "operatingIncome": {"concepts": ["OperatingProfitLossIFRS", "OperatingProfitLossIFRSSummaryOfBusinessResults"], "labels": ["営業利益（△損失）（IFRS）"]},
    "ordinaryIncome": None,
    "profitBeforeTax": {"concepts": ["ProfitLossBeforeTaxIFRS", "ProfitLossBeforeTaxIFRSSummaryOfBusinessResults"], "labels": ["継続事業からの税引前利益（△損失）（IFRS）"]},
    "netIncome": {"concepts": ["ProfitLossAttributableToOwnersOfParentIFRS", "ProfitLossAttributableToOwnersOfParentIFRSSummaryOfBusinessResults", "ProfitLossIFRS", "ProfitLossIFRSSummaryOfBusinessResults"], "labels": ["親会社の所有者、当期利益（△損失）（IFRS）", "当期利益（△損失）（IFRS）"]},
    "assets": {"concepts": ["AssetsIFRS", "AssetsIFRSSummaryOfBusinessResults"], "labels": ["資産（IFRS）"]},
    "liabilities": {"concepts": ["LiabilitiesIFRS"], "labels": ["負債（IFRS）"]},
    "equity": {"concepts": ["EquityIFRS"], "labels": ["資本（IFRS）"]},
    "parentEquity": {"concepts": ["EquityAttributableToOwnersOfParentIFRS"], "labels": ["親会社の所有者に帰属する持分（IFRS）"]},
    "reportedRoe": {"concepts": ["RateOfReturnOnEquityIFRSSummaryOfBusinessResults"], "labels": ["親会社所有者帰属持分利益率（IFRS）、経営指標等"]},
    "reportedEquityRatio": None,
    "cash": {"concepts": ["CashAndCashEquivalentsIFRS", "CashAndCashEquivalentsIFRSSummaryOfBusinessResults"], "labels": ["現金及び現金同等物（IFRS）"]},
    "operatingCashFlow": {"concepts": ["CashFlowsFromUsedInOperatingActivitiesIFRS", "CashFlowsFromUsedInOperatingActivitiesIFRSSummaryOfBusinessResults"], "labels": ["営業活動によるキャッシュ・フロー（IFRS）、経営指標等"]},
    "investingCashFlow": {"concepts": ["CashFlowsFromUsedInInvestingActivitiesIFRS", "CashFlowsFromUsedInInvestingActivitiesIFRSSummaryOfBusinessResults"], "labels": ["投資活動によるキャッシュ・フロー（IFRS）、経営指標等"]},
    "financingCashFlow": {"concepts": ["CashFlowsFromUsedInFinancingActivitiesIFRS", "CashFlowsFromUsedInFinancingActivitiesIFRSSummaryOfBusinessResults"], "labels": ["財務活動によるキャッシュ・フロー（IFRS）、経営指標等"]},
}

HEADER_ALIASES = {
    "concept": ("要素ID", "要素ＩＤ"),
    "label": ("項目名",),
    "context": ("コンテキストID", "コンテキストＩＤ"),
    "relativeYear": ("相対年度",),
    "consolidation": ("連結・個別",),
    "periodType": ("期間・時点",),
    "unit": ("単位",),
    "value": ("値",),
}


def _header_value(row: dict[str, str], key: str) -> str:
    for name in HEADER_ALIASES[key]:
        if name in row:
            return (row.get(name) or "").strip()
    return ""


def read_fact_rows(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        for name in names:
            raw = archive.read(name)
            try:
                text = raw.decode("utf-16")
            except UnicodeError:
                text = raw.decode("utf-16le")
            reader = csv.DictReader(io.StringIO(text), delimiter="\t")
            for source in reader:
                rows.append({
                    "concept": _header_value(source, "concept"),
                    "label": _header_value(source, "label"),
                    "context": _header_value(source, "context"),
                    "relativeYear": _header_value(source, "relativeYear"),
                    "consolidation": _header_value(source, "consolidation"),
                    "periodType": _header_value(source, "periodType"),
                    "unit": _header_value(source, "unit"),
                    "value": _header_value(source, "value"),
                    "sourceFile": name,
                })
    return rows


def local_concept(concept: str) -> str:
    return concept.rsplit(":", 1)[-1]

def parse_number(value: str):
    text = (value or "").strip().replace(",", "")
    if not text or text in {"-", "―", "－", "—", "nan", "NaN"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    text = text.replace("△", "-").replace("▲", "-")
    try:
        number = float(text)
    except ValueError:
        return None
    if negative:
        number = -number
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else number


def is_current_context(row: dict[str, str], period: str) -> bool:
    relative = row["relativeYear"]
    context = row["context"]
    period_type = row["periodType"]
    if relative and not any(word in relative for word in ("当期", "当年度", "当事業年度", "当連結会計年度")):
        if "CurrentYear" not in context:
            return False
    if period == "duration" and period_type and "期間" not in period_type:
        return False
    if period == "instant" and period_type and "時点" not in period_type:
        return False
    lowered = context.lower()
    if "prior" in lowered:
        return False
    # Company-level KPIs must not use segment/component dimensions.
    # NonConsolidatedMember is the one allowed dimension for standalone facts.
    remaining_members = lowered.replace("nonconsolidatedmember", "")
    if "member" in remaining_members:
        return False
    return True

def metric_spec(metric: str, base_spec: dict, standard: str | None) -> dict | None:
    if standard and "IFRS" in standard.upper() and metric in IFRS_METRICS:
        override = IFRS_METRICS[metric]
        if override is None:
            return None
        return {"period": base_spec["period"], **override}
    return base_spec


def row_score(row: dict[str, str], spec: dict, prefer_consolidated: bool) -> int:
    local = local_concept(row["concept"])
    if local in spec["concepts"]:
        score = 100
    elif row["label"] in spec["labels"]:
        score = 65
    else:
        return -10000
    if not is_current_context(row, spec["period"]):
        return -10000
    consolidation = row["consolidation"]
    context = row["context"]
    nonconsolidated = "個別" in consolidation or "NonConsolidatedMember" in context
    if prefer_consolidated:
        score += -80 if nonconsolidated else 45
    elif nonconsolidated:
        score += 20
    if context in {"CurrentYearDuration", "CurrentYearInstant"}:
        score += 20
    if local.endswith("SummaryOfBusinessResults") or local.endswith("KeyFinancialData"):
        score += 8
    if row["value"]:
        score += 5
    return score


def metric_fact_declared(rows: list[dict[str, str]], metric: str, spec: dict, prefer_consolidated: bool, standard: str | None) -> bool:
    selected_spec = metric_spec(metric, spec, standard)
    if selected_spec is None:
        return False
    return any(row_score(row, selected_spec, prefer_consolidated) > -10000 for row in rows)


def select_metric(rows: list[dict[str, str]], metric: str, spec: dict, prefer_consolidated: bool, standard: str | None):
    selected_spec = metric_spec(metric, spec, standard)
    if selected_spec is None:
        return None, None
    candidates = []
    for row in rows:
        value = parse_number(row["value"])
        if value is None:
            continue
        score = row_score(row, selected_spec, prefer_consolidated)
        if score > -10000:
            candidates.append((score, row, value))
    if not candidates:
        return None, None
    candidates.sort(key=lambda item: item[0], reverse=True)
    score, row, value = candidates[0]
    source = {
        "concept": row["concept"],
        "label": row["label"],
        "context": row["context"],
        "relativeYear": row["relativeYear"],
        "consolidation": row["consolidation"],
        "unit": row["unit"],
        "score": score,
    }
    return value, source


def accounting_standard(rows: list[dict[str, str]]) -> str | None:
    for row in rows:
        if local_concept(row["concept"]) == "AccountingStandardsDEI":
            return row["value"] or None
        if row["label"] in {"会計基準", "会計基準の種類"} and row["value"]:
            return row["value"]
    return None

FINANCIAL_INDUSTRIES = {"銀行業", "保険業", "証券、商品先物取引業", "その他金融業"}


def load_master() -> tuple[dict[str, dict], dict[str, dict]]:
    payload = json.loads((PUBLIC / "master.json").read_text(encoding="utf-8"))
    by_edinet = {x["edinetCode"]: x for x in payload["records"] if x.get("edinetCode")}
    by_code = {x["securityCode"]: x for x in payload["records"]}
    return by_edinet, by_code


def choose_documents() -> list[dict]:
    path = RAW / "documents-index.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for doc in payload.get("annualReports", []):
        if str(doc.get("csvFlag")) != "1":
            continue
        key = (doc.get("edinetCode") or "", doc.get("periodEnd") or "")
        if all(key):
            groups[key].append(doc)
    selected = []
    for docs in groups.values():
        docs.sort(
            key=lambda d: (
                1 if d.get("docTypeCode") == "130" else 0,
                d.get("submitDateTime") or "",
            ),
            reverse=True,
        )
        selected.append(docs[0])
    return selected


def safe_ratio(numerator, denominator):
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator * 100


def normalize_document(doc: dict, company: dict) -> dict | None:
    csv_path = RAW / "csv" / f"{doc['docID']}.zip"
    xbrl_path = RAW / "xbrl" / f"{doc['docID']}.zip"
    if csv_path.exists():
        rows = read_fact_rows(csv_path)
        source_format = "edinet-csv"
    elif xbrl_path.exists():
        from .xbrl_facts import read_xbrl_fact_rows
        rows = read_xbrl_fact_rows(xbrl_path)
        source_format = "xbrl"
    else:
        return None
    prefer_consolidated = bool(company.get("consolidatedAvailable"))
    standard = accounting_standard(rows)
    metrics: dict[str, int | float | None] = {}
    sources: dict[str, dict] = {}
    for key, spec in METRICS.items():
        value, source = select_metric(rows, key, spec, prefer_consolidated, standard)
        metrics[key] = value
        if source:
            sources[key] = source
    salary_anomaly = False
    salary = metrics.get("averageSalary")
    if salary is not None and not (100_000 <= salary <= 100_000_000):
        from .salary import recover_average_salary
        recovered, recovery_source = recover_average_salary(xbrl_path)
        if recovered is not None:
            metrics["averageSalary"] = recovered
            if sources.get("averageSalary") and recovery_source:
                sources["averageSalary"]["presentationRecovery"] = recovery_source
        else:
            metrics["averageSalary"] = None
            salary_anomaly = True
    metrics["freeCashFlow"] = None
    if metrics.get("operatingCashFlow") is not None and metrics.get("investingCashFlow") is not None:
        metrics["freeCashFlow"] = metrics["operatingCashFlow"] + metrics["investingCashFlow"]
    metrics["operatingMargin"] = safe_ratio(metrics.get("operatingIncome"), metrics.get("revenue"))
    metrics["netMargin"] = safe_ratio(metrics.get("netIncome"), metrics.get("revenue"))
    reported_roe = metrics.get("reportedRoe")
    metrics["roe"] = (reported_roe * 100 if reported_roe is not None and abs(reported_roe) <= 2 else reported_roe)
    declared = metric_fact_declared(rows, "reportedRoe", METRICS["reportedRoe"], prefer_consolidated, standard)
    if metrics["roe"] is None and not declared:
        metrics["roe"] = safe_ratio(metrics.get("netIncome"), metrics.get("parentEquity") or metrics.get("equity"))
    metrics["roa"] = safe_ratio(metrics.get("netIncome"), metrics.get("assets"))
    reported_equity_ratio = metrics.get("reportedEquityRatio")
    metrics["equityRatio"] = (reported_equity_ratio * 100 if reported_equity_ratio is not None and abs(reported_equity_ratio) <= 2 else reported_equity_ratio)
    if metrics["equityRatio"] is None:
        metrics["equityRatio"] = safe_ratio(metrics.get("parentEquity") or metrics.get("equity"), metrics.get("assets"))
    metrics["debtRatio"] = safe_ratio(metrics.get("liabilities"), metrics.get("equity"))
    warnings = []
    if salary_anomaly:
        warnings.append({"type": "implausibleAverageSalary", "message": "XBRL presentation unit could not be recovered; value omitted"})
    assets = metrics.get("assets")
    liabilities = metrics.get("liabilities")
    equity = metrics.get("equity")
    if assets not in (None, 0) and liabilities is not None and equity is not None:
        gap = abs(assets - liabilities - equity)
        if gap / abs(assets) > 0.02:
            warnings.append({"type": "balanceSheetEquation", "gap": gap})
    if company.get("industry33") in FINANCIAL_INDUSTRIES:
        metrics["operatingMargin"] = None
        metrics["netMargin"] = None
        metrics["debtRatio"] = None
        warnings.append({"type": "financialSector", "message": "一般企業と同じ利益率・負債比率評価をしない"})
    from .segments import extract_segments
    from .ownership import extract_major_shareholders
    segments = extract_segments(rows, RAW / "xbrl" / f"{doc['docID']}.zip")
    major_shareholders = extract_major_shareholders(rows)
    return {
        "securityCode": company["securityCode"],
        "edinetCode": company["edinetCode"],
        "name": company["name"],
        "industry33": company.get("industry33"),
        "market": company.get("market"),
        "sectorModel": "financial" if company.get("industry33") in FINANCIAL_INDUSTRIES else "general",
        "fiscalYear": (doc.get("periodEnd") or "")[:4] or None,
        "periodStart": doc.get("periodStart"),
        "periodEnd": doc.get("periodEnd"),
        "submitDateTime": doc.get("submitDateTime"),
        "docID": doc.get("docID"),
        "docTypeCode": doc.get("docTypeCode"),
        "sourceFormat": source_format,
        "accountingStandard": standard,
        "consolidatedPreferred": prefer_consolidated,
        "metrics": metrics,
        "segments": segments,
        "majorShareholders": major_shareholders,
        "metricSources": sources,
        "warnings": warnings,
    }


def main() -> None:
    by_edinet, _ = load_master()
    records = []
    missing_archives = 0
    documents = choose_documents()
    for index, doc in enumerate(documents, 1):
        company = by_edinet.get(doc.get("edinetCode"))
        if not company:
            continue
        record = normalize_document(doc, company)
        if record is None:
            missing_archives += 1
        else:
            records.append(record)
        if index % 500 == 0 or index == len(documents):
            print(
                f"normalized={index}/{len(documents)} records={len(records)} missing={missing_archives}",
                flush=True,
            )
    records.sort(key=lambda x: (x["securityCode"], x.get("periodEnd") or ""))
    payload = {
        "dataset": "listed-companies-normalized-financials",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "records": records,
        "stats": {
            "records": len(records),
            "companies": len({x["securityCode"] for x in records}),
            "missingArchives": missing_archives,
            "csvRecords": sum(1 for x in records if x.get("sourceFormat") == "edinet-csv"),
            "xbrlFallbackRecords": sum(1 for x in records if x.get("sourceFormat") == "xbrl"),
            "balanceSheetWarnings": sum(
                1 for x in records if any(w["type"] == "balanceSheetEquation" for w in x["warnings"])
            ),
        },
    }
    write_json(RAW / "normalized" / "financials.json", payload)
    print(payload["stats"])


if __name__ == "__main__":
    main()
