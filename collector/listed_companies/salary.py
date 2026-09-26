from __future__ import annotations

import html
import re
import zipfile
from pathlib import Path

CONCEPT = "AverageAnnualSalaryInformationAboutReportingCompanyInformationAboutEmployees"
UNIT_MULTIPLIER = {"円": 1, "千円": 1_000, "万円": 10_000}
FACT_RE = re.compile(
    rf'<ix:nonFraction\b([^>]*name="[^"]*{CONCEPT}[^"]*"[^>]*)>(.*?)</ix:nonFraction>',
    re.I | re.S,
)


def _plain(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _number(text: str):
    cleaned = _plain(text).replace(",", "").replace("，", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def recover_average_salary(xbrl_zip: Path) -> tuple[int | float | None, dict | None]:
    if not xbrl_zip.exists():
        return None, None
    with zipfile.ZipFile(xbrl_zip) as archive:
        names = [n for n in archive.namelist() if "publicdoc" in n.lower() and n.lower().endswith((".htm", ".html"))]
        for name in names:
            source = archive.read(name).decode("utf-8", "ignore")
            for match in FACT_RE.finditer(source):
                attrs, displayed = match.group(1), match.group(2)
                if "CurrentYearInstant" not in attrs:
                    continue
                value = _number(displayed)
                if value is None:
                    continue
                start = source.rfind("<table", 0, match.start())
                end = source.find("</table>", match.end())
                if start < 0 or end < 0:
                    continue
                table_text = _plain(source[start:end + 8])
                unit_match = re.search(r"(?:平均年間給与|年間平均給与)\s*[（(]\s*(千円|万円|円)\s*[）)]", table_text)
                if unit_match:
                    unit = unit_match.group(1)
                    recovered = value * UNIT_MULTIPLIER[unit]
                    if 100_000 <= recovered <= 100_000_000:
                        if float(recovered).is_integer():
                            recovered = int(recovered)
                        return recovered, {"displayedValue": value, "presentationUnit": unit, "sourceFile": name}
                    # A contradictory header/value pair is not corrected by inference.
                    continue
                # Some filings put the unit immediately after the tagged display value.
                after = _plain(source[match.end(): min(end + 8, match.end() + 500)])
                suffix_match = re.match(r"\s*(千円|万円|円)(?:\s|$)", after)
                if suffix_match:
                    unit = suffix_match.group(1)
                    recovered = value * UNIT_MULTIPLIER[unit]
                    if 100_000 <= recovered <= 100_000_000:
                        if float(recovered).is_integer():
                            recovered = int(recovered)
                        return recovered, {"displayedValue": value, "presentationUnit": unit, "sourceFile": name}
                # Some filings place the currency in a separate cell rather than the header.
                if ("平均年間給与" in table_text or "年間平均給与" in table_text) and "千円" not in table_text and "万円" not in table_text and "円" in table_text:
                    if 100_000 <= value <= 100_000_000:
                        recovered = int(value) if float(value).is_integer() else value
                        return recovered, {"displayedValue": value, "presentationUnit": "円", "sourceFile": name}
    return None, None
