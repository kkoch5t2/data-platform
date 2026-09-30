from __future__ import annotations

import hashlib
import shutil
import tempfile
import urllib.request
from pathlib import Path

from .common import RAW, ensure_dirs

FINANCE_URL = "https://content.info.gbiz.go.jp/download/legacy/standard/Zaimujoho_UTF-8_20251204.zip"
FINANCE_NAME = "Zaimujoho_UTF-8_20251204.zip"
FINANCE_SHA256 = "e67542f81cc747260b6d8dd739137395ca99bb88fd4fdff1093e1c189f16b18a"
USER_AGENT = "DATLUME/1.0 (+https://datlume.com/)"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_finance(force: bool = False) -> Path:
    ensure_dirs()
    target = RAW / "gbiz-legacy" / FINANCE_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not force and sha256(target) == FINANCE_SHA256:
        print(f"gBizINFO legacy finance already verified: {target}")
        return target
    request = urllib.request.Request(FINANCE_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as tmp:
            shutil.copyfileobj(response, tmp, length=1024 * 1024)
            temp_path = Path(tmp.name)
    actual = sha256(temp_path)
    if actual != FINANCE_SHA256:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"gBizINFO legacy finance checksum mismatch: expected={FINANCE_SHA256} actual={actual}"
        )
    temp_path.replace(target)
    print(f"gBizINFO legacy finance downloaded: {target} sha256={actual}")
    return target


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    download_finance(args.force)
