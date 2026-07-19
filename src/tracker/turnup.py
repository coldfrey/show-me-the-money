"""Pure per-BMU attribution calculations for both constraint sides."""

from dataclasses import dataclass

from tracker.models import StackItem


@dataclass(frozen=True)
class BmuAmount:
    volume_mwh: float
    cost_gbp: float


def so_offer_payments(
    offer_items: list[StackItem], fuel_lookup: dict[str, str | None]
) -> dict[str | None, BmuAmount]:
    """Group gross SO-flagged offer payments by Elexon BMU ID."""
    del fuel_lookup  # Shared contract with curtailment; fuel does not filter offers.
    grouped: dict[str | None, tuple[float, float]] = {}
    for item in offer_items:
        if not item.soFlag:
            continue
        volume, cost = grouped.get(item.id, (0.0, 0.0))
        grouped[item.id] = (
            volume + item.volume,
            cost + item.originalPrice * item.volume,
        )
    return {
        bmu_id: BmuAmount(volume_mwh=volume, cost_gbp=cost)
        for bmu_id, (volume, cost) in grouped.items()
    }


def so_wind_curtailment(
    bid_items: list[StackItem], fuel_lookup: dict[str, str | None]
) -> dict[str | None, BmuAmount]:
    """Group SO-flagged wind curtailment by Elexon BMU ID."""
    grouped: dict[str | None, tuple[float, float]] = {}
    for item in bid_items:
        if item.id is None or fuel_lookup.get(item.id) != "WIND" or not item.soFlag:
            continue
        volume, cost = grouped.get(item.id, (0.0, 0.0))
        grouped[item.id] = (
            volume + item.volume,
            cost + item.originalPrice * item.volume,
        )
    return {
        bmu_id: BmuAmount(volume_mwh=abs(volume), cost_gbp=cost)
        for bmu_id, (volume, cost) in grouped.items()
    }
