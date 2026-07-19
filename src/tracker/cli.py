"""Command-line interface for the tracker."""

from datetime import date
from pathlib import Path

import typer

from tracker.api import ElexonClient

app = typer.Typer(help="Track Great Britain balancing-mechanism constraint costs.")


@app.callback()
def main() -> None:
    """Run tracker commands."""


@app.command()
def fetch(
    settlement_date: str = typer.Option(
        ..., "--date", help="Settlement date to fetch."
    ),
    refresh: bool = typer.Option(False, help="Refresh cached responses."),
) -> None:
    """Cache bid and offer settlement stacks for one day."""
    try:
        parsed_date = date.fromisoformat(settlement_date)
    except ValueError as exc:
        raise typer.BadParameter("must be an ISO date (YYYY-MM-DD)") from exc
    with ElexonClient(Path("raw")) as client:
        for period in range(1, 51):
            client.bid_stack(parsed_date, period, refresh=refresh)
            client.offer_stack(parsed_date, period, refresh=refresh)
