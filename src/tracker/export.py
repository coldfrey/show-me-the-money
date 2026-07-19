"""Pydantic-validated JSON exports for the future static site."""

from __future__ import annotations

from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from tracker.config import EARLIEST_DATE
from tracker.owners import Owner, aggregate_leaderboard, load_owners
from tracker.store import TrackerStore

METHODOLOGY_VERSION = "1.0"
LIMITATIONS = (
    "BM settlement data only. Excludes bilateral trades, the Local Constraint "
    "Market and embedded (non-BM) wind: true constraint costs are higher. "
    "SO-flag is an imperfect constraint indicator."
)


class ExportModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TopBmu(ExportModel):
    bmu_id: str
    station_name: str
    lead_party_name: str
    parent_company: str
    cost_gbp: float
    volume_mwh: float


class CurtailmentExport(ExportModel):
    cost_gbp: float
    volume_mwh: float
    top_bmus: list[TopBmu] = Field(max_length=10)


class TopCompany(ExportModel):
    parent_company: str
    cost_gbp: float
    volume_mwh: float
    fuel_types: list[str]


class TurnupExport(ExportModel):
    replacement_cost_gbp: float
    replacement_volume_mwh: float
    so_flagged_payments_gbp: float
    so_flagged_volume_mwh: float
    top_companies: list[TopCompany] = Field(max_length=10)


class DailyExport(ExportModel):
    date: date
    methodology_version: str
    limitations: str
    curtailment: CurtailmentExport
    turnup: TurnupExport
    total_cost_gbp: float


class SummaryTotals(ExportModel):
    curtailment_cost_gbp: float
    curtailment_volume_mwh: float
    replacement_cost_gbp: float
    total_cost_gbp: float
    so_flagged_payments_gbp: float


class SummaryMonth(ExportModel):
    month: int
    partial: bool
    curtailment_cost_gbp: float
    curtailment_volume_mwh: float
    replacement_cost_gbp: float
    so_flagged_payments_gbp: float
    total_cost_gbp: float


class SummaryExport(ExportModel):
    generated_at: datetime
    methodology_version: str
    limitations: str
    year: int
    totals: SummaryTotals
    months: list[SummaryMonth]


class MissingDatesError(ValueError):
    def __init__(self, dates: list[date]) -> None:
        self.dates = dates
        super().__init__(
            "Missing daily results: " + ", ".join(day.isoformat() for day in dates)
        )


def build_daily_export(
    store: TrackerStore,
    settlement_date: date,
    owners: dict[str, Owner],
) -> DailyExport:
    daily = store.daily_result(settlement_date)
    if daily is None:
        raise ValueError(f"No daily result stored for {settlement_date}")
    curtailment_rows = store.attribution_rows(
        settlement_date, settlement_date, "curtailment"
    )
    turnup_rows = store.attribution_rows(settlement_date, settlement_date, "turnup")
    top_bmus = []
    for row in sorted(curtailment_rows, key=lambda item: (-item.cost_gbp, item.bmu_id))[
        :10
    ]:
        owner = owners.get(row.lead_party_id or "")
        lead_party = row.lead_party_name or row.bmu_id
        top_bmus.append(
            TopBmu(
                bmu_id=row.bmu_id,
                station_name=row.station_name or row.bmu_id,
                lead_party_name=lead_party,
                parent_company=owner.parent_company if owner else lead_party,
                cost_gbp=row.cost_gbp,
                volume_mwh=row.volume_mwh,
            )
        )
    company_rows = aggregate_leaderboard(turnup_rows, "company", owners)[:10]
    top_companies = [TopCompany.model_validate(row) for row in company_rows]
    so_payments = sum(row.cost_gbp for row in turnup_rows)
    so_volume = sum(row.volume_mwh for row in turnup_rows)
    return DailyExport(
        date=settlement_date,
        methodology_version=METHODOLOGY_VERSION,
        limitations=LIMITATIONS,
        curtailment=CurtailmentExport(
            cost_gbp=daily.curtailment_cost,
            volume_mwh=daily.curtailment_volume,
            top_bmus=top_bmus,
        ),
        turnup=TurnupExport(
            replacement_cost_gbp=daily.turnup_cost,
            replacement_volume_mwh=daily.turnup_volume,
            so_flagged_payments_gbp=so_payments,
            so_flagged_volume_mwh=so_volume,
            top_companies=top_companies,
        ),
        total_cost_gbp=daily.curtailment_cost + daily.turnup_cost,
    )


def export_dates(
    store: TrackerStore,
    dates: list[date],
    output_dir: Path,
    owners_path: Path,
) -> list[Path]:
    owners = load_owners(owners_path)
    paths = []
    for settlement_date in dates:
        document = build_daily_export(store, settlement_date, owners)
        path = output_dir / "daily" / f"{settlement_date.isoformat()}.json"
        write_model(path, document)
        paths.append(path)
    return paths


def expected_dates(start: date, end: date) -> list[date]:
    if start > end:
        return []
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def build_summary_export(
    store: TrackerStore,
    today: date,
    *,
    allow_missing: bool,
) -> tuple[SummaryExport, list[date]]:
    year = today.year
    latest = today - timedelta(days=2)
    year_start = max(EARLIEST_DATE, date(year, 1, 1))
    expected = expected_dates(year_start, latest)
    stored = set(store.daily_result_dates(year_start, latest))
    missing = [day for day in expected if day not in stored]
    if missing and not allow_missing:
        raise MissingDatesError(missing)

    months = []
    for month in range(1, today.month + 1):
        month_start = max(year_start, date(year, month, 1))
        month_end = min(latest, date(year, month, monthrange(year, month)[1]))
        supported_days = expected_dates(month_start, month_end)
        aggregate = store.daily_aggregate(month_start, month_end)
        so_payments = store.so_payments_total(month_start, month_end)
        partial = month == today.month or any(
            day not in stored for day in supported_days
        )
        months.append(
            SummaryMonth(
                month=month,
                partial=partial,
                curtailment_cost_gbp=aggregate.curtailment_cost,
                curtailment_volume_mwh=aggregate.curtailment_volume,
                replacement_cost_gbp=aggregate.turnup_cost,
                so_flagged_payments_gbp=so_payments,
                total_cost_gbp=aggregate.curtailment_cost + aggregate.turnup_cost,
            )
        )
    totals = SummaryTotals(
        curtailment_cost_gbp=sum(item.curtailment_cost_gbp for item in months),
        curtailment_volume_mwh=sum(item.curtailment_volume_mwh for item in months),
        replacement_cost_gbp=sum(item.replacement_cost_gbp for item in months),
        total_cost_gbp=sum(item.total_cost_gbp for item in months),
        so_flagged_payments_gbp=sum(item.so_flagged_payments_gbp for item in months),
    )
    return (
        SummaryExport(
            generated_at=datetime.now(UTC),
            methodology_version=METHODOLOGY_VERSION,
            limitations=LIMITATIONS,
            year=year,
            totals=totals,
            months=months,
        ),
        missing,
    )


def export_summary(
    store: TrackerStore,
    output_dir: Path,
    today: date,
    *,
    allow_missing: bool,
) -> tuple[Path, list[date]]:
    document, missing = build_summary_export(store, today, allow_missing=allow_missing)
    path = output_dir / "summary.json"
    write_model(path, document)
    return path, missing


def write_model(path: Path, model: ExportModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(indent=2) + "\n")
