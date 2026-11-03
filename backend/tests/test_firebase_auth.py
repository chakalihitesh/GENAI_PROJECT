import os
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from routers.auth import get_firebase_client_config, get_auth_status, get_authenticated_user_profile
from services.firebase_auth import FIREBASE_PROJECT_ID


def test_firebase_config():
    """Verify public client config returns correct project ID."""
    cfg = get_firebase_client_config()
    assert cfg["projectId"] == "vbus-b49d6"
    assert cfg["authDomain"] == "vbus-b49d6.firebaseapp.com"
    assert cfg["storageBucket"] == "vbus-b49d6.firebasestorage.app"
    assert cfg["messagingSenderId"] == "962026177714"


def test_firebase_status():
    """Verify backend auth status structure."""
    st = get_auth_status()
    assert st["service"] == "Firebase Authentication"
    assert st["projectId"] == "vbus-b49d6"
    assert "password" in st["supportedProviders"]
    assert "google.com" in st["supportedProviders"]


def test_service_account_not_in_frontend():
    """
    Verifies that no private service account keys or credentials exist in frontend files.
    """
    frontend_dir = backend_dir.parent / "frontend"
    for file_path in frontend_dir.glob("*.*"):
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        assert "private_key" not in content.lower()
        assert "service_account" not in content.lower()
