#!/usr/bin/env python3
"""Read-only operations report; collection time is never treated as a source period."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
JST = ZoneInfo("Asia/Tokyo")
PERIOD_KEYS = ("sourceDate", "latestDate", "lastDate", "latestMonth", "latestPeriod",
               "year", "wageYear", "startYear", "endYear", "startDate", "endDate")


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone missing")
    return parsed


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def build_report(root, now=None):
    root = Path(root)
    now = now or datetime.now(timezone.utc)
    issues, rows = [], []
    catalog = load(root / "collector/source_catalog.json")["sources"]
    statuses = load(root / "src/data/sources.json")["sources"]
    for key, cfg in sorted(catalog.items()):
        if not cfg.get("enabled"):
            continue
        item = statuses.get(key, {})
        metrics = item.get("metrics") or {}
        problems, completed, age = [], None, None
        if item.get("status") != "ok":
            problems.append("収集成功を確認できない")
        try:
            completed = timestamp(item["finishedAt"])
            age = round((now - completed).total_seconds() / 3600, 1)
            if completed > now + timedelta(minutes=10):
                problems.append("収集日時が未来")
            if (now - completed).total_seconds() > cfg.get("maxAgeHours", 48) * 3600:
                problems.append("収集期限超過")
            if item.get("startedAt") and timestamp(item["startedAt"]) > completed:
                problems.append("開始・終了日時が逆転")
        except (KeyError, ValueError, TypeError, AttributeError):
            problems.append("収集日時が不正または未記録")
        count = metrics.get("records")
        if not isinstance(count, (int, float)) or isinstance(count, bool) or count < cfg.get("minRecords", 1):
            problems.append("件数不足または未記録")
        issues.extend(f"{key}: {problem}" for problem in problems)
        rows.append({"id": key, "label": cfg.get("label", key),
                     "frequency": cfg.get("frequency"), "status": "要確認" if problems else "正常",
                     "collectedAt": completed.astimezone(JST).isoformat() if completed else None,
                     "ageHours": age, "records": count,
                     "sourcePeriod": {k: metrics[k] for k in PERIOD_KEYS if k in metrics},
                     "issues": problems})
    state = root / "data/automation"
    jobs = {}
    for job, marker in (("daily", "last-success-date"), ("topics", "last-wikipedia-success-date"),
                        ("weekly", "last-weekly-success-date")):
        path = state / marker
        jobs[job] = {"lastVerifiedDate": path.read_text().strip() if path.exists() else None}
    for job in ("daily", "topics"):
        try:
            successful = datetime.strptime(jobs[job]["lastVerifiedDate"], "%Y-%m-%d").date()
            today = now.astimezone(JST).date()
            if successful > today or successful < today - timedelta(days=1):
                issues.append(f"{job}: 公開成功日が古いまたは未来")
        except (ValueError, TypeError):
            issues.append(f"{job}: 公開成功日が不正または未記録")
    try:
        successful = datetime.strptime(jobs["weekly"]["lastVerifiedDate"], "%Y-%m-%d").date()
        today = now.astimezone(JST).date()
        if successful > today or successful < today - timedelta(days=8):
            issues.append("weekly: 監査成功日が古いまたは未来")
    except (ValueError, TypeError):
        issues.append("weekly: 監査成功日が不正または未記録")
    # A recent marker must not hide a later failure in the same week/day.
    failures = state / "weekly-audit-logs/failures.log"
    if failures.exists():
        lines = [line for line in failures.read_text().splitlines() if line.strip()]
        if lines:
            try:
                failed_at = timestamp(lines[-1].split("\t", 1)[0])
                jobs["weekly"]["lastFailureAt"] = failed_at.astimezone(JST).isoformat()
                successful_at = None
                marker = jobs["weekly"]["lastVerifiedDate"]
                log = state / "weekly-audit-logs" / f"{marker}.log"
                prefix = "=== weekly refresh verified success "
                if log.exists():
                    for line in log.read_text().splitlines():
                        if line.startswith(prefix):
                            successful_at = timestamp(line[len(prefix):].removesuffix(" ==="))
                if successful_at:
                    jobs["weekly"]["lastVerifiedAt"] = successful_at.astimezone(JST).isoformat()
                    if failed_at > successful_at:
                        issues.append("weekly: 前回成功後に監査が失敗")
                elif marker is None or failed_at.astimezone(JST).date().isoformat() >= marker:
                    issues.append("weekly: 失敗後の監査成功を確認できない")
            except (ValueError, TypeError, AttributeError):
                issues.append("weekly: 監査失敗履歴の日時が不正")
    # Read the latest verified history; newer code commits alone do not imply a deployment.
    latest = None
    history = state / "history.jsonl"
    if history.exists():
        for line in history.read_text().splitlines():
            try:
                entry = json.loads(line)
                if entry.get("verified") is True and entry.get("job") in ("daily", "topics"):
                    if latest is None or timestamp(entry["finishedAt"]) > timestamp(latest["finishedAt"]):
                        latest = entry
            except (ValueError, KeyError, TypeError, AttributeError):
                issues.append("成功履歴に不正な行")
    verification = None
    try:
        verification = load(state / "last-production-verification.json")
        if verification.get("ok") is not True:
            issues.append("最後の本番照合が未成功")
        if not latest:
            issues.append("公開成功履歴が未記録")
        elif verification.get("commit") != latest.get("commit"):
            issues.append("本番照合と最新公開成功履歴のコミットが不一致")
        timestamp(verification["verifiedAt"])
        if not verification.get("releaseId"):
            issues.append("本番リリースIDが未記録")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        issues.append("本番照合記録が不正または未記録")
    return {"schemaVersion": 1, "checkedAt": now.astimezone(JST).isoformat(),
            "ok": not issues, "sources": rows, "jobs": jobs,
            "lastPublication": latest, "productionVerification": verification,
            "issues": issues,
            "note": "収集日時・元データの対象年月・公開確認日時は別。対象年月の未記録は推測しない。本番照合は保存記録であり、現在の通信確認ではない。"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--check", action="store_true", help="exit 1 when recorded state needs review")
    args = parser.parse_args()
    try:
        report = build_report(args.root)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        report = {"ok": False, "issues": [f"運用レポートを生成できない: {type(exc).__name__}"]}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("DATLUME 更新状況: " + ("正常" if report["ok"] else "要確認"))
        print("収集状態 | ソース | 収集日時(JST) | 件数 | 元データ対象(記録値)")
        for row in report.get("sources", []):
            period = ", ".join(f"{k}={v}" for k, v in row["sourcePeriod"].items()) or "未記録"
            print(f'{row["status"]} | {row["id"]} | {row["collectedAt"] or "未記録"} | {row["records"]} | {period}')
        for job, value in report.get("jobs", {}).items():
            print(f'{job} {"監査成功日" if job == "weekly" else "本番確認成功日"}: {value["lastVerifiedDate"] or "未記録"}')
        value = report.get("productionVerification") or {}
        print(f'最後の本番照合: {value.get("verifiedAt", "未記録")} / release={value.get("releaseId", "未記録")}')
        print(report.get("note", ""))
        for issue in report["issues"]:
            print("要確認: " + issue)
    if args.check and not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
