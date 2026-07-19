"""Directly ingest any date range into the DB, bypassing the CLI EARLIEST_DATE floor.

The CLI refuses dates before EARLIEST_DATE (2026-01-01); that guard lives only in
the CLI's date parsing, not in the engine. This script calls the engine's
`ingest_dates()` directly so we can load the full historical archive now, without
waiting on the M8 CLI amendment. Cache-aware: dates already fetched into raw/ are
read from disk (no network); missing periods are fetched live through the same
throttled client. Idempotent per date (transactional replace), so re-runs are safe.

Usage:
  uv run python scripts/ingest_history.py START END   # inclusive, YYYY-MM-DD
  uv run python scripts/ingest_history.py 2025-01-01 2025-12-31

Skips dates already present in daily_results unless --refresh is passed.
Newest-first so recent history becomes usable soonest.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracker.api import ElexonClient  # noqa: E402
from tracker.ingest import ingest_dates  # noqa: E402
from tracker.store import TrackerStore  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "raw"
DB = ROOT / "data" / "tracker.duckdb"


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    refresh = "--refresh" in sys.argv
    start = date.fromisoformat(args[0])
    end = date.fromisoformat(args[1])

    all_dates = [
        end - timedelta(days=n) for n in range((end - start).days + 1)
    ]  # newest-first

    with TrackerStore(DB) as store:
        have = set(store.daily_result_dates(start, end)) if not refresh else set()
    todo = [d for d in all_dates if d not in have]
    print(
        f"{len(all_dates)} dates in range; {len(have)} already ingested; "
        f"{len(todo)} to do (refresh={refresh})",
        flush=True,
    )

    done = 0
    with ElexonClient(RAW) as client, TrackerStore(DB) as store:
        for d in todo:
            results = ingest_dates(client, store, [d], refresh=refresh)
            r = results[0]
            done += 1
            print(
                f"[{done}/{len(todo)}] {d.isoformat()}: "
                f"curtailment £{r.curtailment.cost_gbp:,.0f} / "
                f"{r.curtailment.volume_mwh:,.0f} MWh, "
                f"replacement £{r.turnup.cost_gbp:,.0f}, "
                f"total £{r.total_cost_gbp:,.0f}",
                flush=True,
            )
    print(f"ingest_history complete: {done} dates", flush=True)


if __name__ == "__main__":
    main()
