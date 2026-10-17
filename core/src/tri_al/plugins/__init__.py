"""The plugin system: discovery through entry points, checks, ordering and registration."""

from tri_al.plugins.errors import PluginError, PluginLoadError
from tri_al.plugins.loader import (
    LoadedPlugins,
    PluginStatus,
    discover,
    inspect_plugins,
    load_plugins,
)
from tri_al.plugins.plugin import API_VERSION, ENTRY_POINT_GROUP, Plugin
from tri_al.plugins.registry import Contributions, Registry

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
