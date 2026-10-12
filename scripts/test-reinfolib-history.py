import gzip,io,json,sys,tempfile,unittest,urllib.error
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import collector.backfill_reinfolib_history as history
class Response:
    headers={}
    def __init__(self,data):self.data=data
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self):return json.dumps(self.data).encode()
class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.patch=patch.object(history,'CACHE',Path(self.tmp.name));self.patch.start();self.addCleanup(self.patch.stop)
    def test_official_no_results_is_cached_but_other_404_is_failure(self):
        error=lambda message:urllib.error.HTTPError('https://example.invalid',404,'not found',{},io.BytesIO(json.dumps({'message':message}).encode()))
        with patch.object(history.urllib.request,'urlopen',side_effect=lambda *a,**k:(_ for _ in ()).throw(error('検索結果がありません。'))):
            self.assertEqual(history.fetch(2005,'02','test')['data'],[])
        with patch.object(history.urllib.request,'urlopen',side_effect=AssertionError('cache must avoid request')):
            self.assertEqual(history.fetch(2005,'02','test')['httpStatus'],404)
        with patch.object(history.urllib.request,'urlopen',side_effect=lambda *a,**k:(_ for _ in ()).throw(error('unknown error'))),patch.object(history.time,'sleep'):
            with self.assertRaises(RuntimeError):history.fetch(2005,'03','test')
    def test_wrong_year_region_and_price_category_stop_collection(self):
        good={'Period':'2005年第3四半期','MunicipalityCode':'13101','PriceCategory':'不動産取引価格情報'}
        for changes in ({'Period':'2006年第3四半期'},{'MunicipalityCode':'14101'},{'PriceCategory':'成約価格情報'}):
            with patch.object(history.urllib.request,'urlopen',return_value=Response({'status':'OK','data':[{**good,**changes}]})):
                with self.assertRaises(ValueError):history.fetch(2005,'13','test')
    def test_retry_uses_successful_prefecture_cache_only_for_current_day(self):
        path=history.CACHE/'2026'/'13.json.gz';path.parent.mkdir(parents=True)
        payload={'fetchedAt':datetime.now(timezone.utc).isoformat(),'data':[]}
        with gzip.open(path,'wt',encoding='utf-8') as stream:json.dump(payload,stream)
        with patch.object(history.urllib.request,'urlopen',side_effect=AssertionError('must not refetch successful source')):
            self.assertEqual(history.fetch(2026,'13','test',refresh=True),payload)
        payload['fetchedAt']='2026-01-01T00:00:00+00:00'
        with gzip.open(path,'wt',encoding='utf-8') as stream:json.dump(payload,stream)
        with patch.object(history.urllib.request,'urlopen',return_value=Response({'status':'OK','data':[]})) as opener:
            history.fetch(2026,'13','test',refresh=True)
            opener.assert_called_once()

    def test_unchanged_shard_and_index_preserve_matching_bytes(self):
        path=history.CACHE/'index.json'
        history.write(path,{'generatedAt':'old','value':42})
        before=path.read_bytes()
        history.write(path,{'generatedAt':'new','value':42})
        self.assertEqual(path.read_bytes(),before)
        history.write(path,{'generatedAt':'new','value':43})
        self.assertNotEqual(path.read_bytes(),before)

    def test_median_sample_size_excludes_missing_unit_prices(self):
        rows=[{'segment':'land','tradePrice':v,'unitValue':u,'area':10,'floorArea':None} for v,u in [(100,10),(200,None),(300,30),(400,None),(500,None)]]
        result=history.compact(rows)['land']
        self.assertEqual(result['count'],5)
        self.assertEqual(result['medianTradePrice'],300)
        self.assertEqual(result['medianUnitPrice'],20)
        self.assertEqual(result['validCounts']['medianUnitPrice'],2)
        self.assertEqual(result['validCounts']['medianTradePrice'],5)
if __name__=='__main__':unittest.main()
