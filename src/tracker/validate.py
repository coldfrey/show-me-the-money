"""Monthly comparison against wastedwind.energy's summary API."""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta
from math import inf
from pathlib import Path
from typing import Any

import yaml

from tracker.api import ElexonClient
from tracker.config import EARLIEST_DATE
from tracker.ingest import ingest_dates
from tracker.models import WastedWindMonth
from tracker.store import MonthlyAggregate, TrackerStore

THRESHOLD_PCT = 2.0


@dataclass(frozen=True)
class ValidationWaiver:
    year: int
    month: int
    metric: str
    observed_pct: float
    reason: str


@dataclass(frozen=True)
class MetricComparison:
    year: int
    month: int
    metric: str
    ours: float
    theirs: float
    deviation_pct: float
    passed: bool
    waiver_reason: str | None = None

    @property
    def status(self) -> str:
        if self.waiver_reason is not None:
            return f"WAIVED ({self.waiver_reason})"
        return "PASS" if self.passed else "FAIL"


@dataclass(frozen=True)
class ValidationReport:
    comparisons: list[MetricComparison]

    @property
    def passed(self) -> bool:
        return all(
            item.passed or item.waiver_reason is not None for item in self.comparisons
        )


def eligible_months(year: int, latest_date: date) -> list[int]:
    """Return months wholly inside the supported validation interval."""
    months: list[int] = []
    for month in range(1, 13):
        start = date(year, month, 1)
        end = date(year, month, monthrange(year, month)[1])
        if start >= EARLIEST_DATE and end <= latest_date:
            months.append(month)
    return months


def month_dates(year: int, month: int) -> list[date]:
    start = date(year, month, 1)
    return [
        start + timedelta(days=offset) for offset in range(monthrange(year, month)[1])
    ]


def deviation_pct(ours: float, theirs: float) -> float:
    if theirs == 0.0:
        return 0.0 if ours == 0.0 else inf
    return abs(ours - theirs) / abs(theirs) * 100.0


def compare_month(
    year: int,
    month: int,
    ours: MonthlyAggregate,
    theirs: WastedWindMonth,
    waivers: list[ValidationWaiver],
) -> list[MetricComparison]:
    metrics = {
        "bidCost": (ours.curtailment_cost, theirs.bidCost),
        "bidVolumeMWh": (ours.curtailment_volume, theirs.bidVolumeMWh),
        "turnUpCost": (ours.turnup_cost, theirs.turnUpCost),
        "turnUpVolume": (ours.turnup_volume, theirs.turnUpVolume),
    }
    waiver_lookup = {(item.year, item.month, item.metric): item for item in waivers}
    comparisons: list[MetricComparison] = []
    for metric, (ours_value, theirs_value) in metrics.items():
        deviation = deviation_pct(ours_value, theirs_value)
        waiver = waiver_lookup.get((year, month, metric))
        comparisons.append(
            MetricComparison(
                year=year,
                month=month,
                metric=metric,
                ours=ours_value,
                theirs=theirs_value,
                deviation_pct=deviation,
                passed=deviation <= THRESHOLD_PCT,
                waiver_reason=waiver.reason if waiver is not None else None,
            )
        )
    return comparisons


def load_waivers(path: Path) -> list[ValidationWaiver]:
    raw: Any = yaml.safe_load(path.read_text()) if path.exists() else {"waivers": []}
    if not isinstance(raw, dict) or not isinstance(raw.get("waivers"), list):
        raise ValueError(f"Invalid waiver file: {path}")
    return [ValidationWaiver(**entry) for entry in raw["waivers"]]


def run_validation(
    client: ElexonClient,
    store: TrackerStore,
    year: int,
    month: int | None,
    latest_date: date,
    waiver_path: Path,
) -> ValidationReport:
    eligible = eligible_months(year, latest_date)
    if month is not None and month not in eligible:
        listed = ", ".join(str(value) for value in eligible) or "none"
        raise ValueError(
            f"Month {month} is not eligible; eligible months for {year}: {listed}"
        )
    selected = [month] if month is not None else eligible
    if not selected:
        raise ValueError(f"No complete eligible months for {year}")

    dates = [
        day for selected_month in selected for day in month_dates(year, selected_month)
    ]
    ingest_dates(client, store, dates)
    summary = client.wastedwind_summary(year)
    summaries = {(item.year, item.month): item for item in summary.data}
    waivers = load_waivers(waiver_path)
    comparisons: list[MetricComparison] = []
    for selected_month in selected:
        theirs = summaries.get((year, selected_month))
        if theirs is None:
            raise ValueError(
                f"wastedwind summary has no entry for {year}-{selected_month:02d}"
            )
        ours = store.monthly_aggregate(year, selected_month)
        comparisons.extend(compare_month(year, selected_month, ours, theirs, waivers))
    return ValidationReport(comparisons)
