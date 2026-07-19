"""Command-line interface for the tracker."""

import typer

app = typer.Typer(help="Track Great Britain balancing-mechanism constraint costs.")


@app.callback()
def main() -> None:
    """Run tracker commands."""
