"""Command-line interface for the tracker."""

from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import typer

from tracker.api import ElexonClient
from tracker.config import EARLIEST_DATE
from tracker.ingest import ingest_dates, refresh_reference
from tracker.store import TrackerStore
from tracker.validate import run_validation

app = typer.Typer(help="Track Great Britain balancing-mechanism constraint costs.")
RAW_DIR = Path("raw")
DATABASE_PATH = Path("data/tracker.duckdb")
WAIVER_PATH = Path("validation/waivers.yml")


@app.callback()
def main() -> None:
    """Run tracker commands."""


@app.command()
def fetch(
    settlement_date: str | None = typer.Option(None, "--date"),
    from_date: str | None = typer.Option(None, "--from"),
    to_date: str | None = typer.Option(None, "--to"),
    refresh: bool = typer.Option(False, help="Refresh cached responses."),
) -> None:
    """Cache bid and offer settlement stacks."""
    dates = resolve_date_range(settlement_date, from_date, to_date)
    with ElexonClient(RAW_DIR) as client:
        for requested_date in dates:
            for period in range(1, 51):
                client.bid_stack(requested_date, period, refresh=refresh)
                client.offer_stack(requested_date, period, refresh=refresh)


@app.command()
def ingest(
    settlement_date: str | None = typer.Option(None, "--date"),
    from_date: str | None = typer.Option(None, "--from"),
    to_date: str | None = typer.Option(None, "--to"),
    refresh: bool = typer.Option(False, help="Refresh cached stack responses."),
    refresh_bmu_reference: bool = typer.Option(False, "--refresh-reference"),
) -> None:
    """Fetch, store, and calculate one date or an inclusive range."""
    no_dates = settlement_date is None and from_date is None and to_date is None
    if no_dates and refresh_bmu_reference:
        with ElexonClient(RAW_DIR) as client, TrackerStore(DATABASE_PATH) as store:
            count = refresh_reference(client, store)
        typer.echo(f"Refreshed {count} BMU reference rows")
        return
    dates = resolve_date_range(settlement_date, from_date, to_date)
    with ElexonClient(RAW_DIR) as client, TrackerStore(DATABASE_PATH) as store:
        results = ingest_dates(
            client,
            store,
            dates,
            refresh=refresh,
            refresh_reference=refresh_bmu_reference,
        )
    for result in results:
        typer.echo(
            f"{result.date}: curtailment £{result.curtailment.cost_gbp:.2f}, "
            f"{result.curtailment.volume_mwh:.2f} MWh"
        )


@app.command()
def show(settlement_date: str = typer.Option(..., "--date")) -> None:
    """Print a stored daily result."""
    requested_date = resolve_date_range(settlement_date, None, None)[0]
    with TrackerStore(DATABASE_PATH) as store:
        result = store.daily_result(requested_date)
    if result is None:
        typer.echo(f"No result stored for {requested_date}", err=True)
        raise typer.Exit(1)
    typer.echo(
        f"date={result.date} curtailment_cost={result.curtailment_cost:.6f} "
        f"curtailment_volume={result.curtailment_volume:.6f} "
        f"turnup_cost={result.turnup_cost:.6f} "
        f"turnup_volume={result.turnup_volume:.6f} "
        f"total_cost={result.total_cost:.6f}"
    )


@app.command("validate")
def validate_command(
    year: int = typer.Option(..., "--year"),
    month: int | None = typer.Option(None, "--month", min=1, max=12),
) -> None:
    """Compare complete stored months with wastedwind.energy."""
    latest = today_in_london() - timedelta(days=2)
    try:
        with ElexonClient(RAW_DIR) as client, TrackerStore(DATABASE_PATH) as store:
            report = run_validation(client, store, year, month, latest, WAIVER_PATH)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    for item in report.comparisons:
        typer.echo(
            f"{item.year}-{item.month:02d} {item.metric}: "
            f"ours={item.ours:.6f} theirs={item.theirs:.6f} "
            f"delta={item.deviation_pct:.6f}% {item.status}"
        )
    if not report.passed:
        raise typer.Exit(1)


def resolve_date_range(
    settlement_date: str | None,
    from_date: str | None,
    to_date: str | None,
    *,
    latest: date | None = None,
) -> list[date]:
    """Validate exclusive date/range forms before any I/O occurs."""
    if settlement_date is not None and (from_date is not None or to_date is not None):
        raise typer.BadParameter("use exactly one of --date or --from/--to")
    if settlement_date is None and (from_date is None or to_date is None):
        raise typer.BadParameter("provide --date or both --from and --to")
    if settlement_date is not None:
        start = end = parse_iso_date(settlement_date, "--date")
    else:
        assert from_date is not None and to_date is not None
        start = parse_iso_date(from_date, "--from")
        end = parse_iso_date(to_date, "--to")
    if start > end:
        raise typer.BadParameter("--from must be on or before --to")
    maximum = latest or (today_in_london() - timedelta(days=1))
    if start < EARLIEST_DATE or end > maximum:
        raise typer.BadParameter(
            f"dates must be in [{EARLIEST_DATE.isoformat()}, {maximum.isoformat()}]"
        )
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def parse_iso_date(value: str, option: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(
            f"must be an ISO date (YYYY-MM-DD), got {value!r}", param_hint=option
        ) from exc


def today_in_london() -> date:
    from datetime import datetime

    return datetime.now(ZoneInfo("Europe/London")).date()
