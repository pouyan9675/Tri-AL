import itertools
import os
import sys
import types
from collections.abc import Callable
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Any

import pytest

from trial_al.plugins import API_VERSION, ENTRY_POINT_GROUP, Plugin, Registry, loader

type MakeEntryPoint = Callable[[str, object], EntryPoint]
type MakePlugin = Callable[..., Plugin]
type Install = Callable[..., None]


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Run each test in an empty directory, without the caller's TRIAL_AL_* variables."""
    for var in list(os.environ):
        if var.startswith("TRIAL_AL_"):
            monkeypatch.delenv(var)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def make_entry_point(monkeypatch: pytest.MonkeyPatch) -> MakeEntryPoint:
    """Make entry points that load the given objects, without installing a package."""
    module = types.ModuleType("fake_trial_al_plugins")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    counter = itertools.count()

    def make(name: str, obj: object) -> EntryPoint:
        attr = f"obj{next(counter)}"
        setattr(module, attr, obj)
        return EntryPoint(name=name, value=f"{module.__name__}:{attr}", group=ENTRY_POINT_GROUP)

    return make


@pytest.fixture
def registered() -> list[str]:
    """Names of plugins whose register() ran, in order."""
    return []


@pytest.fixture
def make_plugin(registered: list[str]) -> MakePlugin:
    """Make a compatible plugin that records its registration in ``registered``."""

    def make(name: str, **fields: Any) -> Plugin:
        def register(registry: Registry) -> None:
            registered.append(registry.plugin)

        defaults: dict[str, Any] = {"version": "1.0", "api_version": API_VERSION}
        return Plugin(name=name, **{"register": register, **defaults, **fields})

    return make


@pytest.fixture
def install(monkeypatch: pytest.MonkeyPatch, make_entry_point: MakeEntryPoint) -> Install:
    """Make discovery see exactly the given plugins."""

    def install(*plugins: Plugin) -> None:
        eps = [make_entry_point(plugin.name, plugin) for plugin in plugins]
        monkeypatch.setattr(loader, "discover", lambda: eps)

    return install
