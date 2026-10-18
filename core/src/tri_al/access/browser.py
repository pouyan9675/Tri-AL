"""Browser protections (docs/design.md §5.8), on even without login.

A page on another website, open in the same browser, can send requests to the local
server. Three checks stop it from changing anything or reading through a rebound name:

- **Host:** every request's ``Host`` must be one of the server's names, so a DNS-rebinding
  page (``evil.example`` resolving to 127.0.0.1) gets 400s.
- **Custom header:** requests that change something (POST, PUT, PATCH, DELETE) must send
  ``X-Tri-AL``. Other origins can't add it without a CORS preflight, which the server
  never approves.
- **Origin:** when such a request has an ``Origin`` (browsers send one), it must be one of
  the server's names too; ``Sec-Fetch-Site: cross-site`` is refused outright.
"""

import json
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

CLIENT_HEADER = "X-Tri-AL"
"""The header changing requests must send, with any value (the front end sends ``1``)."""

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def hostname(netloc: str) -> str:
    """``netloc`` without its port, lowercased: ``[::1]:8000`` → ``[::1]``."""
    netloc = netloc.strip().lower()
    if netloc.startswith("["):
        return netloc[: netloc.find("]") + 1] if "]" in netloc else netloc
    return netloc.split(":", 1)[0]


class BrowserProtection:
    """ASGI middleware with the three checks; ``hosts`` None turns the Host checks off."""

    def __init__(self, app: ASGIApp, *, hosts: frozenset[str] | None) -> None:
        self.app = app
        self.hosts = hosts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        problem = self._problem(scope["method"], headers)
        if problem is None:
            await self.app(scope, receive, send)
            return
        code, detail = problem
        body = json.dumps({"detail": detail}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    def _problem(self, method: str, headers: Headers) -> tuple[int, str] | None:
        if self.hosts is not None and hostname(headers.get("host", "")) not in self.hosts:
            return 400, (
                "unexpected Host header; to reach the server under another name, add it to "
                "server.allowed_hosts in tri-al.toml"
            )
        if method not in UNSAFE_METHODS:
            return None
        if not headers.get(CLIENT_HEADER):
            return 403, f"requests that change something must send the {CLIENT_HEADER} header"
        if headers.get("sec-fetch-site") == "cross-site":
            return 403, "cross-site requests can't change anything"
        origin = headers.get("origin")
        if origin is not None:
            name = hostname(urlsplit(origin).netloc) if origin != "null" else ""
            if not name or (self.hosts is not None and name not in self.hosts):
                return 403, f"requests from {origin} can't change anything"
        return None
