#!/usr/bin/env python3
from datetime import date
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("master_refresh", Path(__file__).with_name("listed-master-refresh-needed.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FreshnessTests(unittest.TestCase):
    def test_monthly_marker_does_not_hide_old_edition(self):
        self.assertTrue(module.needs_refresh("2026-08-31", "2026-10", date(2026, 10, 8)))

    def test_previous_month_edition_is_sufficient(self):
        self.assertFalse(module.needs_refresh("2026-09-30", "2026-10", date(2026, 10, 8)))

    def test_business_day_month_end_is_sufficient(self):
        self.assertFalse(module.needs_refresh("2026-05-29", "2026-06", date(2026, 6, 8)))

    def test_month_change_still_requires_acquisition(self):
        self.assertTrue(module.needs_refresh("2026-09-30", "2026-09", date(2026, 10, 8)))

    def test_year_boundary_and_leap_year(self):
        self.assertFalse(module.needs_refresh("2025-12-31", "2026-01", date(2026, 1, 5)))
        self.assertFalse(module.needs_refresh("2024-02-29", "2024-03", date(2024, 3, 5)))

    def test_missing_invalid_or_future_dates_require_retry(self):
        for value in (None, "", "2026-02-30", "2026-10-31"):
            self.assertTrue(module.needs_refresh(value, "2026-10", date(2026, 10, 8)))


if __name__ == "__main__":
    unittest.main()
