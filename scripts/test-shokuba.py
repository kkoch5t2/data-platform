#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from collector.collect_shokuba import normalize_row

class WorkplaceSemantics(unittest.TestCase):
    def row(self, **values):
        return {"法人番号":"1180001058333","企業名":"テスト株式会社","更新日時":"2026-10-01 12:00:00",**values}
    def test_missing_is_not_zero(self):
        self.assertIsNone(normalize_row(self.row(**{"月平均所定外労働時間":""}),"2026-10-05"))
        item=normalize_row(self.row(**{"月平均所定外労働時間":"0.0時間"}),"2026-10-05")
        self.assertEqual(item["metrics"]["overtime"]["value"],0)
    def test_wrong_unit_and_invalid_identity_rejected(self):
        self.assertIsNone(normalize_row(self.row(**{"月平均所定外労働時間":"20日"}),"2026-10-05"))
        self.assertIsNone(normalize_row(self.row(**{"法人番号":"123","月平均所定外労働時間":"20時間"}),"2026-10-05"))
    def test_source_scope_and_note_are_preserved(self):
        row=self.row(**{"年次有給休暇取得率（雇用管理区分）-取得率（一覧）":"105.2%",
          "年次有給休暇取得率（雇用管理区分）-範囲（一覧）":"2:正社員",
          "年次有給休暇取得率（雇用管理区分）-注記(一覧)":"2025年度・グループ全体"})
        m=normalize_row(row,"2026-10-05")["metrics"]["paidLeaveRateByGroup"]
        self.assertEqual(m["value"],105.2)
        self.assertEqual(m["scope"],"2:正社員")
        self.assertEqual(m["note"],"2025年度・グループ全体")
    def test_cohorts_do_not_become_calendar_years_or_rates(self):
        row=self.row(**{"新卒者の採用・定着状況(前年度/2年度前/3年度前)-男女計":"0人/7人/4人"})
        hiring=normalize_row(row,"2026-10-05")["hiring"]["graduates"]
        self.assertEqual([p["value"] for p in hiring["hires"]],[0,7,4])
        self.assertNotIn("leavers",hiring)
    def test_bad_partial_series_is_not_padded(self):
        self.assertIsNone(normalize_row(self.row(**{"新卒者の採用・定着状況(前年度/2年度前/3年度前)-男女計":"2人/—/4人"}),"2026-10-05"))

if __name__=="__main__":
    unittest.main()
