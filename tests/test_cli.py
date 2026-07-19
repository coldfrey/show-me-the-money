from datetime import date, timedelta

from typer.testing import CliRunner

from tracker.cli import app


def test_help_exits_successfully() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "constraint costs" in result.stdout


def test_pre_earliest_date_is_rejected_before_http() -> None:
    result = CliRunner().invoke(app, ["fetch", "--date", "2025-12-31"])

    assert result.exit_code == 2
    assert "dates must be in" in result.stderr


def test_future_date_is_rejected_before_http() -> None:
    future = (date.today() + timedelta(days=1)).isoformat()
    result = CliRunner().invoke(app, ["ingest", "--date", future])

    assert result.exit_code == 2
    assert "dates must be in" in result.stderr


def test_date_and_range_are_mutually_exclusive() -> None:
    result = CliRunner().invoke(
        app,
        [
            "ingest",
            "--date",
            "2026-07-10",
            "--from",
            "2026-07-09",
            "--to",
            "2026-07-10",
        ],
    )

    assert result.exit_code == 2
    assert "exactly one" in result.stderr


def test_export_summary_strict_mode_exits_one_on_gap(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("tracker.cli.DATABASE_PATH", tmp_path / "tracker.duckdb")
    monkeypatch.setattr("tracker.cli.OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr("tracker.cli.today_in_london", lambda: date(2026, 1, 4))

    result = CliRunner().invoke(app, ["export-summary"])

    assert result.exit_code == 1
    assert "2026-01-01" in result.stderr
    assert "2026-01-02" in result.stderr
