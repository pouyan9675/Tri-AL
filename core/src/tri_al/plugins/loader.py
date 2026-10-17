"""Find, check, order and load plugins (docs/design.md §5.6)."""

import graphlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from importlib.metadata import EntryPoint, entry_points

from pydantic import BaseModel, ValidationError

from tri_al.config import Config
from tri_al.plugins.errors import PluginLoadError
from tri_al.plugins.plugin import API_VERSION, ENTRY_POINT_GROUP, NAME_PATTERN, Plugin
from tri_al.plugins.registry import Contributions, Registry


@dataclass
class LoadedPlugins:
    """The enabled plugins in load order, their validated settings, and what they registered."""

    plugins: list[Plugin] = field(default_factory=list)
    settings: dict[str, BaseModel | None] = field(default_factory=dict)
    contributions: Contributions = field(default_factory=Contributions)


@dataclass
class PluginStatus:
    """What ``inspect_plugins`` knows about one plugin."""

    name: str
    enabled: bool
    installed: bool = True
    version: str | None = None
    description: str = ""
    problems: list[str] = field(default_factory=list)


def discover() -> list[EntryPoint]:
    """The installed plugins' entry points, sorted by name."""
    return sorted(entry_points(group=ENTRY_POINT_GROUP), key=lambda ep: ep.name)


def load_plugins(config: Config, eps: Iterable[EntryPoint] | None = None) -> LoadedPlugins:
    """Import, check and register the enabled plugins, each after the plugins it requires.

    Only enabled plugins are imported. Every problem is collected before any plugin
    registers and raised together as one PluginLoadError, so a broken setup fails at
    startup with the whole list rather than at first use.
    """
    survey = _survey(config, discover() if eps is None else eps, import_disabled=False)
    problems = [
        f"{status.name}: {problem}"
        for status in survey.statuses.values()
        if status.enabled and status.installed
        for problem in status.problems
    ]
    if problems:
        raise PluginLoadError(problems)

    loaded = LoadedPlugins()
    for name in survey.order:
        plugin, settings = survey.plugins[name], survey.settings[name]
        try:
            plugin.register(Registry(name, settings, loaded.contributions))
        except Exception as exc:
            raise PluginLoadError([f"{name}: register() failed: {exc}"]) from exc
        loaded.plugins.append(plugin)
        loaded.settings[name] = settings
    return loaded


def inspect_plugins(config: Config, eps: Iterable[EntryPoint] | None = None) -> list[PluginStatus]:
    """Describe every installed plugin and every configured one that isn't installed.

    Imports disabled plugins too, to read their metadata, but registers nothing and never
    raises: problems are reported per plugin.
    """
    survey = _survey(config, discover() if eps is None else eps, import_disabled=True)
    return sorted(survey.statuses.values(), key=lambda status: status.name)


@dataclass
class _Survey:
    statuses: dict[str, PluginStatus]
    plugins: dict[str, Plugin]  # enabled plugins that imported
    settings: dict[str, BaseModel | None]
    order: list[str]


def _survey(config: Config, eps: Iterable[EntryPoint], *, import_disabled: bool) -> _Survey:
    statuses: dict[str, PluginStatus] = {}
    imported: dict[str, Plugin] = {}
    for ep in eps:
        if ep.name in statuses:
            statuses[ep.name].problems.append(
                f"{_package(ep)} also provides a plugin with this name; uninstall one of them"
            )
            continue
        status = statuses[ep.name] = PluginStatus(
            name=ep.name,
            enabled=config.plugin_enabled(ep.name),
            version=ep.dist.version if ep.dist else None,
        )
        if not NAME_PATTERN.fullmatch(ep.name):
            status.problems.append(
                f"invalid name (from {_package(ep)}); plugin names use lowercase letters, "
                "digits and underscores"
            )
        elif status.enabled or import_disabled:
            plugin, problems = _resolve(ep)
            status.problems += problems
            if plugin is not None:
                status.version, status.description = plugin.version, plugin.description
                imported[ep.name] = plugin

    enabled = {name: plugin for name, plugin in imported.items() if statuses[name].enabled}
    settings: dict[str, BaseModel | None] = {}
    for name, plugin in enabled.items():
        statuses[name].problems += _check_requires(plugin, statuses)
        settings[name], problems = _validate_settings(plugin, config.plugin_settings(name))
        statuses[name].problems += problems
    order = _order(enabled, statuses)

    for name, section in config.plugins.items():
        if name not in statuses:
            statuses[name] = PluginStatus(name=name, enabled=section.enabled, installed=False)
    return _Survey(statuses, enabled, settings, order)


def _resolve(ep: EntryPoint) -> tuple[Plugin | None, list[str]]:
    try:
        obj = ep.load()
    except Exception as exc:
        return None, [f"failed to import {ep.value}: {exc!r}"]
    if not isinstance(obj, Plugin):
        return None, [f"{ep.value} is a {type(obj).__name__}, not a tri_al.plugins.Plugin"]
    problems = []
    if obj.name != ep.name:
        problems.append(f"entry point name doesn't match Plugin.name {obj.name!r}")
    if obj.api_version != API_VERSION:
        problems.append(
            f"written for plugin API {obj.api_version}, but this tri-al supports "
            f"API {API_VERSION}; upgrade the plugin or tri-al"
        )
    return obj, problems


def _check_requires(plugin: Plugin, statuses: dict[str, PluginStatus]) -> list[str]:
    problems = []
    for required in plugin.requires:
        status = statuses.get(required)
        if status is None:
            problems.append(f"requires plugin {required!r}, which is not installed")
        elif not status.enabled:
            problems.append(
                f"requires plugin {required!r}, which is disabled; "
                f"run `tri-al plugins enable {required}`"
            )
    return problems


def _validate_settings(
    plugin: Plugin, data: dict[str, object]
) -> tuple[BaseModel | None, list[str]]:
    if plugin.settings is None:
        if data:
            keys = ", ".join(sorted(data))
            return None, [f"takes no settings, but [plugins.{plugin.name}] sets {keys}"]
        return None, []
    try:
        return plugin.settings.model_validate(data), []
    except ValidationError as exc:
        return None, [
            f"invalid setting {'.'.join(map(str, error['loc'])) or '(section)'}: {error['msg']}"
            for error in exc.errors()
        ]


def _order(plugins: dict[str, Plugin], statuses: dict[str, PluginStatus]) -> list[str]:
    """Names in load order: each plugin after the ones it requires. Reports cycles."""
    graph = {name: [r for r in plugin.requires if r in plugins] for name, plugin in plugins.items()}
    try:
        return list(graphlib.TopologicalSorter(graph).static_order())
    except graphlib.CycleError as exc:
        cycle: list[str] = exc.args[1]
        for name in set(cycle):
            statuses[name].problems.append(f"requires form a cycle: {' -> '.join(cycle)}")
        return []


def _package(ep: EntryPoint) -> str:
    return f"{ep.dist.name} {ep.dist.version}" if ep.dist else ep.value
