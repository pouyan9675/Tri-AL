from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import typer
from typer.testing import CliRunner, Result

from tri_al import __version__
from tri_al.cli import create_app
from tri_al.cli.app import STUBS
from tri_al.cli.data import ProgressPrinter, describe, duration
from tri_al.pipeline import Progress
from tri_al.plugins import Plugin, Registry
from tri_al.testing import FakeSource, fake_study

if TYPE_CHECKING:
    from conftest import Install, MakePlugin

runner = CliRunner(env={"COLUMNS": "200"})


def run(*args: str, env: dict[str, str] | None = None) -> Result:
    return runner.invoke(create_app(), list(args), env=env)


def test_version() -> None:
    result = run("--version")

    assert result.exit_code == 0
    assert result.stdout == f"tri-al {__version__}\n"


@pytest.mark.parametrize("command", list(STUBS))
def test_unbuilt_commands_say_so(command: str) -> None:
    result = run(command)

    assert result.exit_code == 1
    assert result.stderr == f"tri-al {command}: not implemented yet\n"


def test_plugins_list_shows_installed_plugins(install: Install, make_plugin: MakePlugin) -> None:
    install(make_plugin("alpha", version="1.2", description="First."), make_plugin("beta"))
    Path("tri-al.toml").write_text("[plugins.beta]\nenabled = false\n")

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
    Path("tri-al.toml").write_text("[server]\nhots = 'x'\n")

    result = run("plugins", "list")

    assert result.exit_code == 1
    assert "server.hots: Extra inputs are not permitted" in result.stderr


def test_plugins_disable_then_enable(install: Install, make_plugin: MakePlugin) -> None:
    install(make_plugin("alpha"))
    config = Path("tri-al.toml")

    result = run("plugins", "disable", "alpha")

    assert result.exit_code == 0
    assert result.stdout == "Plugin 'alpha' disabled in tri-al.toml.\n"
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
    assert not Path("tri-al.toml").exists()


def test_plugins_enable_writes_to_tri_al_config(
    install: Install, make_plugin: MakePlugin, tmp_path: Path
) -> None:
    install(make_plugin("alpha"))
    path = tmp_path / "elsewhere.toml"

    result = run("plugins", "disable", "alpha", env={"TRI_AL_CONFIG": str(path)})

    assert result.exit_code == 0
    assert path.read_text() == "[plugins.alpha]\nenabled = false\n"


def test_plugins_enable_warns_when_environment_wins(
    install: Install, make_plugin: MakePlugin
) -> None:
    install(make_plugin("alpha"))
    Path("tri-al.toml").write_text("[plugins.alpha]\nenabled = false\n")

    result = run("plugins", "enable", "alpha", env={"TRI_AL_PLUGINS__ALPHA__ENABLED": "0"})

    assert result.exit_code == 0
    assert "TRI_AL_PLUGINS__ALPHA__ENABLED overrides the file" in result.stderr


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


# --- install and update ---------------------------------------------------------------------


def test_progress_lines() -> None:
    assert (
        describe(Progress("load", 5_000, 607_349, "trials")) == "load: 5,000 of 607,349 trials (1%)"
    )
    assert describe(Progress("download", 512_000_000, None, "bytes")) == "download: 512 MB"
    assert describe(Progress("index", message="building")) == "index: building"
    assert describe(Progress("check")) == "check"


@pytest.mark.parametrize(("seconds", "text"), [(12.34, "12.3s"), (245, "4m05s"), (3725, "1h02m")])
def test_durations(seconds: float, text: str) -> None:
    assert duration(seconds) == text


def test_progress_printer_throttles_within_a_stage() -> None:
    now = [0.0]
    lines: list[str] = []
    printer = ProgressPrinter(interval=5, clock=lambda: now[0], echo=lines.append)

    for t, report in [
        (0, Progress("load", 0, 10)),
        (1, Progress("load", 2, 10)),
        (6, Progress("load", 5, 10)),
        (7, Progress("index")),
    ]:
        now[0] = t
        printer(report)

    assert lines == ["load: 0 of 10 (0%)", "load: 5 of 10 (50%)", "index"]


def test_progress_printer_shows_how_a_stage_ended() -> None:
    lines: list[str] = []
    printer = ProgressPrinter(interval=5, clock=lambda: 0.0, echo=lines.append)

    for report in [Progress("load", 0, 10), Progress("load", 10, 10), Progress("index")]:
        printer(report)

    assert lines == ["load: 0 of 10 (0%)", "load: 10 of 10 (100%)", "index"]


def source_plugin(make_plugin: MakePlugin, source: FakeSource) -> Plugin:
    return make_plugin("fakes", register=lambda registry: registry.add_source(source))


def test_install_and_update(install: Install, make_plugin: MakePlugin) -> None:
    studies = (fake_study("F1", updated="2026-10-01"), fake_study("F2", updated="2026-10-02"))
    install(source_plugin(make_plugin, FakeSource(studies=studies)))

    result = run("install", "--workers", "0")

    assert result.exit_code == 0, result.output
    assert "Installed into data/trials.db" in result.stdout
    assert "fake: 2 fetched, 2 new, 0 updated, 0 unchanged, 0 failed" in result.stdout
    assert Path("data/trials.db").exists()

    result = run("update")

    assert result.exit_code == 0, result.output
    assert "fake: 1 fetched, 0 new, 0 updated, 1 unchanged, 0 failed" not in result.stdout
    assert "fake: 0 fetched" in result.stdout


def test_install_into_another_directory(
    install: Install, make_plugin: MakePlugin, tmp_path: Path
) -> None:
    install(source_plugin(make_plugin, FakeSource(studies=(fake_study("F1"),))))

    result = run("install", "--workers", "0", "--data-dir", str(tmp_path / "elsewhere"))

    assert result.exit_code == 0, result.output
    assert (tmp_path / "elsewhere" / "trials.db").exists()


def test_install_explains_errors(install: Install, make_plugin: MakePlugin) -> None:
    install(source_plugin(make_plugin, FakeSource(studies=(fake_study("F1"),))))
    run("install", "--workers", "0")

    result = run("install", "--workers", "0")

    assert result.exit_code == 1
    assert "error: data/trials.db already exists" in result.stderr


def test_update_needs_an_install(install: Install, make_plugin: MakePlugin) -> None:
    install(source_plugin(make_plugin, FakeSource()))

    result = run("update")

    assert result.exit_code == 1
    assert "run `tri-al install` first" in result.stderr


def test_install_needs_a_source(install: Install) -> None:
    install()

    result = run("install")

    assert result.exit_code == 1
    assert "no source plugin is enabled" in result.stderr


def test_install_reports_plugins_that_dont_load(install: Install, make_plugin: MakePlugin) -> None:
    install(make_plugin("alpha", api_version=99))

    result = run("install")

    assert result.exit_code == 1
    assert "written for plugin API 99" in result.stderr
