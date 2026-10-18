"""The built front end on the API's port (tri_al.api.web)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tri_al.api import create_app
from tri_al.config import Config
from tri_al.plugins import LoadedPlugins

BASE_URL = "http://127.0.0.1:8000"
INDEX = b"<!doctype html><title>Tri-AL</title><div id=root></div>"


def client_for(tmp_path: Path, web_dir: Path) -> TestClient:
    config = Config.model_validate(
        {"data": {"dir": str(tmp_path / "data")}, "server": {"web_dir": str(web_dir)}}
    )
    app = create_app(config, LoadedPlugins(), config_file=tmp_path / "tri-al.toml")
    return TestClient(app, base_url=BASE_URL)


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_bytes(INDEX)
    (root / "assets" / "index-abc123.js").write_text("console.log('tri-al')")
    (root / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("not for the web")
    return root


@pytest.fixture
def client(tmp_path: Path, dist: Path) -> Iterator[TestClient]:
    with client_for(tmp_path, dist) as client:
        yield client


@pytest.mark.parametrize("path", ["/", "/trials", "/trials/NCT04437511", "/settings"])
def test_pages_get_the_app(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert response.content == INDEX
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"


def test_hashed_assets_are_cached_for_good(client: TestClient) -> None:
    response = client.get("/assets/index-abc123.js")
    assert response.status_code == 200
    assert response.text == "console.log('tri-al')"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert client.get("/favicon.svg").headers["cache-control"] == "no-cache"


def test_missing_files_are_404s_not_the_page(client: TestClient) -> None:
    assert client.get("/assets/index-old999.js").status_code == 404
    assert client.get("/favicon.ico").status_code == 404


def test_api_paths_are_never_the_app(client: TestClient) -> None:
    response = client.get("/api/nothing-here")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert client.get("/api").status_code == 404
    assert client.get("/api/meta").json()["installed"] is False


@pytest.mark.parametrize(
    "path", ["/..%2fsecret.txt", "/assets/..%2f..%2fsecret.txt", "/%2e%2e/secret.txt"]
)
def test_files_outside_the_build_stay_private(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert b"not for the web" not in response.content


def test_the_host_check_covers_the_app(client: TestClient) -> None:
    assert client.get("/", headers={"Host": "rebound.example"}).status_code == 400


def test_without_a_build_the_page_says_how_to_make_one(tmp_path: Path) -> None:
    with client_for(tmp_path, tmp_path / "missing") as client:
        response = client.get("/trials")
    assert response.status_code == 200
    assert "npm run build" in response.text
