from __future__ import annotations

# Corrections are only added after the filing presentation and a later annual
# report's prior-year disclosure make the source-scale defect deterministic.
# `expected` guards against silently overriding a future EDINET correction.
CORRECTIONS = {
    ("S100PUH1", "averageSalary"): {
        "expected": 381000, "value": None, "evidenceDocID": "S100SJMP",
        "reason": "2022年有報は381千円と原典にも記載されるが、前後年は約500万円台。正確な訂正値を確定できないため推測補正せず欠損扱い。",
    },
    ("S100TYBD", "averageSalary"): {
        "expected": 500000, "value": None, "evidenceDocID": "S100W9WY",
        "reason": "2024年有報は500千円と原典にも記載されるが、前後年は400〜500万円台。正確な訂正値を確定できないため推測補正せず欠損扱い。",
    },
    ("S100W6AS", "averageSalary"): {
        "expected": 598000, "value": 5980000, "evidenceDocID": "S100YN9T",
        "reason": "2025年有報は598千円だが、前後年は約590万円台で、2026年有報の6,080千円・前年比101.7%から前期5,980千円と確定。",
    },
    ("S1009ZEM", "employees"): {
        "expected": 351000, "value": 351, "evidenceDocID": "S100CPB9",
        "reason": "翌年有報の前期従業員数351人で、当年CSVの351000が桁異常と確定。",
    },
    ("S100GA3F", "sharesOutstanding"): {
        "expected": 4450000000, "value": 4450000, "evidenceDocID": "S100J0QX",
        "reason": "翌年有報は前期4,450千株。2019年タグ値のみ1000倍。",
    },
    ("S100R1FN", "sharesOutstanding"): {
        "expected": 72088, "value": 72088000, "evidenceDocID": "S100TSZ6",
        "reason": "表示単位が千株で、翌年有報も前期72,088千株と確認。",
    },
    ("S100G5PK", "revenue"): {
        "expected": 54752724000000, "value": 54752724000, "evidenceDocID": "S100IYAJ",
        "reason": "2019年表示値が1000倍スケール。翌年有報は前期54,752百万円。",
    },
    ("S100G5PK", "operatingCashFlow"): {
        "expected": 4055383000000, "value": 4055383000, "evidenceDocID": "S100IYAJ",
        "reason": "2019年表示値が1000倍スケール。翌年有報は前期4,055百万円。",
    },
    ("S100G5PK", "netIncome"): {
        "expected": 2209141000000, "value": 2209141000, "evidenceDocID": "S100IYAJ",
        "reason": "2019年表示値が1000倍スケール。翌年有報は前期2,209百万円。",
    },
    ("S100G5PK", "investingCashFlow"): {
        "expected": -3847725000000, "value": -3847725000, "evidenceDocID": "S100IYAJ",
        "reason": "2019年表示値が1000倍スケール。翌年有報は前期-3,847百万円。",
    },
    ("S100G5PK", "financingCashFlow"): {
        "expected": 2270633000000, "value": 2270633000, "evidenceDocID": "S100IYAJ",
        "reason": "2019年表示値が1000倍スケール。翌年有報は前期2,270百万円。",
    },
    ("S100DHS5", "operatingCashFlow"): {
        "expected": -279000, "value": -279010000, "evidenceDocID": "S100G9QB",
        "reason": "翌年有報の前期値-279,010千円と現金残高推移から当年タグの欠落桁を確定。",
    },
    ("S100DHS5", "investingCashFlow"): {
        "expected": 124000, "value": 124737000, "evidenceDocID": "S100G9QB",
        "reason": "翌年有報の前期値124,737千円で当年タグの欠落桁を確定。",
    },
    ("S100DHS5", "financingCashFlow"): {
        "expected": -93000, "value": -93008000, "evidenceDocID": "S100G9QB",
        "reason": "翌年有報の前期値-93,008千円で当年タグの欠落桁を確定。",
    },
}


def apply_verified_source_corrections(doc_id: str, metrics: dict, sources: dict) -> list[dict]:
    warnings: list[dict] = []
    for (wanted_doc, metric), correction in CORRECTIONS.items():
        if wanted_doc != doc_id:
            continue
        current = metrics.get(metric)
        if current == correction["value"]:
            continue
        if current != correction["expected"]:
            raise RuntimeError(
                f"verified correction source changed: {doc_id} {metric} "
                f"expected={correction['expected']} actual={current}"
            )
        metrics[metric] = correction["value"]
        source = sources.get(metric)
        if source is not None:
            source["validatedCorrection"] = {
                "originalValue": current,
                "correctedValue": correction["value"],
                "evidenceDocID": correction["evidenceDocID"],
                "reason": correction["reason"],
            }
        warnings.append({
            "type": "validatedSourceCorrection",
            "metric": metric,
            "originalValue": current,
            "correctedValue": correction["value"],
        })
    return warnings
