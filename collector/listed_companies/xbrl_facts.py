from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

XLINK = "{http://www.w3.org/1999/xlink}"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def _public_files(archive: zipfile.ZipFile, suffix: str) -> list[str]:
    return [
        name for name in archive.namelist()
        if "publicdoc" in name.lower() and name.lower().endswith(suffix.lower())
    ]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _relative_year(context_id: str) -> str:
    if context_id.startswith("CurrentYear"):
        return "当期"
    if context_id.startswith("Prior1Year"):
        return "前期"
    if context_id.startswith("Prior2Year"):
        return "前々期"
    if context_id.startswith("Prior3Year"):
        return "3期前"
    if context_id.startswith("Prior4Year"):
        return "4期前"
    return ""


def _labels(archive: zipfile.ZipFile) -> dict[str, str]:
    labels: dict[str, str] = {}
    for name in _public_files(archive, "_lab.xml"):
        root = ET.fromstring(archive.read(name))
        locators: dict[str, str] = {}
        resources: dict[str, str] = {}
        arcs: list[tuple[str | None, str | None]] = []
        for element in root.iter():
            kind = _local(element.tag)
            if kind == "loc":
                label = element.attrib.get(XLINK + "label")
                href = element.attrib.get(XLINK + "href", "")
                if label and "#" in href:
                    locators[label] = href.rsplit("#", 1)[-1]
            elif kind == "label":
                label = element.attrib.get(XLINK + "label")
                role = element.attrib.get(XLINK + "role", "")
                lang = element.attrib.get(XML_LANG)
                if label and lang == "ja" and role.endswith("/label"):
                    resources[label] = (element.text or "").strip()
            elif kind == "labelArc":
                arcs.append((element.attrib.get(XLINK + "from"), element.attrib.get(XLINK + "to")))
        for source, target in arcs:
            concept_id = locators.get(source or "")
            text = resources.get(target or "")
            if concept_id and text:
                labels.setdefault(concept_id.rsplit("_", 1)[-1], text)
    return labels


def _context_meta(root: ET.Element) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for element in root:
        if _local(element.tag) != "context":
            continue
        context_id = element.attrib.get("id")
        if not context_id:
            continue
        has_start = any(_local(child.tag) == "startDate" for child in element.iter())
        has_instant = any(_local(child.tag) == "instant" for child in element.iter())
        nonconsolidated = any(
            _local(child.tag) == "explicitMember" and
            "NonConsolidatedMember" in ((child.text or "").strip())
            for child in element.iter()
        )
        result[context_id] = {
            "relativeYear": _relative_year(context_id),
            "consolidation": "個別" if nonconsolidated else "その他",
            "periodType": "期間" if has_start else ("時点" if has_instant else ""),
        }
    return result


def read_xbrl_fact_rows(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with zipfile.ZipFile(path) as archive:
        labels = _labels(archive)
        for name in _public_files(archive, ".xbrl"):
            root = ET.fromstring(archive.read(name))
            contexts = _context_meta(root)
            for element in root:
                context = element.attrib.get("contextRef")
                if not context:
                    continue
                concept = _local(element.tag)
                meta = contexts.get(context, {})
                rows.append({
                    "concept": concept,
                    "label": labels.get(concept, ""),
                    "context": context,
                    "relativeYear": meta.get("relativeYear", ""),
                    "consolidation": meta.get("consolidation", ""),
                    "periodType": meta.get("periodType", ""),
                    "unit": element.attrib.get("unitRef", ""),
                    "value": re.sub(r"[\r\n\t]+", " ", (element.text or "")).strip(),
                    "sourceFile": name,
                })
    return rows
