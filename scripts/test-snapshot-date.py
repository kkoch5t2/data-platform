import sys,unittest
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from collector.core.snapshot_date import snapshot_date
class Tests(unittest.TestCase):
    def test_old_snapshot_does_not_move_at_midnight(self):
        dates=['2026-10-07','2026-10-09']
        cutoff=snapshot_date('2026-10-07T23:37:57+00:00',datetime(2026,10,9,tzinfo=timezone.utc))
        self.assertEqual(cutoff,'2026-10-08')
        self.assertEqual(max(d for d in dates if d<=cutoff),'2026-10-07')
    def test_jst_boundary_not_utc_day(self):
        self.assertEqual(snapshot_date('2026-10-07T15:00:00Z'),'2026-10-08')
        self.assertEqual(snapshot_date('2026-10-07T14:59:59Z'),'2026-10-07')
    def test_invalid_naive_and_future_are_rejected(self):
        for value in ('invalid','2026-10-08T00:00:00','2099-01-01T00:00:00Z'):
            with self.assertRaises(ValueError):snapshot_date(value)
if __name__=='__main__':unittest.main()
