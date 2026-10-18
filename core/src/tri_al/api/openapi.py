"""Print the API's OpenAPI schema, which ``web/`` generates its typed client from.

    uv run python -m tri_al.api.openapi > web/openapi.json

It describes the core's routes only: the app is built with no plugins and an empty data
directory, so the schema doesn't change with what's installed (plugin routes, under
``/api/x/<plugin>/``, are each plugin's own).
"""

import sys
import tempfile
from pathlib import Path
from typing import Any

import orjson

from tri_al.config import Config
from tri_al.plugins import LoadedPlugins


def schema() -> dict[str, Any]:
    from tri_al.api.app import create_app

    with tempfile.TemporaryDirectory() as tmp:
        config = Config.model_validate({"data": {"dir": tmp}})
        app = create_app(config, LoadedPlugins(), config_file=Path(tmp) / "tri-al.toml")
        try:
            return app.openapi()
        finally:
            app.state.tri_al.close()


def main() -> None:
    sys.stdout.buffer.write(orjson.dumps(schema(), option=orjson.OPT_INDENT_2) + b"\n")


if __name__ == "__main__":
    main()
