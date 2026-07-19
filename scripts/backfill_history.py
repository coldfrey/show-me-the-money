"""Deep historical backfill of the raw Elexon cache, 2025 -> 2015.

Uses the engine's ElexonClient (same pacing lock, retries, and cache layout
as the CLI) but bypasses the CLI's EARLIEST_DATE floor, which is 2026-01-01
pending a spec amendment. Fetch-only: no DB writes, safe to run alongside
engine DB work. Newest-first so recent years become usable soonest.

Usage: uv run python scripts/backfill_history.py [start_date [end_date]]
Progress: one line per completed date on stdout; resumable (cache hits skip).
"""

from __future__ import annotations

import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracker.api import ElexonClient  # noqa: E402

RAW = Path(__file__).resolve().parents[1] / "raw"
NEWEST = date(2025, 12, 31)
OLDEST = date(2015, 1, 1)


def main() -> None:
    newest = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else NEWEST
    oldest = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else OLDEST
    with ElexonClient(RAW) as client:
        d = newest
        while d >= oldest:
            t0 = time.monotonic()
            rows = 0
            for period in range(1, 51):
                rows += len(client.bid_stack(d, period))
                rows += len(client.offer_stack(d, period))
            print(
                f"{d.isoformat()} done: {rows} rows in {time.monotonic() - t0:.0f}s",
                flush=True,
            )
            d -= timedelta(days=1)
    print("history backfill complete", flush=True)


if __name__ == "__main__":
    main()
