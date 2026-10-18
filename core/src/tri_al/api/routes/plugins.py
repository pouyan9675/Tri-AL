"""Plugins (docs/design.md §5.6 and §5.9): list them, and edit their part of ``tri-al.toml``.

Plugins load at startup, so a change applies when the server next starts.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ValidationError

from tri_al.access import EDIT_PLUGINS, READ, require
from tri_al.api.http import live_json
from tri_al.api.models import ErrorOut, PluginChangedOut, PluginPatch, PluginsOut
from tri_al.api.routes.data import State
from tri_al.api.state import ApiState
from tri_al.config import Config, ConfigError, edit_plugin_section, load_config
from tri_al.plugins import Plugin, PluginStatus, discover, inspect_plugins

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


def _config(state: ApiState) -> Config:
    try:
        return load_config(state.config_path)
    except ConfigError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from None


def _plugin_json(state: ApiState, config: Config, plugin: PluginStatus) -> dict[str, Any]:
    loaded = {p.name for p in state.plugins.plugins}
    return {
        "name": plugin.name,
        "enabled": plugin.enabled,
        "installed": plugin.installed,
        "loaded": plugin.name in loaded,
        "version": plugin.version,
        "description": plugin.description,
        "problems": plugin.problems,
        "settings": config.plugin_settings(plugin.name),
    }


@router.get(
    "", response_model=PluginsOut, dependencies=[Depends(require(READ))], name="listPlugins"
)
def list_plugins(state: State) -> Response:
    """Installed plugins and plugins named in ``tri-al.toml``, with their settings."""
    config = _config(state)
    plugins = inspect_plugins(config)
    return live_json({"plugins": [_plugin_json(state, config, p) for p in plugins]})


@router.patch(
    "/{name}",
    response_model=PluginChangedOut,
    responses={404: {"model": ErrorOut}, 422: {"model": ErrorOut}},
    dependencies=[Depends(require(EDIT_PLUGINS))],
    name="updatePlugin",
)
def update_plugin(state: State, name: str, patch: PluginPatch) -> Response:
    """Enable or disable a plugin, or change its settings, in ``tri-al.toml``.

    Settings are checked against the plugin's settings model before anything is written.
    """
    config = _config(state)
    found = {p.name: p for p in inspect_plugins(config)}
    if name not in found or not found[name].installed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no plugin {name!r} is installed")
    changes: dict[str, Any] = {}
    if patch.settings:
        if "enabled" in patch.settings:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "set enabled outside settings"
            )
        merged = config.plugin_settings(name) | patch.settings
        merged = {key: value for key, value in merged.items() if value is not None}
        _validate(name, merged)
        changes |= patch.settings
    if patch.enabled is not None:
        changes["enabled"] = patch.enabled
    if changes:
        try:
            edit_plugin_section(state.config_path, name, changes)
        except ConfigError as exc:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from None
    config = _config(state)
    plugin = {p.name: p for p in inspect_plugins(config)}[name]
    return live_json(
        {"plugin": _plugin_json(state, config, plugin), "restart_required": bool(changes)}
    )


def _validate(name: str, settings: dict[str, Any]) -> None:
    plugin = next((ep.load() for ep in discover() if ep.name == name), None)
    model: type[BaseModel] | None = plugin.settings if isinstance(plugin, Plugin) else None
    if model is None:
        if settings:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{name} takes no settings")
        return
    try:
        model.model_validate(settings)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(map(str, error['loc'])) or '(settings)'}: {error['msg']}"
            for error in exc.errors()
        )
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, problems) from None
