import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

import trial_al_sample
from trial_al.cli import create_app
from trial_al.plugins import discover


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for var in list(os.environ):
        if var.startswith("TRIAL_AL_"):
            monkeypatch.delenv(var)
    monkeypatch.chdir(tmp_path)


def test_is_discovered_through_its_entry_point() -> None:
    entry_points = {ep.name: ep for ep in discover()}

    assert entry_points["sample"].load() is trial_al_sample.plugin


@pytest.mark.parametrize(
    ("config", "env", "expected"),
    [
        ("", {}, "Hello, Ada!\n"),
        ('[plugins.sample]\ngreeting = "Hi"\n', {}, "Hi, Ada!\n"),
        ("", {"TRIAL_AL_PLUGINS__SAMPLE__GREETING": "Hey"}, "Hey, Ada!\n"),
    ],
    ids=["default", "file", "env"],
)
def test_hello_uses_the_configured_greeting(
    monkeypatch: pytest.MonkeyPatch, config: str, env: dict[str, str], expected: str
) -> None:
    Path("trial-al.toml").write_text(config)
    for var, value in env.items():
        monkeypatch.setenv(var, value)

    result = CliRunner().invoke(create_app(), ["sample", "hello", "--name", "Ada"])

    assert result.exit_code == 0
    assert result.stdout == expected
