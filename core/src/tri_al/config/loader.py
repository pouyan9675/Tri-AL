"""Read ``tri-al.toml``, apply ``TRI_AL_*`` environment overrides, and edit the file."""

import os
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import tomlkit
import tomlkit.exceptions
from pydantic import ValidationError

from tri_al.config.models import Config

ENV_PREFIX = "TRI_AL_"
CONFIG_ENV = "TRI_AL_CONFIG"
"""Path of the config file. Reserved: it is not an override."""

DEFAULT_PATH = Path("tri-al.toml")


class ConfigError(Exception):
    """The config file or a ``TRI_AL_*`` variable is invalid."""


def config_path(env: Mapping[str, str] | None = None) -> Path:
    """``$TRI_AL_CONFIG`` if set, else ``tri-al.toml`` in the working directory."""
    env = os.environ if env is None else env
    return Path(env[CONFIG_ENV]) if env.get(CONFIG_ENV) else DEFAULT_PATH


def load_config(path: Path | None = None, env: Mapping[str, str] | None = None) -> Config:
    """Load the config. A missing file means all defaults.

    Environment variables override the file. Double underscores separate nested keys, and
    names are lowercased: ``TRI_AL_SERVER__PORT=9000`` sets ``server.port``, and
    ``TRI_AL_PLUGINS__SAMPLE__GREETING=Hi`` sets ``greeting`` in ``[plugins.sample]``.
    Values arrive as strings; Pydantic converts them to each field's type.
    """
    env = os.environ if env is None else env
    path = config_path(env) if path is None else path
    data = _read(path)
    sources = _apply_env(data, env)
    try:
        return Config.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(_describe(exc, path, sources)) from None


def set_plugin_enabled(path: Path, name: str, enabled: bool) -> None:
    """Set ``enabled`` in ``[plugins.<name>]``, keeping the file's comments and layout."""
    edit_plugin_section(path, name, {"enabled": enabled})


def edit_plugin_section(path: Path, name: str, changes: Mapping[str, Any]) -> None:
    """Set keys in ``[plugins.<name>]`` (None removes one), keeping comments and layout."""
    doc = _parse(path)
    plugins = doc.setdefault("plugins", tomlkit.table(is_super_table=True))
    if not isinstance(plugins, dict):
        raise ConfigError(f"{path}: 'plugins' must be a table")
    section = plugins.setdefault(name, tomlkit.table())
    if not isinstance(section, dict):
        raise ConfigError(f"{path}: 'plugins.{name}' must be a table")
    _set(section, changes)
    _write(path, doc)


def edit_ai_section(
    path: Path,
    changes: Mapping[str, Any],
    labels: Sequence[Mapping[str, Any]] | None = None,
) -> None:
    """Set keys in ``[ai]`` (None removes one) and, if given, replace the annotation labels.

    Labels are written as ``[[ai.annotation.labels]]`` tables, one per label, so the file
    stays easy to edit by hand. Comments and layout elsewhere are kept.
    """
    doc = _parse(path)
    section = doc.setdefault("ai", tomlkit.table())
    if not isinstance(section, dict):
        raise ConfigError(f"{path}: 'ai' must be a table")
    _set(section, changes)
    if labels is not None:
        annotation = section.setdefault("annotation", tomlkit.table())
        if not isinstance(annotation, dict):
            raise ConfigError(f"{path}: 'ai.annotation' must be a table")
        tables = tomlkit.aot()
        for label in labels:
            table = tomlkit.table()
            _set(table, {key: value for key, value in label.items() if value not in ("", [])})
            tables.append(table)
        annotation["labels"] = tables
    _write(path, doc)


def _parse(path: Path) -> tomlkit.TOMLDocument:
    try:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        return tomlkit.parse(text)
    except (OSError, tomlkit.exceptions.ParseError) as exc:
        raise ConfigError(f"{path}: {exc}") from None


def _set(section: dict[str, Any], changes: Mapping[str, Any]) -> None:
    for key, value in changes.items():
        if value is None:
            section.pop(key, None)
        else:
            section[key] = value


def _write(path: Path, doc: tomlkit.TOMLDocument) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(tomlkit.dumps(doc), encoding="utf-8")
    tmp.replace(path)


def _read(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"{path}: {exc}") from None


def _apply_env(data: dict[str, Any], env: Mapping[str, str]) -> dict[tuple[str, ...], str]:
    """Merge ``TRI_AL_*`` variables into ``data``; return which variable set each key."""
    sources: dict[tuple[str, ...], str] = {}
    for var, value in sorted(env.items()):
        if not var.startswith(ENV_PREFIX) or var == CONFIG_ENV:
            continue
        keys = tuple(var.removeprefix(ENV_PREFIX).lower().split("__"))
        if not all(keys):
            raise ConfigError(
                f"{var}: empty key; separate nested keys with '__', as in TRI_AL_SERVER__PORT"
            )
        target = data
        for depth, key in enumerate(keys[:-1], start=1):
            target = target.setdefault(key, {})
            if not isinstance(target, dict):
                raise ConfigError(f"{var}: '{'.'.join(keys[:depth])}' is not a table")
        target[keys[-1]] = value
        sources[keys] = var
    return sources


def _describe(exc: ValidationError, path: Path, sources: dict[tuple[str, ...], str]) -> str:
    lines = [f"invalid config ({path}):"]
    for error in exc.errors():
        loc = tuple(str(part) for part in error["loc"])
        origin = f" (from {sources[loc]})" if loc in sources else ""
        lines.append(f"  {'.'.join(loc)}: {error['msg']}{origin}")
    return "\n".join(lines)
