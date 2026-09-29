#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from collector import collect_yokohama_procurement as yokohama


def check(name, actual, expected):
    if actual != expected:
        raise AssertionError(f'{name}: expected={expected!r} actual={actual!r}')
    print(f'PASS {name}: {actual!r}')


def main():
    check('reiwa date', yokohama.yokohama_date('令和 6年10月28日'), '2024-10-28')
    check('blank date', yokohama.yokohama_date('null'), '')

    row = """
    <tr><td><a href="javascript:detail('2024','2435065009');">案件Ａ</a></td>
    <td>造園設計</td><td>有限会社テスト</td><td>2,750,000</td>
    <td>令和 6年10月28日</td><td>令和 6年10月21日</td>
    <td>南土木事務所</td><td>南区</td><td>指名競争</td></tr>
    """
    parsed = yokohama.result_rows(row, 2024)[0]
    check('contract', parsed['contract'], '2435065009')
    check('list amount', parsed['amount'], 2750000)

    detail = """
    <table>
      <tr><td>予定価格（税抜き：円）</td><td>2,600,000</td></tr>
      <tr><td>有限会社テスト</td><td>2,500,001</td><td></td><td></td><td></td></tr>
      <tr><td>落札</td><td></td><td></td><td></td></tr>
    </table>
    """
    check(
        'detail tax conversion',
        yokohama.detail_contract_amount(detail, '有限会社テスト'),
        2750001,
    )
    check(
        'missing detail amount',
        yokohama.detail_contract_amount('<table><tr><td>有限会社テスト</td><td></td></tr></table>', '有限会社テスト'),
        None,
    )


if __name__ == '__main__':
    main()
