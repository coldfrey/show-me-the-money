from typer.testing import CliRunner

from tracker.cli import app


def test_help_exits_successfully() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "constraint costs" in result.stdout
