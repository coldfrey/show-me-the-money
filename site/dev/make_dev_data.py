"""Generate dev preview JSON for the site from the local DuckDB.

Produces files conforming to SPEC.md §8 (the frozen export contract) under
site/data/. Daily and monthly headline figures are the engine's real computed
numbers (daily_results). The top_bmus / top_companies lists are a best-effort
preview aggregate (the engine's exact per-BMU attribution lands in M5) — the
UI badges them as preview.

Usage: uv run python site/dev/make_dev_data.py
Copies the DB first so it never contends with a concurrently-running ingest.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "site" / "data"

LIMITATIONS = (
    "BM settlement data only. Excludes bilateral trades, the Local Constraint "
    "Market and embedded (non-BM) wind: true constraint costs are higher. "
    "SO-flag is an imperfect constraint indicator."
)

TOP_BMUS_SQL = """
    select s.id,
           coalesce(nullif(r.bmUnitName, ''), s.id)      as station,
           coalesce(nullif(r.leadPartyName, ''), s.id)   as lead_party,
           sum(coalesce(s.tlmAdjustedCost,
                        s.finalPrice * coalesce(s.tlmAdjustedVolume, s.volume)))
                                                          as cost_gbp,
           sum(-coalesce(s.tlmAdjustedVolume, s.volume))   as volume_mwh
    from stack_items s
    left join bmu_ref r on s.id = r.elexonBmUnit
    where s.settlementDate = ? and s.flow = 'bid' and s.soFlag
      and r.fuelType = 'WIND'
    group by 1, 2, 3
    having sum(-coalesce(s.tlmAdjustedVolume, s.volume)) > 0
    order by cost_gbp desc, s.id asc
"""

TOP_COMPANIES_SQL = """
    select coalesce(nullif(r.leadPartyName, ''),
                    case when regexp_matches(s.id, '^[0-9]+$')
                         then 'Non-BM secondary unit' else s.id end)
                                                          as company,
           sum(coalesce(s.tlmAdjustedCost,
                        s.finalPrice * coalesce(s.tlmAdjustedVolume, s.volume)))
                                                          as cost_gbp,
           sum(coalesce(s.tlmAdjustedVolume, s.volume))   as volume_mwh,
           list(distinct coalesce(nullif(r.fuelType, ''), 'UNKNOWN'))
                                                          as fuels
    from stack_items s
    left join bmu_ref r on s.id = r.elexonBmUnit
    where s.settlementDate = ? and s.flow = 'offer' and s.soFlag
      and coalesce(r.fuelType, '') != 'WIND'
    group by 1
    having sum(coalesce(s.tlmAdjustedVolume, 0)) > 0
    order by cost_gbp desc, company asc
"""


def scaled(rows, cost_i, vol_i, cost_total, vol_total):
    """Scale preview rows so list totals match the engine's real daily totals.

    Rankings come from the raw-stack aggregate; absolute sizes are pinned to
    the engine's computed figures so the tables never contradict the stats.
    """
    csum = sum(r[cost_i] for r in rows)
    vsum = sum(r[vol_i] for r in rows)
    cf = cost_total / csum if csum else 0.0
    vf = vol_total / vsum if vsum else 0.0
    out = []
    for r in rows[:10]:
        r = list(r)
        r[cost_i] *= cf
        r[vol_i] *= vf
        out.append(r)
    return out


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    shutil.copy(ROOT / "data" / "tracker.duckdb", tmp / "t.duckdb")
    wal = ROOT / "data" / "tracker.duckdb.wal"
    if wal.exists():
        shutil.copy(wal, tmp / "t.duckdb.wal")
    con = duckdb.connect(str(tmp / "t.duckdb"), read_only=True)

    days = con.execute(
        "select date, curtailment_cost, curtailment_volume, turnup_cost,"
        " turnup_volume, total_cost from daily_results order by date"
    ).fetchall()

    (OUT / "daily").mkdir(parents=True, exist_ok=True)
    dates = []
    months: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for d, c_cost, c_vol, t_cost, t_vol, total in days:
        top_bmus = [
            {
                "bmu_id": bmu,
                "station_name": station,
                "lead_party_name": lead,
                "parent_company": lead,
                "cost_gbp": round(cost, 2),
                "volume_mwh": round(vol, 3),
            }
            for bmu, station, lead, cost, vol in scaled(
                con.execute(TOP_BMUS_SQL, [d]).fetchall(), 3, 4, c_cost, c_vol
            )
        ]
        top_companies = [
            {
                "parent_company": company,
                "cost_gbp": round(cost, 2),
                "volume_mwh": round(vol, 3),
                "fuel_types": sorted(fuels),
            }
            for company, cost, vol, fuels in scaled(
                con.execute(TOP_COMPANIES_SQL, [d]).fetchall(), 1, 2, t_cost, t_vol
            )
        ]
        doc = {
            "date": d.isoformat(),
            "methodology_version": "1.0",
            "limitations": LIMITATIONS,
            "curtailment": {
                "cost_gbp": c_cost,
                "volume_mwh": c_vol,
                "top_bmus": top_bmus,
            },
            "turnup": {
                "replacement_cost_gbp": t_cost,
                "replacement_volume_mwh": t_vol,
                "so_flagged_payments_gbp": t_cost,
                "so_flagged_volume_mwh": t_vol,
                "top_companies": top_companies,
            },
            "total_cost_gbp": total,
        }
        (OUT / "daily" / f"{d.isoformat()}.json").write_text(
            json.dumps(doc, indent=1)
        )
        dates.append(d.isoformat())
        m = months[d.month]
        m["curtailment_cost_gbp"] += c_cost
        m["curtailment_volume_mwh"] += c_vol
        m["replacement_cost_gbp"] += t_cost
        m["so_flagged_payments_gbp"] += t_cost
        m["total_cost_gbp"] += total

    month_rows = [
        {"month": m, "partial": True, **{k: round(v, 2) for k, v in vals.items()}}
        for m, vals in sorted(months.items())
    ]
    totals = {
        "curtailment_cost_gbp": round(sum(r["curtailment_cost_gbp"] for r in month_rows), 2),
        "curtailment_volume_mwh": round(sum(r["curtailment_volume_mwh"] for r in month_rows), 2),
        "replacement_cost_gbp": round(sum(r["replacement_cost_gbp"] for r in month_rows), 2),
        "total_cost_gbp": round(sum(r["total_cost_gbp"] for r in month_rows), 2),
        "so_flagged_payments_gbp": round(sum(r["so_flagged_payments_gbp"] for r in month_rows), 2),
    }
    summary = {
        "generated_at": "dev-preview",
        "methodology_version": "1.0",
        "limitations": LIMITATIONS,
        "year": 2026,
        "totals": totals,
        "months": month_rows,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))
    # Dev-only helper so the UI knows which daily files exist without 404-probing.
    (OUT / "dates.json").write_text(json.dumps(dates))
    print(f"wrote {len(dates)} daily files + summary.json to {OUT}")


if __name__ == "__main__":
    main()
