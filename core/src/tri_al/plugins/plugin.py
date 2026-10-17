"""The object every plugin exposes through the ``tri_al.plugins`` entry-point group."""

import re
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

from tri_al.plugins.registry import Registry

API_VERSION = 1
"""The plugin API this core implements. Plugins declare the version they were written for."""

ENTRY_POINT_GROUP = "tri_al.plugins"

NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]*")
"""Plugin names map to config sections, env vars and CLI groups, so they stay simple."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Plugin:
    """A plugin's metadata and its ``register`` function.

    A plugin package points an entry point named after the plugin at an instance:

        [project.entry-points."tri_al.plugins"]
        sample = "tri_al_sample:plugin"

    ``api_version`` must be the literal version the plugin was written against, not
    ``tri_al.plugins.API_VERSION``, or the compatibility check can never fail.

    ``settings`` validates the plugin's ``[plugins.<name>]`` config section. Give it
    ``extra="forbid"`` so typos in the config are errors. ``register`` receives it, already
    validated, as ``registry.settings``.
    """

    name: str
    version: str
    api_version: int
    register: Callable[[Registry], None]
    requires: tuple[str, ...] = ()
    settings: type[BaseModel] | None = None
    description: str = ""
