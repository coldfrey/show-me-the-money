"""Orchestration for fetching, storing, and calculating settlement dates."""

from datetime import date

from tracker.api import ElexonClient
from tracker.store import TrackerStore
from tracker.turnup import so_offer_payments, so_wind_curtailment
from tracker.wastedwind import DayResult, compute_day


def ingest_dates(
    client: ElexonClient,
    store: TrackerStore,
    dates: list[date],
    *,
    refresh: bool = False,
    refresh_reference: bool = False,
) -> list[DayResult]:
    """Ingest an inclusive set of already-validated settlement dates."""
    references = client.bmunits(refresh=refresh_reference)
    store.replace_bmu_ref(references)
    fuel_lookup = {item.elexonBmUnit: item.fuelType for item in references}
    reference_lookup = {item.elexonBmUnit: item for item in references}
    results: list[DayResult] = []
    for settlement_date in dates:
        bids = []
        offers = []
        for period in range(1, 51):
            bids.extend(client.bid_stack(settlement_date, period, refresh=refresh))
            offers.extend(client.offer_stack(settlement_date, period, refresh=refresh))
        store.replace_stack_items(settlement_date, bids, offers)
        result = compute_day(settlement_date, bids, offers, fuel_lookup)
        store.replace_daily_result(result)
        store.replace_attributions(
            settlement_date,
            so_offer_payments(offers, fuel_lookup),
            so_wind_curtailment(bids, fuel_lookup),
            reference_lookup,
        )
        results.append(result)
    return results


def refresh_reference(client: ElexonClient, store: TrackerStore) -> int:
    """Refresh only BMU reference data and return its row count."""
    references = client.bmunits(refresh=True)
    store.replace_bmu_ref(references)
    return len(references)


def recompute_stored_dates(store: TrackerStore, start: date, end: date) -> list[date]:
    """Recompute stored dates without constructing an HTTP client."""
    references = store.bmu_references()
    fuel_lookup = {item.elexonBmUnit: item.fuelType for item in references}
    reference_lookup = {item.elexonBmUnit: item for item in references}
    dates = store.stored_dates(start, end)
    for settlement_date in dates:
        bids = store.stack_items(settlement_date, "bid")
        offers = store.stack_items(settlement_date, "offer")
        result = compute_day(settlement_date, bids, offers, fuel_lookup)
        store.replace_daily_result(result)
        store.replace_attributions(
            settlement_date,
            so_offer_payments(offers, fuel_lookup),
            so_wind_curtailment(bids, fuel_lookup),
            reference_lookup,
        )
    return dates
