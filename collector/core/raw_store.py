import gzip, hashlib, json, os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = Path(os.getenv("PUBLIC_DATA_RAW_DIR", ROOT / "data" / "raw"))
RAW_ENABLED = os.getenv("PUBLIC_DATA_SAVE_RAW", "1") not in {"0", "false", "False"}

def _stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")

def _safe_key(key):
    digest = hashlib.sha1(str(key).encode("utf-8")).hexdigest()[:12]
    return digest

def save_json(source, key, payload):
    if not RAW_ENABLED:
        return None
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    folder = RAW_ROOT / source / day
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_stamp()}_{_safe_key(key)}.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    return path
