from __future__ import annotations

from importlib.metadata import EntryPoint
from typing import TYPE_CHECKING

import pytest
import typer
from pydantic import BaseModel, ConfigDict

from tri_al.config import Config, PluginSection
from tri_al.pipeline import Subscription
from tri_al.plugins import (
    ENTRY_POINT_GROUP,
    Plugin,
    PluginError,
    PluginLoadError,
    Registry,
    inspect_plugins,
    load_plugins,
)
from tri_al.plugins.registry import Contributions
from tri_al.storage import Migration, SqliteExtension
from tri_al.testing import FakeSource

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
        "alpha: written for plugin API 99, but this tri-al supports API 1; "
        "upgrade the plugin or tri-al"
    ]


def test_rejects_entry_point_name_that_differs_from_plugin_name(
    make_entry_point: MakeEntryPoint, make_plugin: MakePlugin
) -> None:
    with pytest.raises(PluginLoadError, match=r"alpha: entry point name doesn't match .* 'beta'"):
        load_plugins(Config(), [make_entry_point("alpha", make_plugin("beta"))])


def test_rejects_objects_that_are_not_plugins(make_entry_point: MakeEntryPoint) -> None:
    with pytest.raises(PluginLoadError, match=r"alpha: .* is a str, not a tri_al\.plugins\.Plugin"):
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
        "a: requires plugin 'b', which is disabled; run `tri-al plugins enable b`",
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
    assert "alpha: fake_tri_al_plugins:obj2 also provides a plugin" in problems(exc_info)


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
        "written for plugin API 99, but this tri-al supports API 1; upgrade the plugin or tri-al"
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

    with pytest.raises(NotImplementedError, match=r"Registry\.add_enricher is not implemented yet"):
        registry.add_enricher(object())


def test_registry_add_source_records_sources_by_name() -> None:
    contributions = Contributions()
    source = FakeSource()

    Registry("alpha", None, contributions).add_source(source)

    assert contributions.sources == {"fake": source}
    with pytest.raises(PluginError, match="a source named 'fake' was already added"):
        Registry("beta", None, contributions).add_source(FakeSource())


def test_registry_add_source_checks_the_interface() -> None:
    registry = Registry("alpha", None, Contributions())

    with pytest.raises(PluginError, match="object isn't a source"):
        registry.add_source(object())  # type: ignore[arg-type]


def test_registry_on_subscribes_in_load_order() -> None:
    contributions = Contributions()

    Registry("alpha", None, contributions).on("update.finished", print)
    Registry("beta", None, contributions).on("update.finished", repr)

    assert contributions.subscriptions == {
        "update.finished": [Subscription("alpha", print), Subscription("beta", repr)]
    }


def test_registry_on_knows_the_events() -> None:
    with pytest.raises(
        PluginError, match=r"unknown event 'update\.done'; events are update\.started"
    ):
        Registry("alpha", None, Contributions()).on("update.done", print)


def load_nothing(conn: object) -> None:
    pass


def test_registry_add_sqlite_extension_records_the_plugin() -> None:
    contributions = Contributions()

    Registry("vectors", None, contributions).add_sqlite_extension("vec0", load_nothing)

    assert contributions.sqlite_extensions == {
        "vec0": SqliteExtension("vec0", load_nothing, "vectors")
    }
    with pytest.raises(PluginError, match="'vec0' was already added by plugin 'vectors'"):
        Registry("other", None, contributions).add_sqlite_extension("vec0", load_nothing)


def test_registry_add_migrations_per_database_in_load_order() -> None:
    contributions = Contributions()
    first = (Migration(1, "a", "SELECT 1;"),)
    second = (Migration(1, "b", "SELECT 1;"), Migration(2, "c", "SELECT 1;"))

    Registry("zeta", None, contributions).add_migrations("trials", first)
    Registry("alpha", None, contributions).add_migrations("trials", second)
    Registry("alpha", None, contributions).add_migrations("app", first)

    assert contributions.migrations_for("trials") == {"zeta": first, "alpha": second}
    assert contributions.migrations_for("app") == {"alpha": first}


@pytest.mark.parametrize(
    ("database", "migrations", "message"),
    [
        ("trials", [Migration(2, "a", "")], "must be 1, 2, 3"),
        ("stats", [Migration(1, "a", "")], "unknown database 'stats'"),
    ],
)
def test_registry_add_migrations_checks_its_input(
    database: str, migrations: list[Migration], message: str
) -> None:
    with pytest.raises(PluginError, match=message):
        Registry("alpha", None, Contributions()).add_migrations(database, migrations)  # type: ignore[arg-type]


def test_registry_add_migrations_once_per_database() -> None:
    registry = Registry("alpha", None, Contributions())
    registry.add_migrations("trials", [Migration(1, "a", "")])

    with pytest.raises(PluginError, match="already added trials migrations"):
        registry.add_migrations("trials", [Migration(1, "a", "")])
