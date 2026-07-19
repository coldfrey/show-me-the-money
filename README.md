# Show Me The Money

A Python 3.12 batch engine for Great Britain's Balancing Mechanism constraint
costs. It reproduces wastedwind.energy's replacement-cost calculation and adds
per-station and parent-company attribution for SO-flagged payments.

## Local use

Install the locked environment and inspect the CLI:

```sh
uv sync --frozen
uv run tracker --help
```

Typical commands:

```sh
uv run tracker ingest --date 2026-07-10
uv run tracker show --date 2026-07-10
uv run tracker validate --year 2026 --month 6
uv run tracker leaderboard --from 2026-06-01 --to 2026-06-30 --side turnup --by company --json
uv run tracker export --date 2026-07-10
uv run tracker export-summary --allow-missing
```

Raw API responses under `raw/` are the reproducible source of truth. The
DuckDB state is `data/tracker.duckdb`; public JSON is written under `out/`.

## Scheduled R2 publication

`.github/workflows/daily.yml` runs at 06:30 UTC. It restores state with
non-destructive `rclone copy`, backfills missing dates, refreshes the trailing
revision window, writes strict exports, then copies state and public JSON back
to Cloudflare R2. Missing secrets produce a visible warning and a successful
compute-only run.

Configure these GitHub Actions secrets:

- `R2_ACCOUNT_ID`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`

The bucket layout is:

```text
constraint-tracker/
├── daily/YYYY-MM-DD.json
├── summary.json
└── state/
    ├── raw/
    └── tracker.duckdb
```

State restore and publication always use `rclone copy`, never `sync`, so a
fresh runner cannot delete historical cache or exports from R2.
