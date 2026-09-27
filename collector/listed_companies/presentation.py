from __future__ import annotations

import html
import re
import zipfile
from pathlib import Path

FACT_RE = re.compile(r'<ix:nonFraction\b([^>]*)>(.*?)</ix:nonFraction>', re.I | re.S)
ATTR_RE = re.compile(r'(\w+)="([^"]*)"', re.I)


def _plain(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _number(fragment: str):
    text = _plain(fragment).replace(",", "").replace("，", "").strip()
    negative = "△" in text or "▲" in text or (text.startswith("(") and text.endswith(")"))
    text = text.replace("△", "").replace("▲", "").strip("() ")
    try:
        value = float(text)
    except ValueError:
        return None
    value = -value if negative else value
    return int(value) if value.is_integer() else value


def _local(name: str) -> str:
    return name.rsplit(":", 1)[-1]


def _table_text(source: str, start_pos: int, end_pos: int) -> str:
    start = source.rfind("<table", 0, start_pos)
    end = source.find("</table>", end_pos)
    if start < 0 or end < 0:
        return ""
    return _plain(source[start:end + 8])


def recover_count_metric(xbrl_zip: Path, metric: str, source_info: dict) -> tuple[int | float | None, dict | None]:
    if metric not in {"employees", "sharesOutstanding"} or not xbrl_zip.exists():
        return None, None
    wanted_concept = _local(source_info.get("concept", ""))
    wanted_context = source_info.get("context", "")
    with zipfile.ZipFile(xbrl_zip) as archive:
        names = [n for n in archive.namelist() if "publicdoc" in n.lower() and n.lower().endswith((".htm", ".html"))]
        for name in names:
            document = archive.read(name).decode("utf-8", "ignore")
            for match in FACT_RE.finditer(document):
                attrs = dict(ATTR_RE.findall(match.group(1)))
                if _local(attrs.get("name", "")) != wanted_concept:
                    continue
                if attrs.get("contextRef") != wanted_context:
                    continue
                displayed = _number(match.group(2))
                if displayed is None:
                    continue
                table = _table_text(document, match.start(), match.end())
                recovered = None
                presentation_unit = None
                if metric == "employees":
                    if "従業員数" not in table:
                        continue
                    unit_match = re.search(
                        r"従業員数.{0,80}?(?:[（(]\s*)?(人|名)(?=\s|[）)]|$)", table
                    )
                    if unit_match:
                        recovered = displayed
                        presentation_unit = unit_match.group(1)
                else:
                    if "発行済株式総数" not in table:
                        continue
                    unit_match = re.search(
                        r"発行済株式総数.{0,100}?(?:[（(]\s*)?(千株|株)(?=\s|[）)]|$)", table
                    )
                    if unit_match:
                        presentation_unit = unit_match.group(1)
                        recovered = displayed * (1_000 if presentation_unit == "千株" else 1)
                if recovered is None:
                    continue
                if float(recovered).is_integer():
                    recovered = int(recovered)
                if recovered < 0:
                    continue
                return recovered, {
                    "displayedValue": displayed,
                    "presentationUnit": presentation_unit,
                    "sourceFile": name,
                }
    return None, None
