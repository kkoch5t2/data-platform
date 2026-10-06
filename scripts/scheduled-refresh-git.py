#!/usr/bin/env python3
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EXACT_PATHS = {
    "src/data/companies.ts",
    "src/data/organizations.ts",
    "src/data/procurements.ts",
    "src/data/summary.ts",
    "src/data/sources.json",
    "public/data/business-industry-2026.json",
    "public/data/business-industry-history.json",
    "public/data/crime-prefecture-2025.json",
    "public/data/economy-prices-history.json",
    "public/data/economy-prices.json",
    "public/data/employment-economy-2026.json",
    "public/data/employment-wage-history.json",
    "public/data/energy-consumption-history.json",
    "public/data/energy.json",
    "public/data/land-price-history.json",
    "public/data/land-prices-2026.json",
    "public/data/land-survey-2026.json",
    "public/data/municipality-stats-2026.json",
    "public/data/municipality-population-projections.json",
    "public/data/lodging-statistics.json",
    "public/data/weather/index.json",
    "public/data/poi-hospitals-2020.json",
    "public/data/poi-schools-2023.json",
    "public/data/poi-stations-2025.json",
    "public/data/regional-migration-history.json",
    "public/data/regional-trends-2026.json",
    "public/data/realestate-transactions.json",
    "public/data/site-analytics.json",
    "public/data/housing-land-2023.json",
    "public/data/municipality-social-indicators.json",
    "public/data/retail-prices-city-monthly.json",
    "public/data/traffic-accidents-2024.json",
    "public/data/wikipedia-topics.json",
    "public/data/listed-companies/index.json",
    "public/data/listed-companies/master.json",
    "public/data/listed-companies/rankings.json",
    "public/data/listed-companies/summary.json",
    "public/data/company-registry/summary.json",
    "public/data/company-registry/unlisted-index.json",
    "public/data/company-registry/name-groups.json",
}
DETAIL_PREFIXES = (
    "public/data/listed-companies/details/",
    "public/data/company-registry/details/",
)


def run(args, *, check=True, capture=True):
    return subprocess.run(args, cwd=ROOT, check=check, text=True,
                          capture_output=capture)


def git(*args):
    return run(["git", *args]).stdout.strip()


def changed_paths():
    tracked = git("diff", "--name-only", "HEAD", "--").splitlines()
    untracked = git("ls-files", "--others", "--exclude-standard").splitlines()
    return sorted(set(x for x in [*tracked, *untracked] if x))


def is_allowed(path):
    if path in EXACT_PATHS:
        return True
    if re.fullmatch(r"public/data/weather/[0-9]{2}\.json", path):
        return True
    return path.endswith(".json") and any(path.startswith(p) for p in DETAIL_PREFIXES)


def require_generated_only():
    paths = changed_paths()
    bad = [p for p in paths if not is_allowed(p)]
    if bad:
        print("ERROR: non-generated changes detected:", file=sys.stderr)
        for path in bad:
            print(f"  {path}", file=sys.stderr)
        raise SystemExit(22)
    return paths


def strip_generated_at(value):
    if isinstance(value, dict):
        return {k: strip_generated_at(v) for k, v in value.items() if k != "generatedAt"}
    if isinstance(value, list):
        return [strip_generated_at(v) for v in value]
    return value


def prune_noops():
    restored = []
    for rel in git("diff", "--name-only", "HEAD", "--", "public/data").splitlines():
        path = ROOT / rel
        if not is_allowed(rel) or path.suffix != ".json" or not path.exists():
            continue
        old = run(["git", "show", f"HEAD:{rel}"], check=False)
        if old.returncode != 0:
            continue
        try:
            before = json.loads(old.stdout)
            after = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if before == after or strip_generated_at(before) == strip_generated_at(after):
            run(["git", "restore", "--worktree", "--source=HEAD", "--", rel], capture=False)
            restored.append(rel)
    print(f"pruned generated JSON no-ops: {len(restored)}", file=sys.stderr)
    return restored


def check_start():
    branch = git("branch", "--show-current")
    if branch != "main":
        print(f"ERROR: scheduled refresh requires main branch, got {branch!r}", file=sys.stderr)
        raise SystemExit(20)
    paths = changed_paths()
    if paths:
        print("ERROR: scheduled refresh requires a clean working tree:", file=sys.stderr)
        for path in paths:
            print(f"  {path}", file=sys.stderr)
        raise SystemExit(21)
    run(["git", "fetch", "--quiet", "origin", "main"], capture=False)
    head = git("rev-parse", "HEAD")
    remote = git("rev-parse", "origin/main")
    if head != remote:
        print(f"ERROR: local main is not synchronized with origin/main\nHEAD={head}\norigin/main={remote}", file=sys.stderr)
        raise SystemExit(23)
    print(head)


def commit_push(base, date):
    prune_noops()
    paths = require_generated_only()
    run(["git", "fetch", "--quiet", "origin", "main"], capture=False)
    head = git("rev-parse", "HEAD")
    remote = git("rev-parse", "origin/main")
    if head != base or remote != base:
        print("ERROR: main changed while scheduled refresh was running", file=sys.stderr)
        print(f"base={base}\nHEAD={head}\norigin/main={remote}", file=sys.stderr)
        raise SystemExit(24)
    if not paths:
        print("NO_CHANGES")
        return
    for path in paths:
        run(["git", "add", "-A", "--", path], capture=False)
    staged = git("diff", "--cached", "--name-only", "--").splitlines()
    bad = [p for p in staged if not is_allowed(p)]
    if bad:
        print("ERROR: staged non-generated files:", file=sys.stderr)
        for path in bad:
            print(f"  {path}", file=sys.stderr)
        raise SystemExit(25)
    if git("diff", "--name-only", "--") or git("ls-files", "--others", "--exclude-standard"):
        print("ERROR: unstaged changes remain after staging generated files", file=sys.stderr)
        raise SystemExit(26)
    run(["git", "diff", "--cached", "--check"], capture=False)
    if run(["git", "diff", "--cached", "--quiet"], check=False).returncode == 0:
        print("NO_CHANGES")
        return
    message = f"chore(data): scheduled refresh {date}"
    run(["git", "commit", "-m", message], capture=False)
    run(["git", "push", "origin", "main"], capture=False)
    run(["git", "fetch", "--quiet", "origin", "main"], capture=False)
    new_head = git("rev-parse", "HEAD")
    remote = git("rev-parse", "origin/main")
    if new_head != remote or changed_paths():
        print("ERROR: repository is not clean/synchronized after scheduled push", file=sys.stderr)
        raise SystemExit(27)
    print(new_head)


def check_clean():
    paths = changed_paths()
    if paths:
        print("ERROR: working tree is not clean:", file=sys.stderr)
        for path in paths:
            print(f"  {path}", file=sys.stderr)
        raise SystemExit(28)
    print("CLEAN")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check-start")
    sub.add_parser("prune-noops")
    sub.add_parser("check-generated")
    sub.add_parser("check-clean")
    commit = sub.add_parser("commit-push")
    commit.add_argument("--base", required=True)
    commit.add_argument("--date", required=True)
    args = parser.parse_args()
    if args.command == "check-start": check_start()
    elif args.command == "prune-noops": prune_noops()
    elif args.command == "check-generated": require_generated_only()
    elif args.command == "check-clean": check_clean()
    elif args.command == "commit-push": commit_push(args.base, args.date)


if __name__ == "__main__":
    main()
