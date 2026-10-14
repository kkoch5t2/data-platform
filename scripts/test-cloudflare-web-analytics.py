#!/usr/bin/env python3
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('analytics',Path(__file__).with_name('cloudflare_web_analytics.py'))
analytics=importlib.util.module_from_spec(spec)
spec.loader.exec_module(analytics)


class AnalyticsTests(unittest.TestCase):
    def test_daily_queries_cover_rolling_window_without_overlap(self):
        calls=[]
        def graphql(query, variables):
            f=variables['filter']
            calls.append((f['datetime_geq'],f['datetime_lt']))
            date=f['datetime_geq'][:10]
            return {'viewer':{'accounts':[{'daily':[{
                'count':12,'sum':{'visits':3},'dimensions':{'date':date}
            }]}]}}
        start=datetime(2026,10,6,22,1,25,tzinfo=timezone.utc)
        end=datetime(2026,10,8,7,1,25,tzinfo=timezone.utc)
        with patch.object(analytics,'graphql',side_effect=graphql):
            rows=analytics.fetch_daily(start,end,'site')
        self.assertEqual(calls,[
            ('2026-10-06T22:01:25Z','2026-10-07T00:00:00Z'),
            ('2026-10-07T00:00:00Z','2026-10-08T00:00:00Z'),
            ('2026-10-08T00:00:00Z','2026-10-08T07:01:25Z')])
        self.assertEqual([r['date'] for r in rows],['2026-10-06','2026-10-07','2026-10-08'])
        self.assertEqual(sum(r['pageviews'] for r in rows),36)

    def test_rejects_wrong_date_group(self):
        response={'viewer':{'accounts':[{'daily':[{
            'count':1,'sum':{'visits':1},'dimensions':{'date':'2026-10-08'}
        }]}]}}
        with patch.object(analytics,'graphql',return_value=response):
            with self.assertRaisesRegex(RuntimeError,'Unexpected'):
                analytics.fetch_daily(datetime(2026,10,7,tzinfo=timezone.utc),
                                      datetime(2026,10,8,tzinfo=timezone.utc),'site')

    def test_full_day_history_survives_partial_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'site-analytics.json'
            path.write_text(json.dumps({'history':[{'date':'2026-10-06','pageviews':596,'visits':126}]}))
            report={'range':{'start':'2026-10-06T22:01:25Z','end':'2026-10-13T22:01:25Z'},
                    'daily':[{'date':'2026-10-06','pageviews':278,'visits':56},
                             {'date':'2026-10-13','pageviews':267,'visits':63}],
                    'pageviews':545,'visits':119}
            saved=analytics.save_report(report,path)
            history={x['date']:x for x in saved['history']}
            self.assertEqual(history['2026-10-06']['pageviews'],596)
            self.assertEqual(history['2026-10-13']['pageviews'],267)


if __name__=='__main__':
    unittest.main()
