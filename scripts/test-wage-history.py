#!/usr/bin/env python3
import copy,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from collector.collect_employment_wage_history import parse_table
from collector.collect_employment_economy import PREFECTURE_ORDER
def fixture():
    rows=[['都道府県 男女計','','','','','','','','現金','所定内','年間賞与',''],
          ['','','','','歳','年','時間','時間','千円','千円','千円','十人']]
    rows += [['','',p,'',40,12,160,10,300,280,800,100] for p in PREFECTURE_ORDER]
    return rows
class WageTest(unittest.TestCase):
    def run_rows(self,rows):
        with patch('collector.collect_employment_wage_history.table_rows',return_value=rows):return parse_table(b'')
    def test_valid(self):
        data=self.run_rows(fixture());self.assertEqual(data['東京都'],[300,280,800,4400,40,12,160,10]);self.assertEqual(len(data),47)
    def test_duplicate(self):
        rows=fixture();rows.append(rows[-1])
        with self.assertRaises(ValueError):self.run_rows(rows)
    def test_missing(self):
        for column in range(4,12):
            rows=fixture();rows[2][column]='-'
            with self.assertRaises(ValueError):self.run_rows(rows)
    def test_units(self):
        rows=fixture();rows[1][8]='円'
        with self.assertRaises(ValueError):self.run_rows(rows)
    def test_scope(self):
        rows=fixture();rows[0][0]='都道府県 男'
        with self.assertRaises(ValueError):self.run_rows(rows)
    def test_incomplete(self):
        with self.assertRaises(ValueError):self.run_rows(fixture()[:-1])
if __name__=='__main__':unittest.main()
