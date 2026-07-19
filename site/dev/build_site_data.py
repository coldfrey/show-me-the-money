"""Build site/data/ from the engine's REAL validated exports.

Replaces the earlier preview aggregate: now that Phase B (M5) attribution is
implemented, the engine's `tracker export` / `export-summary` produce the exact
§8 contract JSON with genuine per-station and per-company figures. This script
just runs those commands and stages their output for the static site:

  1. tracker export --from <min> --to <max>   -> out/daily/*.json
  2. tracker export-summary --allow-missing    -> out/summary.json
  3. copy out/* into site/data/ and write dates.json (local-nav manifest)

Usage: uv run python site/dev/build_site_data.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "out"
SITE_DATA = ROOT / "site" / "data"


def ingested_range() -> tuple[str, str]:
    tmp = Path(tempfile.mkdtemp())
    shutil.copy(ROOT / "data" / "tracker.duckdb", tmp / "t.duckdb")
    wal = ROOT / "data" / "tracker.duckdb.wal"
    if wal.exists():
        shutil.copy(wal, tmp / "t.duckdb.wal")
    con = duckdb.connect(str(tmp / "t.duckdb"), read_only=True)
    lo, hi = con.execute("select min(date), max(date) from daily_results").fetchone()
    return lo.isoformat(), hi.isoformat()


def run(*args: str) -> None:
    subprocess.run(["uv", "run", "tracker", *args], cwd=ROOT, check=True)


def main() -> None:
    lo, hi = ingested_range()
    print(f"exporting {lo} -> {hi}")
    run("export", "--from", lo, "--to", hi)
    run("export-summary", "--allow-missing")

    SITE_DATA.mkdir(parents=True, exist_ok=True)
    (SITE_DATA / "daily").mkdir(exist_ok=True)
    shutil.copy(OUT / "summary.json", SITE_DATA / "summary.json")
    dates = []
    for src in sorted((OUT / "daily").glob("*.json")):
        shutil.copy(src, SITE_DATA / "daily" / src.name)
        dates.append(src.stem)
    (SITE_DATA / "dates.json").write_text(json.dumps(dates))
    print(f"staged {len(dates)} daily files + summary.json to {SITE_DATA}", file=sys.stderr)


if __name__ == "__main__":
    main()
