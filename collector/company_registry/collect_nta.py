from __future__ import annotations

import argparse
import csv
import http.cookiejar
import os
import re
import shutil
import sqlite3
import tempfile
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .common import NTA_DB, RAW, ensure_dirs, normalize_company_name, valid_corporate_number

NTA_PAGE = "https://www.houjin-bangou.nta.go.jp/download/zenken/index.html"
TOKEN_NAME = "jp.go.nta.houjin_bangou.framework.web.common.CNSFWTokenProcessor.request.token"
USER_AGENT = "DATLUME/1.0 (+https://datlume.com/)"

CSV_COLUMNS = (
    "sequence_number", "corporate_number", "process", "correct", "update_date",
    "change_date", "name", "name_image_id", "kind", "prefecture_name",
    "city_name", "street_number", "address_image_id", "prefecture_code",
    "city_code", "post_code", "address_outside", "address_outside_image_id",
    "close_date", "close_cause", "successor_corporate_number", "change_cause",
    "assignment_date", "latest", "en_name", "en_prefecture_name", "en_address",
    "en_address_outside", "furigana", "hihyoji",
)


def make_opener() -> urllib.request.OpenerDirector:
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def fetch_page(opener: urllib.request.OpenerDirector) -> str:
    request = urllib.request.Request(NTA_PAGE, headers={"User-Agent": USER_AGENT})
    with opener.open(request, timeout=60) as response:
        return response.read().decode("utf-8", "replace")


def unicode_section(page: str) -> str:
    marker = 'id="csv-unicode"'
    start = page.find(marker)
    if start < 0:
        raise RuntimeError("NTA Unicode CSV section was not found")
    end = page.find('id="xml-unicode"', start)
    return page[start:end if end >= 0 else None]


def discover_file_numbers(page: str, region: str) -> list[str]:
    section = unicode_section(page)
    region_pattern = re.escape(region)
    match = re.search(
        rf'<dt[^>]*>\s*{region_pattern}\s*</dt>([\s\S]*?)</dl>', section, re.I
    )
    if not match:
        raise RuntimeError(f"NTA download region was not found: {region}")
    file_numbers = re.findall(r"doDownload\((\d+)\)", match.group(1))
    if not file_numbers:
        raise RuntimeError(f"NTA Unicode CSV file was not found: {region}")
    return file_numbers


def csrf_token(page: str) -> str:
    match = re.search(
        rf'name="{re.escape(TOKEN_NAME)}"\s+value="([^"]+)"', page
    )
    if not match:
        raise RuntimeError("NTA CSRF token was not found")
    return match.group(1)


def response_filename(response, file_number: str) -> str:
    header = response.headers.get("Content-Disposition", "")
    match = re.search(r"filename\*=utf-8'[^']*'([^;]+)", header, re.I)
    if match:
        return urllib.parse.unquote(match.group(1)).strip('"')
    match = re.search(r'filename="?([^";]+)', header, re.I)
    return match.group(1) if match else f"nta_{file_number}.zip"


def download_file(opener: urllib.request.OpenerDirector, file_number: str) -> Path:
    page = fetch_page(opener)
    form = urllib.parse.urlencode({
        TOKEN_NAME: csrf_token(page), "event": "download", "selDlFileNo": file_number,
    }).encode()
    request = urllib.request.Request(
        NTA_PAGE, data=form, headers={"User-Agent": USER_AGENT, "Referer": NTA_PAGE}
    )
    with opener.open(request, timeout=180) as response:
        filename = response_filename(response, file_number)
        destination = RAW / "nta" / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as tmp:
            shutil.copyfileobj(response, tmp, length=1024 * 1024)
            temp_path = Path(tmp.name)
    if not zipfile.is_zipfile(temp_path):
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(f"NTA response is not a ZIP file: {file_number}")
    temp_path.replace(destination)
    return destination


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    PRAGMA journal_mode=OFF;
    PRAGMA synchronous=OFF;
    CREATE TABLE corporations (
      corporate_number TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      normalized_name TEXT NOT NULL,
      kind TEXT,
      prefecture_name TEXT,
      city_name TEXT,
      street_number TEXT,
      prefecture_code TEXT,
      city_code TEXT,
      post_code TEXT,
      close_date TEXT,
      close_cause TEXT,
      successor_corporate_number TEXT,
      assignment_date TEXT,
      latest INTEGER NOT NULL DEFAULT 0,
      en_name TEXT,
      en_prefecture_name TEXT,
      en_address TEXT,
      furigana TEXT,
      hihyoji INTEGER NOT NULL DEFAULT 0,
      update_date TEXT,
      change_date TEXT,
      source_file TEXT NOT NULL
    );
    CREATE INDEX idx_corporations_name ON corporations(normalized_name);
    CREATE INDEX idx_corporations_active_name ON corporations(normalized_name, close_date, latest);
    CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """)


def corporation_record(values: list[str], source_file: str) -> tuple:
    row = dict(zip(CSV_COLUMNS, values))
    corporate_number = row["corporate_number"].strip()
    if not valid_corporate_number(corporate_number):
        raise ValueError(f"invalid corporate number: {corporate_number!r}")
    return (
        corporate_number, row["name"], normalize_company_name(row["name"]), row["kind"],
        row["prefecture_name"], row["city_name"], row["street_number"],
        row["prefecture_code"], row["city_code"], row["post_code"], row["close_date"],
        row["close_cause"], row["successor_corporate_number"], row["assignment_date"],
        1 if row["latest"] == "1" else 0, row["en_name"], row["en_prefecture_name"],
        row["en_address"], row["furigana"], 1 if row["hihyoji"] == "1" else 0,
        row["update_date"], row["change_date"], source_file,
    )


INSERT_SQL = """
INSERT OR REPLACE INTO corporations (
 corporate_number,name,normalized_name,kind,prefecture_name,city_name,street_number,
 prefecture_code,city_code,post_code,close_date,close_cause,successor_corporate_number,
 assignment_date,latest,en_name,en_prefecture_name,en_address,furigana,hihyoji,
 update_date,change_date,source_file
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""


def ingest_zip(conn: sqlite3.Connection, zip_path: Path) -> int:
    inserted = 0
    batch: list[tuple] = []
    with zipfile.ZipFile(zip_path) as archive:
        csv_names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(csv_names) != 1:
            raise RuntimeError(f"expected one CSV in {zip_path.name}, got {csv_names}")
        csv_name = csv_names[0]
        with archive.open(csv_name) as raw:
            import io
            reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))
            for line_number, values in enumerate(reader, start=1):
                if len(values) != len(CSV_COLUMNS):
                    raise RuntimeError(
                        f"{csv_name}:{line_number}: expected {len(CSV_COLUMNS)} columns, got {len(values)}"
                    )
                batch.append(corporation_record(values, zip_path.name))
                if len(batch) >= 50000:
                    conn.executemany(INSERT_SQL, batch)
                    inserted += len(batch)
                    batch.clear()
            if batch:
                conn.executemany(INSERT_SQL, batch)
                inserted += len(batch)
    conn.commit()
    return inserted


def source_date(paths: list[Path]) -> str:
    dates = []
    for path in paths:
        match = re.search(r"_(\d{8})\.zip$", path.name)
        if match:
            dates.append(match.group(1))
    value = max(dates) if dates else ""
    return f"{value[:4]}-{value[4:6]}-{value[6:]}" if value else ""


def build_database(paths: list[Path], region: str) -> dict:
    ensure_dirs()
    fd, temp_name = tempfile.mkstemp(prefix="nta-corporations-", suffix=".sqlite", dir=RAW)
    os.close(fd)
    temp_db = Path(temp_name)
    try:
        conn = sqlite3.connect(temp_db)
        create_schema(conn)
        rows_read = sum(ingest_zip(conn, path) for path in paths)
        total = conn.execute("SELECT COUNT(*) FROM corporations").fetchone()[0]
        active = conn.execute(
            "SELECT COUNT(*) FROM corporations WHERE latest=1 AND COALESCE(close_date,'')=''"
        ).fetchone()[0]
        closed = conn.execute(
            "SELECT COUNT(*) FROM corporations WHERE COALESCE(close_date,'')<>''"
        ).fetchone()[0]
        date = source_date(paths)
        meta = {
            "source": NTA_PAGE, "sourceDate": date, "region": region,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rowsRead": str(rows_read), "corporations": str(total), "active": str(active),
        }
        conn.executemany("INSERT INTO metadata(key,value) VALUES (?,?)", meta.items())
        conn.commit()
        conn.close()
        temp_db.replace(NTA_DB)
        return {
            "region": region, "sourceDate": date, "rowsRead": rows_read,
            "corporations": total, "active": active, "closed": closed,
            "files": [path.name for path in paths],
        }
    except Exception:
        temp_db.unlink(missing_ok=True)
        raise


def main(region: str, inputs: list[str] | None = None) -> dict:
    ensure_dirs()
    if inputs:
        paths = [Path(value).expanduser().resolve() for value in inputs]
    else:
        opener = make_opener()
        page = fetch_page(opener)
        file_numbers = discover_file_numbers(page, region)
        print(f"nta region={region} files={len(file_numbers)} ids={','.join(file_numbers)}", flush=True)
        paths = []
        for index, file_number in enumerate(file_numbers, start=1):
            path = download_file(opener, file_number)
            paths.append(path)
            print(f"nta download {index}/{len(file_numbers)} {path.name} bytes={path.stat().st_size}", flush=True)
    result = build_database(paths, region)
    print(f"nta registry {result}", flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", default="全国")
    parser.add_argument("--input", action="append", default=[])
    args = parser.parse_args()
    main(args.region, args.input or None)
