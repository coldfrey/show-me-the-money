"""Optional independent cashflow and market-price cross-checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from tracker.api import ElexonClient
from tracker.store import TrackerStore
from tracker.wastedwind import daily_curtailment


@dataclass(frozen=True)
class CrosscheckResult:
    our_curtailment_gbp: float
    ebocf_wind_gbp: float
    ebocf_deviation_pct: float
    ebocf_flagged: bool
    mid_estimate_gbp: float
    missing_mid_periods: list[int]


def ebocf_wind_cashflow(
    rows: list[dict[str, Any]], fuel_lookup: dict[str, str | None]
) -> float:
    total = 0.0
    for row in rows:
        bmu_id = row.get("bmUnit")
        if not isinstance(bmu_id, str) or fuel_lookup.get(bmu_id) != "WIND":
            continue
        cashflows = row.get("bidOfferPairCashflows")
        if not isinstance(cashflows, dict):
            continue
        total += sum(
            float(cashflows.get(f"negative{pair}") or 0.0) for pair in range(1, 7)
        )
    return total


def magnitude_deviation_pct(ours: float, alternative: float) -> float:
    if ours == 0.0:
        return 0.0 if alternative == 0.0 else float("inf")
    return abs(abs(alternative) - abs(ours)) / abs(ours) * 100.0


def mid_alternative_estimate(
    period_curtailed: dict[int, float], rows: list[dict[str, Any]]
) -> tuple[float, list[int]]:
    prices = {
        int(row["settlementPeriod"]): float(row["price"])
        for row in rows
        if row.get("dataProvider") == "APXMIDP"
        and row.get("settlementPeriod") is not None
        and row.get("price") is not None
    }
    missing = sorted(period for period in period_curtailed if period not in prices)
    estimate = sum(
        abs(volume) * prices[period]
        for period, volume in period_curtailed.items()
        if period in prices
    )
    return estimate, missing


def run_crosscheck(
    client: ElexonClient, store: TrackerStore, settlement_date: date
) -> CrosscheckResult:
    daily = store.daily_result(settlement_date)
    if daily is None:
        raise ValueError(f"No daily result stored for {settlement_date}")
    fuel_lookup = store.fuel_lookup()
    ebocf_rows: list[dict[str, Any]] = []
    for period in range(1, 51):
        response = client.get(
            "/balancing/settlement/indicative/cashflows/all/"
            f"bid/{settlement_date.isoformat()}/{period}"
        )
        if not isinstance(response, dict) or not isinstance(response.get("data"), list):
            raise ValueError(f"Invalid EBOCF response for period {period}")
        ebocf_rows.extend(row for row in response["data"] if isinstance(row, dict))
    ebocf = ebocf_wind_cashflow(ebocf_rows, fuel_lookup)
    deviation = magnitude_deviation_pct(daily.curtailment_cost, ebocf)

    bids = store.stack_items(settlement_date, "bid")
    curtailed = daily_curtailment(bids, fuel_lookup).period_curtailed
    mid_response = client.get(
        "/datasets/MID",
        {"from": settlement_date.isoformat(), "to": settlement_date.isoformat()},
    )
    if not isinstance(mid_response, dict) or not isinstance(
        mid_response.get("data"), list
    ):
        raise ValueError("Invalid MID response")
    mid_rows = [row for row in mid_response["data"] if isinstance(row, dict)]
    mid_estimate, missing = mid_alternative_estimate(curtailed, mid_rows)
    return CrosscheckResult(
        our_curtailment_gbp=daily.curtailment_cost,
        ebocf_wind_gbp=ebocf,
        ebocf_deviation_pct=deviation,
        ebocf_flagged=deviation > 25.0,
        mid_estimate_gbp=mid_estimate,
        missing_mid_periods=missing,
    )
