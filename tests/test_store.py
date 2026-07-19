from datetime import UTC, date, datetime
import json

import httpx

from tracker.api import ElexonClient
from tracker.ingest import ingest_dates
from tracker.models import StackItem
from tracker.store import NULL_BMU_ID, NULL_IDENTIFIER, TrackerStore


SETTLEMENT_DATE = date(2026, 7, 10)


def stack_item(
    *, flow: str, null_ids: bool = False, null_bmu_id: bool = False
) -> dict[str, object]:
    volume = -2.0 if flow == "bid" else 2.0
    price = -50.0 if flow == "bid" else 100.0
    return {
        "settlementDate": SETTLEMENT_DATE.isoformat(),
        "settlementPeriod": 1,
        "startTime": "2026-07-09T23:00:00Z",
        "sequenceNumber": 1,
        "id": None if null_bmu_id else ("T_WIND-1" if flow == "bid" else "T_GAS-1"),
        "acceptanceId": None if null_ids else 1,
        "bidOfferPairId": None if null_ids else 1,
        "cadlFlag": None,
        "soFlag": True,
        "originalPrice": price,
        "finalPrice": price,
        "volume": volume,
        "transmissionLossMultiplier": None,
        "createdDateTime": None,
        "storProviderFlag": None,
        "repricedIndicator": None,
        "reserveScarcityPrice": None,
        "dmatAdjustedVolume": None,
        "arbitrageAdjustedVolume": None,
        "nivAdjustedVolume": None,
        "parAdjustedVolume": None,
        "tlmAdjustedVolume": None,
        "tlmAdjustedCost": None,
    }


def bmu_reference() -> list[dict[str, object]]:
    return [
        {
            "elexonBmUnit": "T_WIND-1",
            "nationalGridBmUnit": "WIND-1",
            "bmUnitName": "Test Wind",
            "leadPartyName": "Wind Owner",
            "leadPartyId": "WIND",
            "fuelType": "WIND",
            "generationCapacity": "100",
            "bmUnitType": "T",
            "interconnectorId": None,
            "gspGroupId": None,
        },
        {
            "elexonBmUnit": "T_GAS-1",
            "nationalGridBmUnit": "GAS-1",
            "bmUnitName": "Test Gas",
            "leadPartyName": "Gas Owner",
            "leadPartyId": "GAS",
            "fuelType": "CCGT",
            "generationCapacity": "100",
            "bmUnitType": "T",
            "interconnectorId": None,
            "gspGroupId": None,
        },
    ]


def seed_cache(cache_dir, client: ElexonClient) -> None:
    reference_path = cache_dir / "reference" / "bmunits.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps(bmu_reference()))
    for flow in ("bid", "offer"):
        for period in range(1, 51):
            url = (
                "https://data.elexon.co.uk/bmrs/api/v1/balancing/settlement/"
                f"stack/all/{flow}/{SETTLEMENT_DATE}/{period}"
            )
            path = client._canonical_cache_path(url, None)
            path.parent.mkdir(parents=True, exist_ok=True)
            data = [stack_item(flow=flow)] if period == 1 else []
            path.write_text(json.dumps({"data": data}))


def test_per_date_stack_replace_is_transactional_and_replacing(tmp_path) -> None:
    bid = StackItem.model_validate(stack_item(flow="bid"))
    nullable = StackItem.model_validate(
        stack_item(flow="offer", null_ids=True, null_bmu_id=True)
    )
    with TrackerStore(tmp_path / "tracker.duckdb") as store:
        store.replace_stack_items(SETTLEMENT_DATE, [bid], [nullable])
        assert store.stack_item_count(SETTLEMENT_DATE) == 2
        stored_ids = store.connection.execute(
            "SELECT id, acceptanceId, bidOfferPairId FROM stack_items WHERE flow = 'offer'"
        ).fetchone()
        assert stored_ids == (NULL_BMU_ID, NULL_IDENTIFIER, NULL_IDENTIFIER)

        store.replace_stack_items(SETTLEMENT_DATE, [bid], [])
        assert store.stack_item_count(SETTLEMENT_DATE) == 1


def test_cached_ingest_is_idempotent_and_makes_zero_http_requests(tmp_path) -> None:
    def reject_network(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected HTTP request: {request.url}")

    cache_dir = tmp_path / "raw"
    client = ElexonClient(cache_dir, httpx.MockTransport(reject_network))
    seed_cache(cache_dir, client)
    with client, TrackerStore(tmp_path / "tracker.duckdb") as store:
        ingest_dates(client, store, [SETTLEMENT_DATE])
        first = store.daily_result(SETTLEMENT_DATE)
        first_count = store.stack_item_count(SETTLEMENT_DATE)
        ingest_dates(client, store, [SETTLEMENT_DATE])
        second = store.daily_result(SETTLEMENT_DATE)
        second_count = store.stack_item_count(SETTLEMENT_DATE)

    assert first is not None and second is not None
    assert first.calculated_values == second.calculated_values
    assert first_count == second_count == 2
    assert first.curtailment_cost > 0


def test_daily_result_round_trip(tmp_path) -> None:
    from tracker.wastedwind import compute_day

    bid = StackItem.model_validate(stack_item(flow="bid"))
    offer = StackItem.model_validate(stack_item(flow="offer"))
    result = compute_day(
        SETTLEMENT_DATE,
        [bid],
        [offer],
        {"T_WIND-1": "WIND", "T_GAS-1": "CCGT"},
    )
    with TrackerStore(tmp_path / "tracker.duckdb") as store:
        store.replace_daily_result(result)
        stored = store.daily_result(SETTLEMENT_DATE)

    assert stored is not None
    assert stored.date == SETTLEMENT_DATE
    assert stored.computed_at <= datetime.now(UTC).replace(tzinfo=None)
    assert stored.calculated_values == (100.0, 2.0, 200.0, 2.0, 300.0)


def test_stack_items_round_trip_timestamps_without_optional_timezone_dependency(
    tmp_path,
) -> None:
    bid = StackItem.model_validate(stack_item(flow="bid"))
    with TrackerStore(tmp_path / "tracker.duckdb") as store:
        store.replace_stack_items(SETTLEMENT_DATE, [bid], [])
        restored = store.stack_items(SETTLEMENT_DATE, "bid")

    assert restored == [bid]
