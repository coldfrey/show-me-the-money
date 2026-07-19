# Progress

[x] M0: scaffold, CLI help smoke test, and project configuration
[x] M1: typed API client, retry/pacing policy, atomic raw cache, and fetch CLI
[x] M1: mock-transport cache, retry, pacing, 404, and schema tests
[x] M2: pure curtailment, turn-up stack walk, and daily result calculations
[x] M2: all specified replication edge-case tests

2026-07-19 — M0 complete: `uv run tracker --help` exited 0; pytest collected
and passed 1 test; ruff check/format and mypy all passed.

2026-07-19 — M1 complete: 6 API tests passed; full suite passed 7 tests;
ruff check/format and mypy passed; live `tracker fetch --date 2026-07-10`
exited 0 and populated 100 raw cache files.

2026-07-19 — M2 complete: 11 replication tests passed (including every named
edge case); full suite passed 18 tests; ruff check/format and mypy passed.

Next up: M3 DuckDB store, ingest/show commands, date bounds, and idempotency.
