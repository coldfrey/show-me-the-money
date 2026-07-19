from datetime import date

import pytest

from tracker.export import (
    DailyExport,
    LIMITATIONS,
    MissingDatesError,
    SummaryExport,
    build_daily_export,
    build_summary_export,
)
from tracker.models import BmuRef
from tracker.owners import Owner
from tracker.store import TrackerStore
from tracker.turnup import BmuAmount
from tracker.wastedwind import CurtailmentResult, DayResult, TurnupResult


def reference(bmu_id: str, party_id: str, fuel: str) -> BmuRef:
    return BmuRef(
        elexonBmUnit=bmu_id,
        nationalGridBmUnit=None,
        bmUnitName=f"Station {bmu_id}",
        leadPartyName=f"Party {party_id}",
        leadPartyId=party_id,
        fuelType=fuel,
        generationCapacity=None,
        bmUnitType=None,
        interconnectorId=None,
        gspGroupId=None,
    )


def seed_day(store: TrackerStore, settlement_date: date, count: int = 12) -> None:
    result = DayResult(
        settlement_date,
        CurtailmentResult(100, 2, {1: -2}),
        TurnupResult(200, 2, {1: (200, 2)}),
        300,
    )
    store.replace_daily_result(result)
    references = {
        f"B{index:02d}": reference(f"B{index:02d}", f"P{index:02d}", "WIND")
        for index in range(count)
    }
    turnup_references = {
        f"T{index:02d}": reference(f"T{index:02d}", f"P{index:02d}", "CCGT")
        for index in range(count)
    }
    references.update(turnup_references)
    store.replace_attributions(
        settlement_date,
        {f"T{index:02d}": BmuAmount(1, float(100 - index)) for index in range(count)},
        {f"B{index:02d}": BmuAmount(1, float(100 - index)) for index in range(count)},
        references,
    )


def test_daily_export_round_trips_schema_limits_and_ordering(tmp_path) -> None:
    with TrackerStore(tmp_path / "tracker.duckdb") as store:
        seed_day(store, date(2026, 1, 1))
        owners = {
            f"P{index:02d}": Owner(
                f"P{index:02d}", f"Party P{index:02d}", f"Parent {index:02d}", ""
            )
            for index in range(12)
        }
        document = build_daily_export(store, date(2026, 1, 1), owners)

    restored = DailyExport.model_validate_json(document.model_dump_json())
    assert restored.limitations == LIMITATIONS
    assert len(restored.curtailment.top_bmus) == 10
    assert len(restored.turnup.top_companies) == 10
    assert [row.cost_gbp for row in restored.curtailment.top_bmus] == sorted(
        (row.cost_gbp for row in restored.curtailment.top_bmus), reverse=True
    )
    assert restored.total_cost_gbp == 300


def test_summary_strict_mode_raises_on_a_gap(tmp_path) -> None:
    with TrackerStore(tmp_path / "tracker.duckdb") as store:
        seed_day(store, date(2026, 1, 1), count=1)
        with pytest.raises(MissingDatesError) as error:
            build_summary_export(store, date(2026, 1, 4), allow_missing=False)

    assert error.value.dates == [date(2026, 1, 2)]


def test_summary_allow_missing_round_trips_and_marks_month_partial(tmp_path) -> None:
    with TrackerStore(tmp_path / "tracker.duckdb") as store:
        seed_day(store, date(2026, 1, 1), count=1)
        document, missing = build_summary_export(
            store, date(2026, 1, 4), allow_missing=True
        )

    restored = SummaryExport.model_validate_json(document.model_dump_json())
    assert missing == [date(2026, 1, 2)]
    assert restored.months[0].partial
    assert restored.totals.total_cost_gbp == 300
