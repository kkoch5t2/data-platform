import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "collector" / "metric_catalog.json"


def load_catalog():
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def audit_catalog(catalog=None):
    catalog = catalog or load_catalog()
    sources = catalog.get("sources", {})
    priorities = set(catalog.get("policy", {}).get("sourcePriority", []))
    seen_ids, seen_targets, errors = set(), set(), []
    for metric in catalog.get("metrics", []):
        metric_id = metric.get("metricId")
        canonical = metric.get("canonical") or {}
        source = canonical.get("source")
        target = (canonical.get("dataset"), canonical.get("field"))
        if not metric_id or metric_id in seen_ids:
            errors.append(f"duplicate/empty metricId: {metric_id}")
        seen_ids.add(metric_id)
        if source not in sources:
            errors.append(f"{metric_id}: unknown canonical source {source}")
        elif sources[source].get("tier") not in priorities:
            errors.append(f"{metric_id}: unknown source tier {sources[source].get('tier')}")
        if not all(target) or target in seen_targets:
            errors.append(f"{metric_id}: duplicate/empty public target {target}")
        seen_targets.add(target)
    if errors:
        raise ValueError("canonical metric audit failed: " + "; ".join(errors))
    return {"metrics": len(seen_ids), "publicTargets": len(seen_targets), "sources": len(sources)}


def assert_can_publish(metric_id, source_id, dataset, field):
    catalog = load_catalog()
    audit_catalog(catalog)
    matches = [m for m in catalog["metrics"] if m["metricId"] == metric_id]
    if len(matches) != 1:
        raise ValueError(f"metric not uniquely registered: {metric_id}")
    expected = matches[0]["canonical"]
    actual = {"source": source_id, "dataset": dataset, "field": field}
    if any(expected.get(k) != v for k, v in actual.items()):
        raise ValueError(f"non-canonical publication blocked for {metric_id}: expected {expected}, got {actual}")
    return True
