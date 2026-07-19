from datetime import UTC, date, datetime

import pytest

from tracker.models import StackItem
from tracker.wastedwind import compute_day, daily_curtailment, daily_turnup


def item(
    *,
    bmu_id: str = "T_WIND-1",
    period: int = 1,
    sequence: int = 1,
    so: bool = True,
    cadl: bool | None = False,
    price: float = -50.0,
    volume: float = -2.0,
) -> StackItem:
    return StackItem(
        settlementDate=date(2026, 7, 10),
        settlementPeriod=period,
        startTime=datetime(2026, 7, 10, tzinfo=UTC),
        sequenceNumber=sequence,
        id=bmu_id,
        acceptanceId=1,
        bidOfferPairId=1,
        cadlFlag=cadl,
        soFlag=so,
        originalPrice=price,
        finalPrice=price,
        volume=volume,
        transmissionLossMultiplier=None,
        createdDateTime=None,
        storProviderFlag=None,
        repricedIndicator=None,
        reserveScarcityPrice=None,
        dmatAdjustedVolume=None,
        arbitrageAdjustedVolume=None,
        nivAdjustedVolume=None,
        parAdjustedVolume=None,
        tlmAdjustedVolume=None,
        tlmAdjustedCost=None,
    )


def test_wind_and_soflag_filtering_excludes_non_wind_and_non_so() -> None:
    bids = [
        item(bmu_id="WIND", volume=-2),
        item(bmu_id="GAS", volume=-7),
        item(bmu_id="WIND", so=False, volume=-11),
    ]
    result = daily_curtailment(bids, {"WIND": "WIND", "GAS": "CCGT"})

    assert result.volume_mwh == 2
    assert result.period_curtailed == {1: -2}


def test_negative_price_times_negative_volume_is_positive_cost() -> None:
    result = daily_curtailment([item(price=-50, volume=-2)], {"T_WIND-1": "WIND"})

    assert result.cost_gbp == 100


def test_turnup_sort_order_non_so_before_so_then_sequence_number() -> None:
    offers = [
        item(sequence=1, so=True, price=100, volume=3),
        item(sequence=2, so=False, price=20, volume=3),
        item(sequence=1, so=False, price=10, volume=3),
    ]
    result = daily_turnup(offers, {1: -5})

    assert result.volume_mwh == 5
    assert result.cost_gbp == 70


def test_stable_tie_order_preserves_original_response_order() -> None:
    offers = [
        item(sequence=1, so=False, price=10, volume=4),
        item(sequence=1, so=False, price=100, volume=4),
    ]
    result = daily_turnup(offers, {1: -5})

    assert result.cost_gbp == 140


def test_pro_rating_final_offer_at_exact_boundary() -> None:
    offers = [
        item(sequence=1, so=False, price=10, volume=5),
        item(sequence=2, so=False, price=100, volume=5),
    ]
    result = daily_turnup(offers, {1: -5})

    assert result.per_period[1] == (50, 5)


def test_pro_rating_final_offer_on_overshoot() -> None:
    result = daily_turnup(
        [item(so=False, price=12, volume=8)],
        {1: -5},
    )

    assert result.per_period[1] == (60, 5)


def test_partial_coverage_uses_only_consumable_offers() -> None:
    offers = [
        item(sequence=1, so=False, price=10, volume=4),
        item(sequence=2, so=False, price=20, volume=2),
    ]
    result = daily_turnup(offers, {1: -10})

    assert result.volume_mwh == 6
    assert result.cost_gbp == 80


def test_zero_curtailment_day_has_zero_turnup() -> None:
    result = compute_day(
        date(2026, 7, 10),
        [item(so=False)],
        [item(price=100, volume=20)],
        {"T_WIND-1": "WIND"},
    )

    assert result.turnup.volume_mwh == 0
    assert result.turnup.cost_gbp == 0
    assert result.total_cost_gbp == 0


def test_cadl_flag_none_is_treated_as_false() -> None:
    result = daily_turnup(
        [item(so=False, cadl=None, price=10, volume=5)],
        {1: -3},
    )

    assert result.volume_mwh == 3
    assert result.cost_gbp == 30


def test_curtailed_period_with_empty_offer_stack() -> None:
    result = daily_turnup([], {7: -4})

    assert result.per_period == {7: (0, 0)}
    assert result.volume_mwh == 0
    assert result.cost_gbp == 0


def test_periods_and_daily_totals_are_aggregated() -> None:
    bids = [item(period=1, volume=-2), item(period=2, volume=-3)]
    offers = [
        item(period=1, so=False, price=10, volume=2),
        item(period=2, so=False, price=20, volume=3),
    ]
    result = compute_day(date(2026, 7, 10), bids, offers, {"T_WIND-1": "WIND"})

    assert result.curtailment.volume_mwh == 5
    assert result.turnup.volume_mwh == 5
    assert result.turnup.cost_gbp == 80
    assert result.total_cost_gbp == pytest.approx(330)
