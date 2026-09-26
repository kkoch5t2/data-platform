from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from .normalize_financials import local_concept, parse_number

XLINK = "{http://www.w3.org/1999/xlink}"
EXCLUDED_MEMBERS = {
    "ReportableSegmentsMember", "ReportableSegmentMember",
    "TotalOfReportableSegmentsAndOthersMember", "ReconcilingItemsMember",
    "CorporateSharedMember", "AllOtherReportableSegmentMember",
    "OperatingSegmentsNotIncludedInReportableSegmentsAndOtherRevenueGeneratingBusinessActivitiesMember",
}
EXTERNAL_REVENUE = (
    "OperatingRevenueFromExternalCustomersIFRS", "SalesToExternalCustomersIFRS",
    "RevenueFromExternalCustomers2IFRS", "RevenuesFromExternalCustomers",
    "RevenueFromExternalCustomersIFRS",
)
TOTAL_REVENUE = (
    "OperatingRevenuesIFRS", "NetSalesIFRS", "SalesRevenuesIFRS",
    "Revenue2IFRS", "NetSales", "OperatingRevenue1", "OperatingRevenue2",
)
PROFIT_CONCEPTS = (
    "OperatingProfitLossIFRS", "OperatingIncome", "SegmentProfitLoss",
    "SegmentProfit", "ProfitLossByReportableSegment",
)


def _public_files(archive: zipfile.ZipFile, suffix: str):
    return [name for name in archive.namelist() if "publicdoc" in name.lower() and name.lower().endswith(suffix.lower())]


def _member_from_text(text: str | None) -> str | None:
    if not text:
        return None
    local = text.split(":", 1)[-1]
    if local in EXCLUDED_MEMBERS:
        return None
    if "ReportableSegment" not in local or not local.endswith("Member"):
        return None
    return local


def context_members(archive: zipfile.ZipFile) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for name in _public_files(archive, ".xbrl"):
        root = ET.fromstring(archive.read(name))
        for context in root.iter():
            if context.tag.rsplit("}", 1)[-1] != "context":
                continue
            context_id = context.attrib.get("id")
            if not context_id:
                continue
            for child in context.iter():
                if child.tag.rsplit("}", 1)[-1] == "explicitMember":
                    member = _member_from_text(child.text)
                    if member:
                        mapping[context_id] = member
                        break
    return mapping


def japanese_labels(archive: zipfile.ZipFile) -> dict[str, str]:
    labels: dict[str, str] = {}
    for name in _public_files(archive, "_lab.xml"):
        root = ET.fromstring(archive.read(name))
        locators, resources, arcs = {}, {}, []
        for element in root.iter():
            kind = element.tag.rsplit("}", 1)[-1]
            if kind == "loc":
                label = element.attrib.get(XLINK + "label")
                href = element.attrib.get(XLINK + "href", "")
                if label and "#" in href:
                    locators[label] = href.rsplit("#", 1)[-1]
            elif kind == "label":
                label = element.attrib.get(XLINK + "label")
                role = element.attrib.get(XLINK + "role", "")
                lang = element.attrib.get("{http://www.w3.org/XML/1998/namespace}lang")
                if label and lang == "ja" and role.endswith("/label"):
                    resources[label] = (element.text or "").strip()
            elif kind == "labelArc":
                arcs.append((element.attrib.get(XLINK + "from"), element.attrib.get(XLINK + "to")))
        for source, target in arcs:
            concept_id, text = locators.get(source), resources.get(target)
            if concept_id and text:
                labels[concept_id] = text
    return labels


def label_for_member(member: str, labels: dict[str, str]) -> str | None:
    suffix = "_" + member
    hits = [text for concept, text in labels.items() if concept == member or concept.endswith(suffix)]
    clean = [re.sub(r"、?報告セグメント\s*\[メンバー\]$", "", text).strip() for text in hits]
    clean = [text for text in clean if text and "[メンバー]" not in text]
    return clean[0] if clean else (hits[0] if hits else None)


def _select(rows: list[dict], context: str, concepts: tuple[str, ...], label_terms=()):
    by_concept = {local_concept(row["concept"]): row for row in rows if row["context"] == context}
    for concept in concepts:
        row = by_concept.get(concept)
        if row:
            value = parse_number(row["value"])
            if value is not None:
                return value, row
    for row in rows:
        if row["context"] != context or not any(term in row["label"] for term in label_terms):
            continue
        value = parse_number(row["value"])
        if value is not None:
            return value, row
    return None, None


def _growth(current, previous):
    if current is None or previous in (None, 0):
        return None
    return (current - previous) / abs(previous) * 100


def _segment_value(rows: list[dict], context: str):
    revenue, rev_row = _select(rows, context, EXTERNAL_REVENUE, ("外部顧客への売上高", "外部顧客からの収益"))
    basis = "external"
    if revenue is None:
        revenue, rev_row = _select(rows, context, TOTAL_REVENUE, ("売上高", "営業収益", "収益（IFRS）"))
        basis = "segment-total"
    profit, profit_row = _select(rows, context, PROFIT_CONCEPTS, ("営業利益", "セグメント利益"))
    return revenue, profit, basis, rev_row, profit_row


def extract_segments(rows: list[dict], xbrl_zip: Path) -> list[dict]:
    if not xbrl_zip.exists():
        return []
    with zipfile.ZipFile(xbrl_zip) as archive:
        members = context_members(archive)
        labels = japanese_labels(archive)
    results = []
    for context, member in members.items():
        if not context.startswith("CurrentYearDuration"):
            continue
        label = label_for_member(member, labels)
        if not label:
            continue
        revenue, profit, basis, rev_row, profit_row = _segment_value(rows, context)
        if revenue is None or revenue <= 0:
            continue
        prior_context = context.replace("CurrentYearDuration", "Prior1YearDuration", 1)
        prior_revenue, prior_profit, _, _, _ = _segment_value(rows, prior_context)
        results.append({
            "member": member, "name": label, "revenue": revenue,
            "operatingProfit": profit,
            "operatingMargin": (profit / revenue * 100) if profit is not None else None,
            "revenueYoY": _growth(revenue, prior_revenue),
            "profitYoY": _growth(profit, prior_profit),
            "revenueBasis": basis,
            "revenueConcept": rev_row["concept"] if rev_row else None,
            "profitConcept": profit_row["concept"] if profit_row else None,
            "context": context,
        })
    unique = {item["member"]: item for item in results}
    return sorted(unique.values(), key=lambda item: item["revenue"], reverse=True)
