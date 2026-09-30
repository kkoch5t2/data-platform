from __future__ import annotations

import json
import re
import tempfile
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "company-registry"
PUBLIC = ROOT / "public" / "data" / "company-registry"
NTA_DB = RAW / "nta-corporations.sqlite"


def normalize_company_name(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    replacements = {
        "(株)": "株式会社", "(有)": "有限会社",
        "(同)": "合同会社", "(資)": "合資会社", "(名)": "合名会社",
        "㈱": "株式会社", "㈲": "有限会社",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return re.sub(r"[\s\u3000]+", "", text).strip("、,・").casefold()


def valid_corporate_number(value: object) -> bool:
    return bool(re.fullmatch(r"\d{13}", str(value or "").strip()))


def ensure_dirs() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as tmp:
        json.dump(payload, tmp, ensure_ascii=False, separators=(",", ":"))
        tmp.write("\n")
        temp_path = Path(tmp.name)
    temp_path.replace(path)
