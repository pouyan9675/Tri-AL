"""Print the API's OpenAPI schema, which ``web/`` generates its typed client from.

    uv run python -m tri_al.api.openapi > web/openapi.json
    uv run python -m tri_al.api.openapi --plugin results > web/openapi.results.json

It describes the core's routes only: the app is built with no plugins and an empty data
directory, so the schema doesn't change with what's installed. A plugin's routes, under
``/api/x/<plugin>/``, are its own schema (``--plugin``), for a front end that uses them.
"""

import argparse
import sys
import tempfile
from pathlib import Path
from typing import Any

import orjson

from tri_al.config import Config
from tri_al.plugins import LoadedPlugins
from tri_al.plugins.loader import discover, load_plugins


def schema() -> dict[str, Any]:
    from tri_al.api.app import create_app

    with tempfile.TemporaryDirectory() as tmp:
        config = Config.model_validate({"data": {"dir": tmp}})
        app = create_app(config, LoadedPlugins(), config_file=Path(tmp) / "tri-al.toml")
        try:
            return app.openapi()
        finally:
            app.state.tri_al.close()


def plugin_schema(name: str) -> dict[str, Any]:
    """The routes one installed plugin adds, mounted where the API mounts them."""
    from fastapi import FastAPI

    from tri_al.api.app import operation_id

    entry_points = [ep for ep in discover() if ep.name == name]
    if not entry_points:
        raise SystemExit(f"no plugin named {name!r} is installed")
    with tempfile.TemporaryDirectory() as tmp:
        loaded = load_plugins(Config.model_validate({"data": {"dir": tmp}}), entry_points)
    router = loaded.contributions.routes.get(name)
    if router is None:
        raise SystemExit(f"plugin {name!r} adds no routes")
    app = FastAPI(
        title=f"Tri-AL plugin: {name}",
        version=loaded.plugins[0].version,
        generate_unique_id_function=operation_id,  # as the API names operations
    )
    app.include_router(router, prefix=f"/api/x/{name}", tags=[f"plugin: {name}"])
    return app.openapi()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--plugin", help="print this plugin's routes instead of the core's")
    args = parser.parse_args(argv)
    exported = schema() if args.plugin is None else plugin_schema(args.plugin)
    sys.stdout.buffer.write(orjson.dumps(exported, option=orjson.OPT_INDENT_2) + b"\n")


if __name__ == "__main__":
    main()
