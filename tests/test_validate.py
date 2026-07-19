from datetime import date

import pytest

from tracker.models import WastedWindMonth
from tracker.store import MonthlyAggregate
from tracker.validate import (
    ValidationWaiver,
    compare_month,
    deviation_pct,
    eligible_months,
)


def test_eligible_months_are_complete_and_in_supported_range() -> None:
    assert eligible_months(2026, date(2026, 7, 17)) == [1, 2, 3, 4, 5, 6]
    assert eligible_months(2025, date(2026, 7, 17)) == []


def test_deviation_handles_zero_reference_values() -> None:
    assert deviation_pct(0, 0) == 0
    assert deviation_pct(1, 0) == float("inf")
    assert deviation_pct(98, 100) == pytest.approx(2)


def test_waiver_matches_on_year_month_and_metric() -> None:
    ours = MonthlyAggregate(110, 200, 300, 400)
    theirs = WastedWindMonth(
        year=2026,
        month=6,
        bidCost=100,
        bidVolumeMWh=200,
        turnUpCost=300,
        turnUpVolume=400,
    )
    waivers = [ValidationWaiver(2026, 6, "bidCost", 10, "explained revision")]

    comparisons = compare_month(2026, 6, ours, theirs, waivers)

    bid_cost = comparisons[0]
    assert not bid_cost.passed
    assert bid_cost.status == "WAIVED (explained revision)"
    assert all(item.passed for item in comparisons[1:])
