import os
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["ANONYMIZED_TELEMETRY"] = "False"

import sys
from pathlib import Path
import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from services.repository_file_search import (
    list_files,
    find_text,
    retrieve_file_search_chunks,
)
from fastapi.testclient import TestClient
from main import app
import config


def test_css_listing_excludes_env_and_vendor(tmp_path: Path):
    """
    CSS listing returns every matching CSS path while strictly
    excluding vendor directories (.venv, node_modules) and sensitive .env files.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.css").write_text("body{}")
    (tmp_path / "theme.css").write_text(":root{}")
    (tmp_path / ".env").write_text("SECRET=value")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "vendor.css").write_text("")

    paths = {x["path"] for x in list_files(tmp_path, extension="css")}
    assert paths == {"src/app.css", "theme.css"}


def test_path_search(tmp_path: Path):
    """
    Path search by filename keyword returns matching items.
    """
    (tmp_path / "Dashboard.tsx").write_text("export default 1")
    results = list_files(tmp_path, query="dashboard")
    assert len(results) == 1
    assert results[0]["path"] == "Dashboard.tsx"


def test_missing_repository(tmp_path: Path):
    """
    Attempting to list files in a non-existent repository raises FileNotFoundError.
    """
    with pytest.raises(FileNotFoundError):
        list_files(tmp_path / "missing")


def test_find_text_code_location(tmp_path: Path):
    """
    find_text returns real path, line number, and excerpt evidence.
    """
    file_path = tmp_path / "Dashboard.tsx"
    file_path.write_text(
        "import React from 'react';\n"
        "export const Dashboard = () => {\n"
        "  return <h1 className='title'>Dashboard Overview</h1>;\n"
        "};\n"
    )

    matches = find_text(tmp_path, query="title")
    assert len(matches) >= 1
    m = matches[0]
    assert m["path"] == "Dashboard.tsx"
    assert m["line"] == 3
    assert "Dashboard Overview" in m["excerpt"]


def test_retrieve_file_search_chunks_for_css(tmp_path: Path):
    """
    retrieve_file_search_chunks identifies CSS queries and builds inventory chunks.
    """
    (tmp_path / "styles.css").write_text("body { color: blue; }")
    (tmp_path / "index.html").write_text("<h1>Test</h1>")

    chunks = retrieve_file_search_chunks(tmp_path, "what are the css files")
    assert len(chunks) >= 1
    c = chunks[0]
    assert c["metadata"]["chunk_type"] == "file_inventory"
    assert "styles.css" in c["content"]


def test_api_files_endpoint():
    """
    GET /api/repositories/{id}/files returns repository-relative files.
    """
    repo_id = "test_files_api_repo"
    repo_dir = config.REPOSITORIES_DIR / repo_id
    repo_dir.mkdir(parents=True, exist_ok=True)
    try:
        (repo_dir / "style.css").write_text("h1 { color: red; }")
        (repo_dir / "app.py").write_text("print('ok')")

        client = TestClient(app)
        resp = client.get(f"/api/repositories/{repo_id}/files?extension=css")
        assert resp.status_code == 200
        data = resp.json()
        assert data["repository_id"] == repo_id
        assert data["count"] == 1
        assert data["files"][0]["path"] == "style.css"
    finally:
        import shutil
        if repo_dir.exists():
            shutil.rmtree(repo_dir, ignore_errors=True)
