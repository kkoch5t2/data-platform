#!/usr/bin/env python3
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from collector import collect_jetro as jetro

def check(name, actual, expected):
    if actual != expected:
        raise AssertionError(f'{name}: expected={expected!r} actual={actual!r}')
    print(f'PASS {name}: {actual!r}')

def main():
    check('normal yen', jetro.parse_yen('35,970,000円'), 35970000)
    check('unit price excluded', jetro.parse_yen('単価 118.00円'), None)
    check('decimal total excluded', jetro.parse_yen('118.00円'), None)
    check('foreign currency excluded', jetro.parse_yen('USD 2,500.00'), None)
    check('bare yen amount', jetro.parse_yen('52,800,000'), 52800000)
    check('mixed grouped separators', jetro.parse_yen('102,300.000円'), 102300000)
    check('total plus unit price', jetro.parse_yen('2,010,624円（総価）、0.9円（複数単価）'), 2010624)

    normal = '①71 ②正常案件 一式 ③購入等 ④一般 ⑤7.12.2 ⑥株式会社テスト 東京都 ⑦35,970,000円 ⑧7.10.10 ⑪最低価格 ⑫36,088,492円'
    block = jetro.choose_detail_block(jetro.extract_numbered_fields(normal), '正常案件 一式')
    check('normal marker amount', jetro.parse_yen(block.get('⑦')), 35970000)

    malformed = '①71 ②異常案件 一式 ③購入等 ④一般 ⑤7.12.2 ⑥株式会社テスト 東京都 ③35,970,000円 ⑧7.10.10 ⑪最低価格 ⑫36,088,492円'
    block = jetro.choose_detail_block(jetro.extract_numbered_fields(malformed), '異常案件 一式')
    check('duplicate marker amount', jetro.parse_yen(block.get('⑦')), 35970000)
    check('amount status total', jetro.award_amount_status({'awardAmount': 100, 'detailFetched': True}), 'total')
    check('amount status not fetched', jetro.award_amount_status({'awardAmount': None, 'detailFetched': False}), 'notFetched')
    check('amount status unit price', jetro.award_amount_status({'awardAmount': None, 'detailFetched': True, 'detailText': '123円（単価）'}), 'unitPrice')
    check('amount status foreign', jetro.award_amount_status({'awardAmount': None, 'detailFetched': True, 'detailText': 'USD 1,000'}), 'foreignCurrency')
    check('amount status no award', jetro.award_amount_status({'awardAmount': None, 'detailFetched': True, 'detailText': '不調'}), 'noAward')
    check('amount status unpublished', jetro.award_amount_status({'awardAmount': None, 'detailFetched': True, 'detailText': '価格記載なし'}), 'notPublished')

    class TimeoutTwice:
        def __init__(self):
            self.calls = 0

        def open(self, request, timeout):
            self.calls += 1
            if self.calls < 3:
                raise TimeoutError('temporary read timeout')
            return 'response'

    opener = TimeoutTwice()
    with patch.object(jetro.time, 'sleep'):
        check('network timeout retry result', jetro.open_with_retry(opener, object()), 'response')
    check('network timeout retry calls', opener.calls, 3)

if __name__ == '__main__':
    main()
