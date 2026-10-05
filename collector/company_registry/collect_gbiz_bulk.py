from __future__ import annotations

import argparse
import csv
import io
import http.cookiejar
import os
import re
import shutil
import stat
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from .common import RAW, ensure_dirs
from collector.core.source_run import SourceRun

GBIZ_DOWNLOAD_PAGE = "https://info.gbiz.go.jp/hojin/DownloadTop"
USER_AGENT = "DATLUME/1.0 (+https://datlume.com/)"
DOWNLOAD_TYPES = {
    "basic": "Kihonjoho",
    "office": "Jigyousyojoho",
    "certification": "TodokedeNinteijoho",
    "commendation": "Hyoshojoho",
    "subsidy": "Hojokinjoho",
    "procurement": "Chotatsujoho",
    "patent": "Tokkyojoho",
    "finance": "Zaimujoho",
    "workplace": "Shokubajoho",
    "all-activity": "Hojinjoho",
    "statements": "Kessanjoho",
}


def access_token() -> str:
    token = os.environ.get("GBIZINFO_ACCESS_TOKEN", "").strip()
    if token:
        return token
    configured = os.environ.get("DATLUME_GBIZINFO_TOKEN_FILE", "").strip()
    path = Path(configured).expanduser() if configured else Path.home() / ".config" / "datlume" / "gbizinfo_access_token"
    if not path.exists():
        raise SystemExit(
            "gBizINFO access token is not configured. Set GBIZINFO_ACCESS_TOKEN or "
            "create ~/.config/datlume/gbizinfo_access_token with mode 0600."
        )
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise SystemExit(f"gBizINFO token file permissions are too open ({oct(mode)}); require 0600 or stricter.")
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit("gBizINFO access token file is empty.")
    return token


def opener() -> urllib.request.OpenerDirector:
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def download_form(op: urllib.request.OpenerDirector) -> tuple[str, str]:
    request = urllib.request.Request(GBIZ_DOWNLOAD_PAGE, headers={"User-Agent": USER_AGENT})
    with op.open(request, timeout=60) as response:
        page = response.read().decode("utf-8", "replace")
        base_url = response.geturl()
    match = re.search(r'<form[^>]+action="([^"]*?/hojin/Download[^" ]*)"[^>]+id="down"', page, re.I)
    if not match:
        raise RuntimeError("gBizINFO download form was not found")
    return urllib.parse.urljoin(base_url, match.group(1)), base_url


def response_filename(response, fallback: str) -> str:
    header = response.headers.get("Content-Disposition", "")
    match = re.search(r"filename\*=utf-8'[^']*'([^;]+)", header, re.I)
    if match:
        return urllib.parse.unquote(match.group(1)).strip('"')
    match = re.search(r'filename="?([^";]+)', header, re.I)
    return match.group(1) if match else fallback


def download(kind: str) -> Path:
    ensure_dirs()
    token = access_token()
    op = opener()
    action, referer = download_form(op)
    payload = urllib.parse.urlencode({
        "downfile": DOWNLOAD_TYPES[kind],
        "meta": "",
        "downenc": "UTF-8",
        "apiToken": token,
        "isZip": "on",
        "downtype": "zip",
    }).encode()
    request = urllib.request.Request(
        action, data=payload, headers={"User-Agent": USER_AGENT, "Referer": referer}
    )
    target_dir = RAW / "gbiz"
    target_dir.mkdir(parents=True, exist_ok=True)
    with op.open(request, timeout=300) as response:
        fallback = f"gbiz-{kind}.zip"
        filename = response_filename(response, fallback)
        destination = target_dir / filename
        with tempfile.NamedTemporaryFile(dir=target_dir, delete=False) as tmp:
            shutil.copyfileobj(response, tmp, length=1024 * 1024)
            temp_path = Path(tmp.name)
    if not zipfile.is_zipfile(temp_path):
        preview = temp_path.read_bytes()[:300].decode("utf-8", "replace")
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(f"gBizINFO download did not return a ZIP file: {preview[:180]!r}")
    temp_path.replace(destination)
    print(f"gbiz download type={kind} file={destination.name} bytes={destination.stat().st_size}")
    return destination


def count_csv_rows(path: Path) -> int:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"expected one CSV in {path.name}")
        with archive.open(names[0]) as raw:
            return sum(1 for _ in csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", choices=sorted(DOWNLOAD_TYPES), default="all-activity")
    args = parser.parse_args()
    if args.type in ("subsidy", "patent"):
        with SourceRun(f"gbiz_{args.type}", f"Gビズインフォ {args.type}") as run:
            path = download(args.type)
            run.set_metrics(records=count_csv_rows(path), sourceDate=re.search(r"20\d{6}", path.name).group(0))
    else:
        download(args.type)
