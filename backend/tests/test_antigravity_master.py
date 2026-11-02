import os
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["ANONYMIZED_TELEMETRY"] = "False"

import io
import sys
import zipfile
from pathlib import Path
import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from repository.manager import (
    safe_extract_zip,
    summarize_languages,
    inspect_env_files,
    parse_dependency_manifests,
)
import config


# ============================================================
# PHASE 1 TESTS: SAFE ZIP EXTRACTION & CONFIGURABLE LIMITS
# ============================================================

def test_zip_normal_project(tmp_path: Path):
    """
    ZIP with a normal project is accepted and extracted safely.
    """
    zip_path = tmp_path / "valid_project.zip"
    dest = tmp_path / "dest_normal"

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("app/main.py", "print('hello')\n")
        zf.writestr("app/utils.py", "def add(a, b): return a + b\n")
        zf.writestr("README.md", "# Sample\n")

    safe_extract_zip(zip_path, dest)
    assert (dest / "app" / "main.py").exists()
    assert (dest / "app" / "utils.py").exists()
    assert (dest / "README.md").exists()


def test_zip_file_count_limit(tmp_path: Path, monkeypatch):
    """
    ZIP above the configured file limit returns a clear rejection message.
    """
    monkeypatch.setattr(config, "MAX_ZIP_FILES", 3)
    import repository.manager as mgr
    monkeypatch.setattr(mgr, "MAX_ZIP_FILES", 3)

    zip_path = tmp_path / "too_many_files.zip"
    dest = tmp_path / "dest_files"

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("f1.py", "1")
        zf.writestr("f2.py", "2")
        zf.writestr("f3.py", "3")
        zf.writestr("f4.py", "4")

    with pytest.raises(ValueError) as excinfo:
        safe_extract_zip(zip_path, dest)

    assert "too many files" in str(excinfo.value)
    assert "4 > 3" in str(excinfo.value)


def test_zip_expanded_size_limit(tmp_path: Path, monkeypatch):
    """
    ZIP above the configured extracted size limit returns a clear rejection message.
    """
    monkeypatch.setattr(config, "MAX_UNCOMPRESSED_BYTES", 500)
    import repository.manager as mgr
    monkeypatch.setattr(mgr, "MAX_UNCOMPRESSED_BYTES", 500)

    zip_path = tmp_path / "oversized.zip"
    dest = tmp_path / "dest_size"

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("large.txt", "x" * 600)

    with pytest.raises(ValueError) as excinfo:
        safe_extract_zip(zip_path, dest)

    assert "exceeds maximum allowed size" in str(excinfo.value)


def test_zip_path_traversal_rejection(tmp_path: Path):
    """
    ZIP with path traversal entry is rejected without writing outside the repository.
    """
    zip_path = tmp_path / "traversal.zip"
    dest = tmp_path / "dest_safe"
    dest.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("../evil_file.txt", "MALICIOUS")

    with pytest.raises(ValueError) as excinfo:
        safe_extract_zip(zip_path, dest)

    assert "Unsafe ZIP path detected" in str(excinfo.value)
    assert not (tmp_path / "evil_file.txt").exists()


# ============================================================
# PHASE 2 TESTS: LANGUAGE SUMMARY, MANIFESTS, SAFE ENV
# ============================================================

def test_language_summary(tmp_path: Path):
    """
    Language counts match files in the repository, excluding generated/vendor folders.
    """
    repo = tmp_path / "repo_lang"
    repo.mkdir()

    # Valid source files
    (repo / "main.py").write_text("print(1)")
    (repo / "test.py").write_text("print(2)")
    (repo / "app.tsx").write_text("export const A = 1;")
    (repo / "index.html").write_text("<h1>Hi</h1>")

    # Files inside ignored directories (must NOT be counted)
    node_modules = repo / "node_modules" / "pkg"
    node_modules.mkdir(parents=True)
    (node_modules / "library.js").write_text("var x = 1;")

    venv_dir = repo / ".venv" / "lib"
    venv_dir.mkdir(parents=True)
    (venv_dir / "dep.py").write_text("pass")

    summary = summarize_languages(repo)
    assert summary["source_file_count"] == 4

    lang_map = {item["name"]: item["file_count"] for item in summary["languages"]}
    assert lang_map.get("Python") == 2
    assert lang_map.get("TypeScript") == 1
    assert lang_map.get("HTML") == 1
    assert "JavaScript" not in lang_map  # node_modules was excluded


def test_dependency_manifests(tmp_path: Path):
    """
    Dependency manifests are detected and parsed without inventing relationships.
    """
    repo = tmp_path / "repo_deps"
    repo.mkdir()

    # 1. requirements.txt
    req_file = repo / "requirements.txt"
    req_file.write_text(
        "fastapi>=0.115.0\n"
        "groq==0.11.0\n"
        "python-dotenv\n"
        "# comment line\n"
    )

    # 2. package.json
    pkg_file = repo / "package.json"
    pkg_file.write_text(
        '{"dependencies": {"react": "^18.2.0"}, "devDependencies": {"vite": "^5.0.0"}}'
    )

    manifests = parse_dependency_manifests(repo)
    assert len(manifests) == 2

    req_manifest = next(m for m in manifests if m["file"] == "requirements.txt")
    req_names = {d["name"]: d["version"] for d in req_manifest["dependencies"]}
    assert "fastapi" in req_names
    assert req_names["fastapi"] == ">=0.115.0"
    assert "groq" in req_names

    pkg_manifest = next(m for m in manifests if m["file"] == "package.json")
    pkg_names = {d["name"]: d["version"] for d in pkg_manifest["dependencies"]}
    assert pkg_names.get("react") == "^18.2.0"
    assert pkg_names.get("vite") == "^5.0.0"


def test_safe_env_file_inventory(tmp_path: Path):
    """
    Environment inventory displays variable names only;
    no secret values appear in results or logs.
    """
    repo = tmp_path / "repo_env"
    repo.mkdir()

    env_file = repo / ".env.example"
    env_file.write_text(
        "GROQ_API_KEY=mock_dummy_secret_12345\n"
        "DATABASE_URL=postgres://admin:password@localhost:5432/db\n"
        "# Comment line\n"
        "PORT=8000\n"
    )

    inventory = inspect_env_files(repo)
    assert len(inventory) == 1
    item = inventory[0]
    assert item["file"] == ".env.example"
    assert item["values_redacted"] is True

    # Variable names are extracted
    assert set(item["variable_names"]) == {"DATABASE_URL", "GROQ_API_KEY", "PORT"}

    # CRITICAL: Verify secret values NEVER appear in the data
    raw_str = str(inventory)
    assert "mock_dummy_secret_12345" not in raw_str
    assert "password" not in raw_str


# ============================================================
# PHASE 3 TESTS: GITHUB URL VALIDATION & API CONTRACT
# ============================================================

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_github_invalid_urls():
    """
    Verify rejection of arbitrary URLs, non-HTTPS URLs, local paths, and malformed inputs.
    """
    invalid_cases = [
        "",
        "   ",
        "http://github.com/owner/repo",  # Non-HTTPS
        "https://gitlab.com/owner/repo",  # Non-GitHub
        "file:///etc/passwd",             # Local path
        "https://github.com/",            # Missing repo
        "https://github.com/onlyowner",   # Incomplete
    ]

    for bad_url in invalid_cases:
        resp = client.post("/api/repositories/github", json={"url": bad_url})
        assert resp.status_code == 400
        assert "detail" in resp.json()


def test_summary_endpoint():
    """
    Test GET /api/repositories/{id}/summary returns the exact shape specified.
    """
    repo_id = "test_summary_repo"
    repo_dir = config.REPOSITORIES_DIR / repo_id
    repo_dir.mkdir(parents=True, exist_ok=True)
    try:
        (repo_dir / "app.py").write_text("print('test')")
        (repo_dir / "requirements.txt").write_text("pytest>=7.0.0\n")
        (repo_dir / ".env.example").write_text("API_KEY=dummy\n")

        resp = client.get(f"/api/repositories/{repo_id}/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["repository_id"] == repo_id
        assert "language_summary" in data
        assert "dependency_manifests" in data
        assert "environment_files" in data
        assert data["language_summary"]["source_file_count"] >= 1
    finally:
        import shutil
        if repo_dir.exists():
            shutil.rmtree(repo_dir, ignore_errors=True)
