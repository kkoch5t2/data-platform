#!/usr/bin/env python3
import csv
import tempfile
import unittest
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collector.company_registry import gbiz_activity as activity


class ActivitySourceTest(unittest.TestCase):
    def test_classification_duplicates_and_missing_amount(self):
        number = "1010001016860"
        other = "2010001016860"
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            files = {}
            for kind, fieldnames, rows in (
                ("subsidy", ["法人番号", "証明日", "名称", "金額", "対象", "発行元"], [
                    [number, "2024-01-01", "A", "-100", "", "省"],
                    [number, "2024-01-01", "A", "-100", "", "省"],
                    [number, "2025-01-01", "B", "", "", "省"],
                    [other, "2025-01-01", "C", "500", "", "省"],
                ]),
                ("patent", ["法人番号", "特許/意匠/商標", "登録番号", "出願年月日",
                            "発明の名称(等)/意匠に係る物品/表示用商標", "文献固定アドレス"], [
                    [number, "特許", "123", "2020-01-01", "発明A", ""],
                    [number, "特許", "123", "2020-01-01", "発明A", ""],
                    [number, "商標", "987", "2021-01-01", "商標", ""],
                    [other, "特許", "456", "2022-01-01", "他社", ""],
                ]),
            ):
                path = root / f"{activity.SPECS[kind][0]}_UTF-8_20261005.zip"
                import io
                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerow(fieldnames)
                writer.writerows(rows)
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr("data.csv", output.getvalue().encode("utf-8-sig"))
                files[kind] = path
            with patch.object(activity, "source_path", side_effect=lambda kind: files[kind]):
                data, sources = activity.load_activity_map([number])
            self.assertEqual(set(data), {number})
            self.assertEqual(data[number]["subsidies"]["count"], 2)
            self.assertEqual(data[number]["subsidies"]["recent"][0]["amount"], None)
            self.assertEqual(data[number]["subsidies"]["recent"][1]["amount"], -100)
            self.assertEqual(data[number]["patents"]["count"], 1)
            self.assertEqual(data[number]["patents"]["recent"][0]["registration"], "123")
            self.assertEqual(sources["patent"]["sourceDate"], "2026-10-05")


if __name__ == "__main__":
    unittest.main()
