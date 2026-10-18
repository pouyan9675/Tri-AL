"""The built front end, served on the API's port (docs/design.md §9).

``npm run build`` in ``web/`` writes ``web/dist``: ``index.html`` and content-hashed files
under ``assets/``. Hashed files are cached for good; ``index.html`` is checked each time.
Any other path without a file extension is one of the single-page app's routes
(``/trials``, ``/trials/NCT04437511``), so it gets ``index.html`` too. A missing file (an
old hashed asset) is a 404, never the page, and ``/api/...`` is never the app's.

In development the Vite dev server serves the app instead and proxies ``/api`` here.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse, HTMLResponse, Response

CHECKOUT_WEB_DIR = Path(__file__).resolve().parents[4] / "web" / "dist"
"""``web/dist`` beside ``core/`` in a checkout of the repository."""

IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"

NOT_BUILT = """<!doctype html>
<meta charset="utf-8"><title>Tri-AL</title>
<body style="font: 15px/1.5 system-ui, sans-serif; max-width: 40rem; margin: 4rem auto">
<h1>Tri-AL</h1>
<p>The API is running (<a href="/api/docs">API docs</a>), but the front end isn't built.
Build it with <code>npm ci &amp;&amp; npm run build</code> in <code>web/</code>, or run the
dev server there with <code>npm run dev</code>.</p>
</body>
"""


def add_web(app: FastAPI, root: Path | None) -> None:
    """Serve the front end in ``root`` (default: the checkout's ``web/dist``).

    Call it after every other route is added: its catch-all route must come last.
    """
    root = (CHECKOUT_WEB_DIR if root is None else root).resolve()
    index = root / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    def web(path: str) -> Response:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
        if path:
            file = (root / path).resolve()
            if file.is_relative_to(root) and file.is_file():
                cache = IMMUTABLE if path.startswith("assets/") else REVALIDATE
                return FileResponse(file, headers={"Cache-Control": cache})
            if "." in path.rsplit("/", 1)[-1]:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
        if not index.is_file():
            return HTMLResponse(NOT_BUILT, headers={"Cache-Control": REVALIDATE})
        return FileResponse(index, headers={"Cache-Control": REVALIDATE})
