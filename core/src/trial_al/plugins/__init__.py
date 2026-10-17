"""The plugin system: discovery through entry points, checks, ordering and registration."""

from trial_al.plugins.errors import PluginError, PluginLoadError
from trial_al.plugins.loader import (
    LoadedPlugins,
    PluginStatus,
    discover,
    inspect_plugins,
    load_plugins,
)
from trial_al.plugins.plugin import API_VERSION, ENTRY_POINT_GROUP, Plugin
from trial_al.plugins.registry import Contributions, Registry

__all__ = [
    "API_VERSION",
    "ENTRY_POINT_GROUP",
    "Contributions",
    "LoadedPlugins",
    "Plugin",
    "PluginError",
    "PluginLoadError",
    "PluginStatus",
    "Registry",
    "discover",
    "inspect_plugins",
    "load_plugins",
]
