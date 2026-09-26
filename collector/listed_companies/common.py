from __future__ import annotations

import json
import re
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "listed-companies"
PUBLIC = ROOT / "public" / "data" / "listed-companies"

JPX_LIST_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xlsx"
EDINET_CODE_URL = "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/codelist/Edinetcode.zip"
EDINET_API_BASE = "https://api.edinet-fsa.go.jp/api/v2"

XML_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def ensure_dirs() -> None:
    for p in (RAW, PUBLIC):
        p.mkdir(parents=True, exist_ok=True)


def download(url: str, path: Path, timeout: int = 90) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "DATLUME/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read()
    path.write_bytes(body)
    return path


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        json.dump(payload, tmp, ensure_ascii=False, separators=(",", ":"))
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def normalize_security_code(value: object) -> str:
    code = str(value or "").strip().upper()
    if len(code) == 5 and code.endswith("0"):
        return code[:-1]
    return code


def _column(cell_ref: str) -> str:
    match = re.match(r"([A-Z]+)", cell_ref)
    return match.group(1) if match else ""


def read_xlsx_first_sheet(path: Path) -> list[dict[str, str]]:
    with zipfile.ZipFile(path) as book:
        strings: list[str] = []
        if "xl/sharedStrings.xml" in book.namelist():
            root = ET.fromstring(book.read("xl/sharedStrings.xml"))
            strings = [
                "".join(node.text or "" for node in item.iter(f"{{{XML_NS}}}t"))
                for item in root.findall(f"{{{XML_NS}}}si")
            ]
        sheet = ET.fromstring(book.read("xl/worksheets/sheet1.xml"))
        raw_rows: list[dict[str, str]] = []
        for row in sheet.findall(f".//{{{XML_NS}}}sheetData/{{{XML_NS}}}row"):
            values: dict[str, str] = {}
            for cell in row.findall(f"{{{XML_NS}}}c"):
                col = _column(cell.attrib.get("r", ""))
                cell_type = cell.attrib.get("t")
                value_node = cell.find(f"{{{XML_NS}}}v")
                raw = value_node.text if value_node is not None and value_node.text else ""
                if cell_type == "s" and raw:
                    value = strings[int(raw)]
                elif cell_type == "inlineStr":
                    value = "".join(
                        node.text or "" for node in cell.iter(f"{{{XML_NS}}}t")
                    )
                else:
                    value = raw
                values[col] = value
            raw_rows.append(values)
    if not raw_rows:
        return []
    headers = raw_rows[0]
    rows: list[dict[str, str]] = []
    for row in raw_rows[1:]:
        rows.append({label: row.get(col, "") for col, label in headers.items()})
    return rows


def edinet_api_key() -> str:
    import os
    import stat

    key = os.environ.get("EDINET_API_KEY", "").strip()
    if key:
        return key
    configured = os.environ.get("DATLUME_EDINET_KEY_FILE", "").strip()
    secret_path = Path(configured).expanduser() if configured else Path.home() / ".config" / "datlume" / "edinet_api_key"
    if secret_path.exists():
        mode = stat.S_IMODE(secret_path.stat().st_mode)
        if mode & 0o077:
            raise SystemExit(f"EDINET secret file permissions are too open ({oct(mode)}); require 0600 or stricter.")
        key = secret_path.read_text(encoding="utf-8").strip()
        if key:
            return key
    raise SystemExit(
        "EDINET API key is not configured. Set EDINET_API_KEY or create ~/.config/datlume/edinet_api_key with mode 0600."
    )
