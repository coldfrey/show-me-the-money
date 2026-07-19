"""Pure replication of the wastedwind.energy calculation."""

from dataclasses import dataclass
from datetime import date

from tracker.models import StackItem


@dataclass(frozen=True)
class CurtailmentResult:
    cost_gbp: float
    volume_mwh: float
    period_curtailed: dict[int, float]


@dataclass(frozen=True)
class TurnupResult:
    cost_gbp: float
    volume_mwh: float
    per_period: dict[int, tuple[float, float]]


@dataclass(frozen=True)
class DayResult:
    date: date
    curtailment: CurtailmentResult
    turnup: TurnupResult
    total_cost_gbp: float


def daily_curtailment(
    bid_items: list[StackItem], fuel_lookup: dict[str, str | None]
) -> CurtailmentResult:
    """Calculate SO-flagged wind curtailment from a day's bid stack."""
    wind_bids = [
        item for item in bid_items if fuel_lookup.get(item.id) == "WIND" and item.soFlag
    ]
    period_totals: dict[int, float] = {}
    for item in wind_bids:
        period_totals[item.settlementPeriod] = (
            period_totals.get(item.settlementPeriod, 0.0) + item.volume
        )
    period_curtailed = {
        period: volume for period, volume in period_totals.items() if volume != 0.0
    }
    signed_volume = sum(item.volume for item in wind_bids)
    cost = sum(item.originalPrice * item.volume for item in wind_bids)
    return CurtailmentResult(
        cost_gbp=cost,
        volume_mwh=abs(signed_volume),
        period_curtailed=period_curtailed,
    )


def daily_turnup(
    offer_items: list[StackItem], period_curtailed: dict[int, float]
) -> TurnupResult:
    """Walk each offer stack to replace its period's curtailed wind volume."""
    per_period: dict[int, tuple[float, float]] = {}
    for period, curtailed_volume in period_curtailed.items():
        target = abs(curtailed_volume)
        candidates = sorted(
            (
                item
                for item in offer_items
                if item.settlementPeriod == period and not item.cadlFlag
            ),
            key=lambda item: (item.soFlag, item.sequenceNumber),
        )
        consumed = 0.0
        cost = 0.0
        for item in candidates:
            if consumed >= target:
                break
            if item.volume == 0.0:
                fraction = 0.0
            else:
                fraction = max(0.0, min((target - consumed) / item.volume, 1.0))
            consumed_volume = item.volume * fraction
            consumed += consumed_volume
            cost += item.originalPrice * consumed_volume
        per_period[period] = (cost, consumed)

    return TurnupResult(
        cost_gbp=sum(result[0] for result in per_period.values()),
        volume_mwh=sum(result[1] for result in per_period.values()),
        per_period=per_period,
    )


def compute_day(
    settlement_date: date,
    bid_items: list[StackItem],
    offer_items: list[StackItem],
    fuel_lookup: dict[str, str | None],
) -> DayResult:
    """Compute both sides of the wastedwind-compatible daily result."""
    curtailment = daily_curtailment(bid_items, fuel_lookup)
    turnup = daily_turnup(offer_items, curtailment.period_curtailed)
    return DayResult(
        date=settlement_date,
        curtailment=curtailment,
        turnup=turnup,
        total_cost_gbp=curtailment.cost_gbp + turnup.cost_gbp,
    )
