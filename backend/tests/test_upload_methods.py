import io
from pathlib import Path
from fastapi.testclient import TestClient
import sys

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from main import app

client = TestClient(app)


def test_upload_folder_success(tmp_path):
    """
    Test uploading a local project folder with relative paths.
    """
    files = [
        ("files", ("index.js", io.BytesIO(b"console.log('hello');"), "application/javascript")),
        ("files", ("utils.py", io.BytesIO(b"def helper(): pass"), "text/x-python")),
    ]
    data = {
        "paths": ["src/index.js", "src/utils.py"]
    }

    response = client.post("/api/repositories/upload-folder", files=files, data=data)
    assert response.status_code == 200, response.text
    data = response.json()
    assert "repository_id" in data
    assert data["repository"]["file_count"] >= 2


def test_github_import_validation():
    """
    Test GitHub import endpoint rejects invalid URLs with 400.
    """
    response = client.post("/api/repositories/github", json={"url": "https://notgithub.com/foo/bar"})
    assert response.status_code == 400
    assert "valid GitHub repository URL" in response.json()["detail"]


def test_github_import_empty_url():
    """
    Test GitHub import endpoint rejects empty URL with 400.
    """
    response = client.post("/api/repositories/github", json={"url": "   "})
    assert response.status_code == 400
