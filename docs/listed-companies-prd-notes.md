# Listed Companies / PRD implementation notes

## Product rule
The UI is Japanese and targets Japanese users. The English PRD is an implementation brief only.
Financial figures use Japanese units (万円・億円・兆円); negative accounting values use red, non-negative values use black.
Never estimate a missing company-specific value merely to fill a chart.

## Primary sources
- JPX TSE listed issues: company/security master, market and industry classification.
- EDINET code list: EDINET code, corporate number, filer metadata.
- EDINET API v2: annual securities reports, amendments, extraordinary reports, XBRL/converted CSV.
- Other public sources may be added only after source/licence/coverage QA.

## PRD feasibility
- FR-1.1 Segment profitability treemap: PARTIAL. Revenue/profit by segment is available for many issuers, but XBRL dimensions and segment concepts vary. Enable only for issuers/years where segment identity and values can be verified.
- FR-1.2 Competitive scatter: SUPPORTED for verified metrics such as revenue growth, operating margin, ROE and average annual salary. Company logos are not assumed to be freely redistributable; use standard points/labels unless a reliable licensed logo source is established.
- FR-2.1 10-year financial timeline: SUPPORTED from EDINET annual filings. Event pins are PARTIAL: TDnet API is a paid JPX service and cannot be a required dependency under DATLUME's no-added-paid-service policy. EDINET extraordinary reports can cover only part of the event history.
- FR-3.1 Salary curve: NOT implemented as specified. EDINET commonly provides company-wide average salary, age and tenure, not age-band median and 25th/75th percentile salary distributions. DATLUME will not fabricate those distributions.
- FR-3.2 Attrition/hiring waterfall: NOT implemented as a universal company metric. Public disclosures are not standardized enough to derive total hires and total departures for every listed company. Partial MHLW/employer disclosures may be added later with explicit coverage labels.
- FR-4.1 Capital network: PARTIAL/FUTURE. EDINET contains major-shareholder and subsidiary information, but relation extraction and historical ownership percentages require dedicated normalization and source QA. Only verified edges may be shown.

## Accounting rules
Prefer consolidated facts; use non-consolidated facts only when consolidated financial statements do not exist. Keep accounting standard, fiscal period, context, unit and EDINET document ID. Handle amended filings explicitly. Do not select a value merely because its tag name contains a keyword such as Revenue.
Banks, insurers, securities firms and other financial companies require sector-aware metrics and must not be interpreted using generic leverage/profitability semantics.

## Ubuntu secret / update operation
EDINET API authentication is read from `EDINET_API_KEY` or, for always-on Ubuntu operation, `~/.config/datlume/edinet_api_key` (mode 0600). The key must never be committed, logged, or written under `public/`.
Daily collection should scan only the new submission date; `documents-index.json` merges by EDINET document ID so historical coverage is retained. Raw archives remain under gitignored `data/raw/listed-companies/`. Public compact indexes are generated with `npm run build:listed-data`. When EDINET converted CSV is unavailable despite `csvFlag=1`, download the original XBRL with `npm run collect:listed-fallback`; normalization prefers CSV and falls back to original XBRL facts. For normal daily operation, `npm run refresh:listed-daily` scans the current date, downloads only missing archives with automatic CSV→XBRL fallback, normalizes only new or replaced company-year records, and rebuilds compact public data.
