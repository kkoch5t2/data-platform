import json, time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATUS_PATH = ROOT / "src" / "data" / "sources.json"

def utcnow():
    return datetime.now(timezone.utc).isoformat()

def load_status():
    if not STATUS_PATH.exists():
        return {"schemaVersion": 1, "sources": {}}
    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"schemaVersion": 1, "sources": {}}

def save_status(data):
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATUS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATUS_PATH)

class SourceRun:
    def __init__(self, key, label):
        self.key, self.label = key, label
        self.started_at = utcnow()
        self.started = time.monotonic()
        self.metrics = {}

    def set_metrics(self, **metrics):
        self.metrics.update(metrics)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        data = load_status(); sources = data.setdefault("sources", {})
        previous = sources.get(self.key, {})
        entry = {
            "label": self.label,
            "status": "error" if exc else "ok",
            "startedAt": self.started_at,
            "finishedAt": utcnow(),
            "durationSeconds": round(time.monotonic() - self.started, 2),
            "metrics": self.metrics,
        }
        prev_records = (previous.get("metrics") or {}).get("records")
        if prev_records is not None:
            entry["previousRecordCount"] = prev_records
        if exc:
            entry["error"] = f"{exc_type.__name__}: {exc}"[:1000]
        sources[self.key] = entry; save_status(data)
        return False
