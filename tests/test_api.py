from __future__ import annotations

from datetime import date
import time

import httpx

from tracker.api import ElexonClient


def stack_item(period: int) -> dict[str, object]:
    return {
        "settlementDate": "2026-07-10",
        "settlementPeriod": period,
        "startTime": "2026-07-10T00:00:00Z",
        "sequenceNumber": 1,
        "id": "T_TEST-1",
        "acceptanceId": 1,
        "bidOfferPairId": 1,
        "cadlFlag": False,
        "soFlag": False,
        "originalPrice": 10.0,
        "finalPrice": 10.0,
        "volume": 1.0,
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


def test_stack_fetches_are_cached_across_all_periods(tmp_path) -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        period = int(request.url.path.split("/")[-1])
        return httpx.Response(200, json={"data": [stack_item(period)]})

    with ElexonClient(tmp_path, httpx.MockTransport(handler)) as client:
        for period in range(1, 51):
            client.bid_stack(date(2026, 7, 10), period)
            client.offer_stack(date(2026, 7, 10), period)
        assert request_count == 100

        for period in range(1, 51):
            client.bid_stack(date(2026, 7, 10), period)
            client.offer_stack(date(2026, 7, 10), period)
    assert request_count == 100


def test_stack_404_is_cached_as_empty(tmp_path) -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(404, json={"detail": "missing"})

    with ElexonClient(tmp_path, httpx.MockTransport(handler)) as client:
        assert client.bid_stack(date(2026, 7, 10), 49) == []
        assert client.bid_stack(date(2026, 7, 10), 49) == []
    assert request_count == 1


def test_synthetic_stack_item_allows_null_identifiers(tmp_path) -> None:
    item = stack_item(1)
    item["acceptanceId"] = None
    item["bidOfferPairId"] = None

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [item]})

    with ElexonClient(tmp_path, httpx.MockTransport(handler)) as client:
        result = client.offer_stack(date(2026, 7, 10), 1)
    assert result[0].acceptanceId is None
    assert result[0].bidOfferPairId is None


def test_stack_item_allows_null_bmu_id(tmp_path) -> None:
    item = stack_item(1)
    item["id"] = None

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [item]})

    with ElexonClient(tmp_path, httpx.MockTransport(handler)) as client:
        result = client.bid_stack(date(2026, 7, 10), 1)
    assert result[0].id is None


def test_reference_rows_without_elexon_id_are_not_joinable(tmp_path) -> None:
    valid = {
        "elexonBmUnit": "T_TEST-1",
        "nationalGridBmUnit": None,
        "bmUnitName": None,
        "leadPartyName": None,
        "leadPartyId": None,
        "fuelType": "WIND",
        "generationCapacity": None,
        "bmUnitType": None,
        "interconnectorId": None,
        "gspGroupId": None,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[valid, {**valid, "elexonBmUnit": None}, valid],
        )

    with ElexonClient(tmp_path, httpx.MockTransport(handler)) as client:
        result = client.bmunits()
    assert [item.elexonBmUnit for item in result] == ["T_TEST-1"]


def test_retry_after_is_honoured(tmp_path) -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json={"data": [stack_item(1)]})

    started = time.monotonic()
    with ElexonClient(tmp_path, httpx.MockTransport(handler)) as client:
        client.bid_stack(date(2026, 7, 10), 1)
    assert request_count == 2
    assert time.monotonic() - started >= 0.95


def test_attempts_are_spaced_by_at_least_a_quarter_second(tmp_path) -> None:
    attempt_times: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempt_times.append(time.monotonic())
        return httpx.Response(200, json={"data": [stack_item(1)]})

    with ElexonClient(tmp_path, httpx.MockTransport(handler)) as client:
        client.bid_stack(date(2026, 7, 10), 1)
        client.offer_stack(date(2026, 7, 10), 1)
    assert attempt_times[1] - attempt_times[0] >= 0.24


def test_cache_filename_is_deterministic_for_permuted_params(tmp_path) -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, json={"data": []})

    with ElexonClient(tmp_path, httpx.MockTransport(handler)) as client:
        first = client.get("/datasets/MID", {"to": "2026-07-10", "from": "2026-07-10"})
        second = client.get("/datasets/MID", {"from": "2026-07-10", "to": "2026-07-10"})
    assert first == second
    assert requests == 1
