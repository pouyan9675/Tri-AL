from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import typer
from typer.testing import CliRunner, Result

from trial_al import __version__
from trial_al.cli import create_app
from trial_al.cli.app import STUBS
from trial_al.plugins import Registry

if TYPE_CHECKING:
    from conftest import Install, MakePlugin

runner = CliRunner(env={"COLUMNS": "200"})


def run(*args: str, env: dict[str, str] | None = None) -> Result:
    return runner.invoke(create_app(), list(args), env=env)


def test_version() -> None:
    result = run("--version")

    assert result.exit_code == 0
    assert result.stdout == f"trial-al {__version__}\n"


@pytest.mark.parametrize("command", list(STUBS))
def test_unbuilt_commands_say_so(command: str) -> None:
    result = run(command)

    assert result.exit_code == 1
    assert result.stderr == f"trial-al {command}: not implemented yet\n"


def test_plugins_list_shows_installed_plugins(install: Install, make_plugin: MakePlugin) -> None:
    install(make_plugin("alpha", version="1.2", description="First."), make_plugin("beta"))
    Path("trial-al.toml").write_text("[plugins.beta]\nenabled = false\n")

    result = run("plugins", "list")

    assert result.exit_code == 0
    rows = [line.split("│")[1:-1] for line in result.stdout.splitlines() if line.count("│") > 2]
    assert [[cell.strip() for cell in row] for row in rows] == [
        ["alpha", "1.2", "yes", "ok", "First."],
        ["beta", "1.0", "no", "ok", ""],
    ]


def test_plugins_list_shows_problems(install: Install, make_plugin: MakePlugin) -> None:
    install(make_plugin("alpha", api_version=99))

    result = run("plugins", "list")

    assert result.exit_code == 0
    assert "written for plugin API 99" in result.stdout


def test_plugins_list_without_plugins(install: Install) -> None:
    install()

    result = run("plugins", "list")

    assert result.exit_code == 0
    assert result.stdout == "No plugins installed.\n"


def test_plugins_list_reports_config_errors(install: Install) -> None:
    install()
    Path("trial-al.toml").write_text("[server]\nhots = 'x'\n")

    result = run("plugins", "list")

    assert result.exit_code == 1
    assert "server.hots: Extra inputs are not permitted" in result.stderr


def test_plugins_disable_then_enable(install: Install, make_plugin: MakePlugin) -> None:
    install(make_plugin("alpha"))
    config = Path("trial-al.toml")

    result = run("plugins", "disable", "alpha")

    assert result.exit_code == 0
    assert result.stdout == "Plugin 'alpha' disabled in trial-al.toml.\n"
    assert config.read_text() == "[plugins.alpha]\nenabled = false\n"
    assert run("plugins", "disable", "alpha").stdout == "Plugin 'alpha' is already disabled.\n"

    result = run("plugins", "enable", "alpha")

    assert result.exit_code == 0
    assert config.read_text() == "[plugins.alpha]\nenabled = true\n"


def test_plugins_enable_rejects_unknown_names(install: Install, make_plugin: MakePlugin) -> None:
    install(make_plugin("alpha"))

    result = run("plugins", "enable", "nope")

    assert result.exit_code == 1
    assert result.stderr == "error: no installed plugin named 'nope'; installed: alpha\n"
    assert not Path("trial-al.toml").exists()


def test_plugins_enable_writes_to_trial_al_config(
    install: Install, make_plugin: MakePlugin, tmp_path: Path
) -> None:
    install(make_plugin("alpha"))
    path = tmp_path / "elsewhere.toml"

    result = run("plugins", "disable", "alpha", env={"TRIAL_AL_CONFIG": str(path)})

    assert result.exit_code == 0
    assert path.read_text() == "[plugins.alpha]\nenabled = false\n"


def test_plugins_enable_warns_when_environment_wins(
    install: Install, make_plugin: MakePlugin
) -> None:
    install(make_plugin("alpha"))
    Path("trial-al.toml").write_text("[plugins.alpha]\nenabled = false\n")

    result = run("plugins", "enable", "alpha", env={"TRIAL_AL_PLUGINS__ALPHA__ENABLED": "0"})

    assert result.exit_code == 0
    assert "TRIAL_AL_PLUGINS__ALPHA__ENABLED overrides the file" in result.stderr


def test_plugins_disable_warns_about_dependents(install: Install, make_plugin: MakePlugin) -> None:
    install(make_plugin("base"), make_plugin("child", requires=("base",)))

    result = run("plugins", "disable", "base")

    assert result.exit_code == 0
    assert "warning: child: requires plugin 'base', which is disabled" in result.stderr


def test_enabled_plugins_add_command_groups(install: Install, make_plugin: MakePlugin) -> None:
    def register(registry: Registry) -> None:
        cli = typer.Typer()

        @cli.command()
        def ping() -> None:
            typer.echo(f"pong from {registry.plugin}")

        registry.add_cli(cli)

    install(make_plugin("alpha", register=register))

    result = run("alpha", "ping")

    assert result.exit_code == 0
    assert result.stdout == "pong from alpha\n"


def test_core_commands_work_when_plugins_cannot_load(
    install: Install, make_plugin: MakePlugin, capsys: pytest.CaptureFixture[str]
) -> None:
    install(make_plugin("alpha", api_version=99))

    app = create_app()
    result = runner.invoke(app, ["plugins", "list"])

    assert "plugin commands are unavailable" in capsys.readouterr().err
    assert result.exit_code == 0
    assert "written for plugin API 99" in result.stdout
