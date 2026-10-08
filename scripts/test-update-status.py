#!/usr/bin/env python3
"""Exercise missing/stale/failed state, independent source dates and deployment history."""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("status", Path(__file__).with_name("report-update-status.py"))
status = importlib.util.module_from_spec(spec)
spec.loader.exec_module(status)
NOW = datetime(2026, 10, 8, 4, 30, tzinfo=timezone.utc)


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.write("collector/source_catalog.json", {"sources": {"price": {
            "enabled": True, "frequency": "monthly", "maxAgeHours": 840, "minRecords": 1}}})
        self.write("src/data/sources.json", {"sources": {"price": {
            "status": "ok", "finishedAt": "2026-10-07T23:00:00Z",
            "metrics": {"records": 20, "latestMonth": "2026-08"}}}})
        self.write("data/automation/last-production-verification.json", {
            "ok": True, "commit": "published", "releaseId": "release",
            "verifiedAt": "2026-10-07T23:30:00Z"})
        path = self.root / "data/automation/history.jsonl"
        path.write_text(json.dumps({"job": "daily", "verified": True,
            "commit": "published", "finishedAt": "2026-10-08T08:40:00+09:00"}) + "\n")

        for marker in ("last-success-date", "last-wikipedia-success-date", "last-weekly-success-date"):
            (self.root / "data/automation" / marker).write_text("2026-10-07")

    def test_missing_or_old_publication_date_fails(self):
        path = self.root / "data/automation/last-success-date"
        path.write_text("2026-10-01")
        self.assertFalse(self.report()["ok"])
        path.unlink()
        self.assertFalse(self.report()["ok"])

    def test_weekly_audit_missing_or_stale_fails(self):
        path = self.root / "data/automation/last-weekly-success-date"
        path.write_text("2026-09-01")
        self.assertFalse(self.report()["ok"])
        path.unlink()
        self.assertFalse(self.report()["ok"])

    def test_weekly_failure_after_recent_success_is_not_hidden(self):
        directory = self.root / "data/automation/weekly-audit-logs"
        directory.mkdir()
        (directory / "failures.log").write_text("2026-10-08T12:00:00+09:00\tjob=weekly\tstep=collection\n")
        self.assertFalse(self.report()["ok"])
        (self.root / "data/automation/last-weekly-success-date").write_text("2026-10-08")
        (directory / "2026-10-08.log").write_text("=== weekly refresh verified success 2026-10-08T11:00:00+09:00 ===\n")
        self.assertFalse(self.report()["ok"])
        (directory / "2026-10-08.log").write_text("=== weekly refresh verified success 2026-10-08T13:00:00+09:00 ===\n")
        self.assertTrue(self.report()["ok"])

    def test_daily_failure_after_success_is_detected_and_retry_clears_it(self):
        directory = self.root / "data/automation/logs"
        directory.mkdir()
        (directory / "failures.log").write_text("2026-10-08T12:00:00+09:00\tjob=daily\n")
        self.assertFalse(self.report()["ok"])
        with (self.root / "data/automation/history.jsonl").open('a') as f:
            f.write(json.dumps({"job": "daily", "verified": True, "commit": "published",
                "finishedAt": "2026-10-08T13:00:00+09:00"})+'\n')
        self.assertTrue(self.report()["ok"])

    def test_topics_failure_is_reported_without_verified_history(self):
        (self.root / "data/automation/wikipedia-failures.log").write_text("2026-10-08T12:00:00+09:00\tjob=topics\n")
        self.assertFalse(self.report()["ok"])

    def write(self, path, value):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value))

    def source(self, **updates):
        path = self.root / "src/data/sources.json"
        data = json.loads(path.read_text())
        data["sources"]["price"].update(updates)
        self.write("src/data/sources.json", data)

    def report(self):
        return status.build_report(self.root, NOW)

    def test_source_month_is_not_collection_or_publication_date(self):
        report = self.report()
        self.assertTrue(report["ok"])
        self.assertEqual(report["sources"][0]["sourcePeriod"], {"latestMonth": "2026-08"})
        self.assertTrue(report["sources"][0]["collectedAt"].startswith("2026-10-08"))
        self.assertEqual(report["productionVerification"]["commit"], "published")

    def test_missing_period_stays_missing(self):
        self.source(metrics={"records": 20})
        self.assertEqual(self.report()["sources"][0]["sourcePeriod"], {})

    def test_missing_source_status_fails(self):
        self.write("src/data/sources.json", {"sources": {}})
        self.assertFalse(self.report()["ok"])

    def test_old_source_timestamp_fails(self):
        self.source(finishedAt="2026-08-01T00:00:00Z")
        self.assertFalse(self.report()["ok"])

    def test_failed_collection_fails(self):
        self.source(status="failed")
        self.assertFalse(self.report()["ok"])

    def test_future_or_naive_timestamp_fails(self):
        for value in ("2027-01-01T00:00:00Z", "2026-10-08T00:00:00"):
            self.source(finishedAt=value)
            self.assertFalse(self.report()["ok"])

    def test_record_loss_fails(self):
        self.source(metrics={"records": 0})
        self.assertFalse(self.report()["ok"])

    def test_old_deployment_commit_fails(self):
        self.write("data/automation/last-production-verification.json", {
            "ok": True, "commit": "old", "releaseId": "release",
            "verifiedAt": "2026-10-07T23:30:00Z"})
        self.assertFalse(self.report()["ok"])

    def test_failed_or_missing_production_record_fails(self):
        self.write("data/automation/last-production-verification.json", {"ok": False})
        self.assertFalse(self.report()["ok"])
        (self.root / "data/automation/last-production-verification.json").unlink()
        self.assertFalse(self.report()["ok"])


if __name__ == "__main__":
    unittest.main()
