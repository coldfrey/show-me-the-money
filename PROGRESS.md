# Progress

[x] M0: scaffold, CLI help smoke test, and project configuration
[x] M1: typed API client, retry/pacing policy, atomic raw cache, and fetch CLI
[x] M1: mock-transport cache, retry, pacing, 404, and schema tests
[x] M2: pure curtailment, turn-up stack walk, and daily result calculations
[x] M2: all specified replication edge-case tests
[x] M3: DuckDB schemas and transactional per-date replacement
[x] M3: cache-aware ingest/show orchestration and validated date ranges
[x] M3: zero-HTTP cached idempotency and date-bound tests
[x] M4: complete-month validation, four metrics, waivers, and unit tests
[x] M4: preserve live null-BMU stack rows as unknown fuel
[x] M4: live May and June wastedwind.energy validation
[x] M5: pure SO offer/wind attribution and per-BMU DuckDB tables
[x] M5: zero-HTTP recompute, deterministic owner mapping, and leaderboards
[x] M5: attribution and owner-fallback unit tests

2026-07-19 — M0 complete: `uv run tracker --help` exited 0; pytest collected
and passed 1 test; ruff check/format and mypy all passed.

2026-07-19 — M1 complete: 6 API tests passed; full suite passed 7 tests;
ruff check/format and mypy passed; live `tracker fetch --date 2026-07-10`
exited 0 and populated 100 raw cache files.

2026-07-19 — M2 complete: 11 replication tests passed (including every named
edge case); full suite passed 18 tests; ruff check/format and mypy passed.

2026-07-19 — M3 complete: 3 store tests passed; full suite passed 25 tests;
ruff check/format and mypy passed. Live ingest/show for 2026-07-10 produced
curtailment £1,023.581667 / 70.108333 MWh, replacement £8,678.336989 /
70.108333 MWh, total £9,701.918656. Cached re-ingest test reproduced all five
calculated values and the 2-row fixture stack exactly with zero HTTP.

2026-07-19 — M4 complete: live June deviations were bidCost 0.000000%,
bidVolumeMWh 0.000000%, turnUpCost 0.020175%, turnUpVolume 0.000000%; live May
deviations were 0.106412%, 0.127244%, 0.120229%, and 0.128725% respectively.
Both commands exited 0 with no waivers; 6,200 May/June stack responses are
cached for offline reproduction.

Next up: M5 recompute all stored dates, seed `data/owners.csv`, and run the
live deterministic leaderboard acceptance.
