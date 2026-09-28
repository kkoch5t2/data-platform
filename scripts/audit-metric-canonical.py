#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.core.canonical_metrics import audit_catalog

if __name__ == "__main__":
    result = audit_catalog()
    print(f"canonical metrics: OK / {result['metrics']} metrics / {result['publicTargets']} targets / {result['sources']} sources")
