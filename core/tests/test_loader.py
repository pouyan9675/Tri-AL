from __future__ import annotations

from importlib.metadata import EntryPoint
from typing import TYPE_CHECKING

import pytest
import typer
from pydantic import BaseModel, ConfigDict

from trial_al.config import Config, PluginSection
from trial_al.plugins import (
    ENTRY_POINT_GROUP,
    Plugin,
    PluginError,
    PluginLoadError,
    Registry,
    inspect_plugins,
    load_plugins,
)
from trial_al.plugins.registry import Contributions

if TYPE_CHECKING:
    from conftest import MakeEntryPoint, MakePlugin


class GreetingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    greeting: str = "Hello"
    repeat: int = 1


def config(**sections: dict[str, object]) -> Config:
    return Config(
        plugins={name: PluginSection.model_validate(values) for name, values in sections.items()}
    )


def problems(exc_info: pytest.ExceptionInfo[PluginLoadError]) -> str:
    return "\n".join(exc_info.value.problems)


def test_loads_enabled_plugins(
    make_entry_point: MakeEntryPoint, make_plugin: MakePlugin, registered: list[str]
) -> None:
    plugin = make_plugin("alpha")

    loaded = load_plugins(Config(), [make_entry_point("alpha", plugin)])

    assert loaded.plugins == [plugin]
    assert registered == ["alpha"]


def test_disabled_plugins_are_not_imported(registered: list[str]) -> None:
    missing = EntryPoint(name="ghost", value="no_such_module:plugin", group=ENTRY_POINT_GROUP)

    loaded = load_plugins(config(ghost={"enabled": False}), [missing])

    assert loaded.plugins == []
    assert registered == []


def test_validates_settings_and_passes_them_to_register(make_entry_point: MakeEntryPoint) -> None:
    seen: list[BaseModel | None] = []
    plugin = Plugin(
        name="greeter",
        version="1.0",
        api_version=1,
        settings=GreetingSettings,
        register=lambda registry: seen.append(registry.settings),
    )

    loaded = load_plugins(
        config(greeter={"greeting": "Hi", "repeat": "3"}), [make_entry_point("greeter", plugin)]
    )

    assert seen == [GreetingSettings(greeting="Hi", repeat=3)]
    assert loaded.settings == {"greeter": GreetingSettings(greeting="Hi", repeat=3)}


def test_orders_plugins_by_requires(
    make_entry_point: MakeEntryPoint, make_plugin: MakePlugin, registered: list[str]
) -> None:
    eps = [
        make_entry_point("a", make_plugin("a", requires=("b",))),
        make_entry_point("b", make_plugin("b", requires=("c",))),
        make_entry_point("c", make_plugin("c")),
    ]

    loaded = load_plugins(Config(), eps)

    assert registered == ["c", "b", "a"]
    assert [plugin.name for plugin in loaded.plugins] == ["c", "b", "a"]


def test_rejects_other_plugin_api_versions(
    make_entry_point: MakeEntryPoint, make_plugin: MakePlugin
) -> None:
    with pytest.raises(PluginLoadError) as exc_info:
        load_plugins(Config(), [make_entry_point("alpha", make_plugin("alpha", api_version=99))])

    assert exc_info.value.problems == [
        "alpha: written for plugin API 99, but this trial-al supports API 1; "
        "upgrade the plugin or trial-al"
    ]


def test_rejects_entry_point_name_that_differs_from_plugin_name(
    make_entry_point: MakeEntryPoint, make_plugin: MakePlugin
) -> None:
    with pytest.raises(PluginLoadError, match=r"alpha: entry point name doesn't match .* 'beta'"):
        load_plugins(Config(), [make_entry_point("alpha", make_plugin("beta"))])


def test_rejects_objects_that_are_not_plugins(make_entry_point: MakeEntryPoint) -> None:
    with pytest.raises(
        PluginLoadError, match=r"alpha: .* is a str, not a trial_al\.plugins\.Plugin"
    ):
        load_plugins(Config(), [make_entry_point("alpha", "not a plugin")])


def test_reports_import_failures() -> None:
    broken = EntryPoint(name="broken", value="no_such_module:plugin", group=ENTRY_POINT_GROUP)

    with pytest.raises(PluginLoadError, match="broken: failed to import no_such_module:plugin"):
        load_plugins(Config(), [broken])


def test_reports_missing_and_disabled_requirements(
    make_entry_point: MakeEntryPoint, make_plugin: MakePlugin, registered: list[str]
) -> None:
    eps = [
        make_entry_point("a", make_plugin("a", requires=("b", "nope"))),
        make_entry_point("b", make_plugin("b")),
    ]

    with pytest.raises(PluginLoadError) as exc_info:
        load_plugins(config(b={"enabled": False}), eps)

    assert exc_info.value.problems == [
        "a: requires plugin 'b', which is disabled; run `trial-al plugins enable b`",
        "a: requires plugin 'nope', which is not installed",
    ]
    assert registered == []


def test_reports_requirement_cycles(
    make_entry_point: MakeEntryPoint, make_plugin: MakePlugin
) -> None:
    eps = [
        make_entry_point("a", make_plugin("a", requires=("b",))),
        make_entry_point("b", make_plugin("b", requires=("a",))),
    ]

    with pytest.raises(PluginLoadError, match="requires form a cycle"):
        load_plugins(Config(), eps)


def test_reports_invalid_settings(
    make_entry_point: MakeEntryPoint, make_plugin: MakePlugin
) -> None:
    plugin = make_plugin("greeter", settings=GreetingSettings)

    with pytest.raises(PluginLoadError) as exc_info:
        load_plugins(
            config(greeter={"repeat": "often", "colour": "red"}),
            [make_entry_point("greeter", plugin)],
        )

    assert exc_info.value.problems == [
        "greeter: invalid setting repeat: Input should be a valid integer, unable to parse "
        "string as an integer",
        "greeter: invalid setting colour: Extra inputs are not permitted",
    ]


def test_rejects_settings_for_plugin_without_settings_model(
    make_entry_point: MakeEntryPoint, make_plugin: MakePlugin
) -> None:
    with pytest.raises(PluginLoadError, match=r"takes no settings, but \[plugins.alpha\] sets x"):
        load_plugins(config(alpha={"x": 1}), [make_entry_point("alpha", make_plugin("alpha"))])


def test_rejects_invalid_and_duplicate_names(
    make_entry_point: MakeEntryPoint, make_plugin: MakePlugin
) -> None:
    eps = [
        make_entry_point("Bad-Name", make_plugin("Bad-Name")),
        make_entry_point("alpha", make_plugin("alpha")),
        make_entry_point("alpha", make_plugin("alpha")),
    ]

    with pytest.raises(PluginLoadError) as exc_info:
        load_plugins(Config(), eps)

    assert "Bad-Name: invalid name" in problems(exc_info)
    assert "alpha: fake_trial_al_plugins:obj2 also provides a plugin" in problems(exc_info)


def test_collects_every_problem_before_registering(
    make_entry_point: MakeEntryPoint, make_plugin: MakePlugin, registered: list[str]
) -> None:
    eps = [
        make_entry_point("a", make_plugin("a", api_version=0)),
        make_entry_point("b", make_plugin("b")),
        make_entry_point("c", make_plugin("c", requires=("nope",))),
    ]

    with pytest.raises(PluginLoadError) as exc_info:
        load_plugins(Config(), eps)

    assert [problem.split(":")[0] for problem in exc_info.value.problems] == ["a", "c"]
    assert registered == []


def test_reports_register_failures(make_entry_point: MakeEntryPoint) -> None:
    def register(registry: Registry) -> None:
        raise RuntimeError("boom")

    plugin = Plugin(name="alpha", version="1.0", api_version=1, register=register)

    with pytest.raises(PluginLoadError, match=r"alpha: register\(\) failed: boom"):
        load_plugins(Config(), [make_entry_point("alpha", plugin)])


def test_inspect_reports_every_plugin_without_raising(
    make_entry_point: MakeEntryPoint, make_plugin: MakePlugin, registered: list[str]
) -> None:
    eps = [
        make_entry_point("on", make_plugin("on", version="2.1", description="Enabled.")),
        make_entry_point("off", make_plugin("off", api_version=99)),
    ]

    statuses = inspect_plugins(config(off={"enabled": False}, gone={}), eps)

    assert [(s.name, s.enabled, s.installed, s.version) for s in statuses] == [
        ("gone", True, False, None),
        ("off", False, True, "1.0"),
        ("on", True, True, "2.1"),
    ]
    assert statuses[1].problems == [
        "written for plugin API 99, but this trial-al supports API 1; "
        "upgrade the plugin or trial-al"
    ]
    assert statuses[2].problems == []
    assert statuses[2].description == "Enabled."
    assert registered == []


def test_registry_add_cli_records_one_app_per_plugin() -> None:
    contributions = Contributions()
    registry = Registry("alpha", None, contributions)
    cli = typer.Typer()

    registry.add_cli(cli)

    assert contributions.cli == {"alpha": cli}
    with pytest.raises(PluginError, match="already added a CLI"):
        registry.add_cli(typer.Typer())


def test_registry_methods_from_later_milestones_are_stubs() -> None:
    registry = Registry("alpha", None, Contributions())

    with pytest.raises(NotImplementedError, match=r"Registry\.add_source is not implemented yet"):
        registry.add_source(object())
