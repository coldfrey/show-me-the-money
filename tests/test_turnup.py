from datetime import UTC, date, datetime

from tracker.models import StackItem
from tracker.owners import Owner, aggregate_leaderboard
from tracker.store import AttributionRecord
from tracker.turnup import so_offer_payments, so_wind_curtailment


def item(
    *,
    bmu_id: str = "T_TEST-1",
    so: bool = True,
    cadl: bool | None = False,
    price: float = 50,
    volume: float = 2,
) -> StackItem:
    return StackItem(
        settlementDate=date(2026, 6, 1),
        settlementPeriod=1,
        startTime=datetime(2026, 5, 31, 23, tzinfo=UTC),
        sequenceNumber=1,
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


def test_so_offer_payments_filters_so_only_without_cadl_filter() -> None:
    result = so_offer_payments(
        [item(cadl=True), item(so=False, price=999, volume=10)],
        {"T_TEST-1": "CCGT"},
    )

    assert result["T_TEST-1"].volume_mwh == 2
    assert result["T_TEST-1"].cost_gbp == 100


def test_so_offer_payments_groups_bmus_with_signed_sums() -> None:
    result = so_offer_payments(
        [
            item(bmu_id="A", price=50, volume=2),
            item(bmu_id="A", price=-10, volume=1),
            item(bmu_id="B", price=100, volume=3),
        ],
        {"A": "CCGT", "B": "PS"},
    )

    assert result["A"].volume_mwh == 3
    assert result["A"].cost_gbp == 90
    assert result["B"].cost_gbp == 300


def test_so_wind_curtailment_filters_and_reports_positive_grouped_volume() -> None:
    result = so_wind_curtailment(
        [
            item(bmu_id="W", price=-50, volume=-2),
            item(bmu_id="W", price=-40, volume=-1),
            item(bmu_id="G", price=-100, volume=-9),
            item(bmu_id="W", so=False, volume=-20),
        ],
        {"W": "WIND", "G": "CCGT"},
    )

    assert result["W"].volume_mwh == 3
    assert result["W"].cost_gbp == 140
    assert set(result) == {"W"}


def attribution(
    bmu_id: str,
    lead_party_id: str | None,
    lead_party_name: str | None,
    fuel: str | None = "CCGT",
) -> AttributionRecord:
    return AttributionRecord(
        date(2026, 6, 1),
        bmu_id,
        None,
        None,
        lead_party_id,
        lead_party_name,
        fuel,
        2,
        100,
    )


def test_owner_join_includes_missing_owner_and_missing_reference_fallbacks() -> None:
    rows = [
        attribution("A", "PARTY-A", "Mapped Name"),
        attribution("B", "PARTY-B", "Missing Owner"),
        attribution("C", None, None, None),
    ]
    owners = {"PARTY-A": Owner("PARTY-A", "Mapped Name", "Parent A", "")}

    result = aggregate_leaderboard(rows, "company", owners)

    assert [row["parent_company"] for row in result] == [
        "C",
        "Missing Owner",
        "Parent A",
    ]
    assert result[0]["fuel_types"] == ["UNKNOWN"]


def test_leaderboard_rows_are_sorted_by_cost_descending() -> None:
    rows = [
        attribution("A", None, "Low"),
        AttributionRecord(
            date(2026, 6, 1), "B", None, "High", None, "High", "PS", 3, 200
        ),
    ]

    result = aggregate_leaderboard(rows, "station", {})

    assert [row["cost_gbp"] for row in result] == [200, 100]
