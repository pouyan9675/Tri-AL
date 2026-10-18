"""JSON responses with orjson, and ETags from the data version (docs/design.md §5.9)."""

import base64
import binascii
from typing import Any

import orjson
from fastapi import HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from tri_al.storage import Cursor, Sort

DATA_CACHE = "no-cache"
"""Data responses: a browser may keep them but must check the ETag each time (a 304)."""

NO_STORE = "no-store"
"""Jobs, plugins and events change without the data version changing."""


class JSONBytes(JSONResponse):
    """A JSON response from orjson, or from bytes that are JSON already.

    A ``JSONResponse`` subclass, so FastAPI puts each route's ``response_model`` in the
    OpenAPI schema (for any other response class it writes ``string``).
    """

    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        if isinstance(content, bytes):
            return content
        return orjson.dumps(content, option=orjson.OPT_NON_STR_KEYS)


def etag_for(data_version: int, build: str) -> str:
    """Weak, since gzip changes the bytes: ``W/"<data_version>-<build>"``."""
    return f'W/"{data_version}-{build}"'


def not_modified(request: Request, etag: str) -> Response | None:
    """A 304 if the request's ``If-None-Match`` has ``etag``; else None."""
    header = request.headers.get("if-none-match")
    if header is None:
        return None
    tags = {tag.strip() for tag in header.split(",")}
    if "*" in tags or etag in tags or etag.removeprefix("W/") in tags:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": DATA_CACHE})
    return None


def data_json(content: Any, etag: str, *, status_code: int = 200) -> JSONBytes:
    return JSONBytes(
        content, status_code=status_code, headers={"ETag": etag, "Cache-Control": DATA_CACHE}
    )


def live_json(content: Any, *, status_code: int = 200) -> JSONBytes:
    return JSONBytes(content, status_code=status_code, headers={"Cache-Control": NO_STORE})


def encode_cursor(sort: Sort, cursor: Cursor) -> str:
    """An opaque, URL-safe cursor that remembers its sort."""
    raw = orjson.dumps([str(sort), cursor[0], cursor[1]])
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def decode_cursor(sort: Sort, text: str) -> Cursor:
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
        sort_text, value, trial_id = orjson.loads(raw)
    except (binascii.Error, orjson.JSONDecodeError, ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid cursor") from None
    if sort_text != str(sort) or not isinstance(trial_id, int):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "the cursor belongs to another sort; start over"
        )
    return (value, trial_id)
