"""
Firebase Admin Authentication Service for CodeLens AI.
Verifies Firebase ID tokens for protected FastAPI endpoints.
Service account credentials and private keys remain strictly on the server.
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any
import firebase_admin
from firebase_admin import credentials, auth
from fastapi import HTTPException, Security, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from config import PROJECT_ROOT

# ============================================================
# CONFIGURATION
# ============================================================

FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", "vbus-b49d6")
FIREBASE_SERVICE_ACCOUNT_KEY = os.getenv("FIREBASE_SERVICE_ACCOUNT_KEY")

# HTTP Bearer security scheme for token extraction
bearer_scheme = HTTPBearer(auto_error=False)

# Track initialization status
_firebase_initialized = False
_firebase_app = None


def get_service_account_path() -> Optional[Path]:
    """Find service account file if configured."""
    if FIREBASE_SERVICE_ACCOUNT_KEY:
        candidate_path = Path(FIREBASE_SERVICE_ACCOUNT_KEY)
        if not candidate_path.is_absolute():
            candidate_path = PROJECT_ROOT / candidate_path
        if candidate_path.exists() and candidate_path.is_file():
            return candidate_path

    default_candidate = PROJECT_ROOT / "backend" / "serviceAccountKey.json"
    if default_candidate.exists() and default_candidate.is_file():
        return default_candidate

    return None


def initialize_firebase_admin() -> Optional[firebase_admin.App]:
    """
    Safely and lazily initialize Firebase Admin SDK.
    Uses service account key file if available.
    Never fails or crashes the backend if credentials are not yet supplied.
    """
    global _firebase_initialized, _firebase_app

    if _firebase_initialized and _firebase_app:
        return _firebase_app

    # Check if an existing app is already registered in firebase_admin
    try:
        _firebase_app = firebase_admin.get_app()
        _firebase_initialized = True
        return _firebase_app
    except ValueError:
        pass

    try:
        key_path = get_service_account_path()

        if key_path:
            print(f"Initializing Firebase Admin with service account key: {key_path}")
            cred = credentials.Certificate(str(key_path))
            _firebase_app = firebase_admin.initialize_app(
                cred,
                options={"projectId": FIREBASE_PROJECT_ID}
            )
        else:
            # Without a service account file, initialize with explicit projectId
            # Set environment to prevent metadata server timeout
            os.environ.setdefault("GCE_METADATA_TIMEOUT", "1")
            _firebase_app = firebase_admin.initialize_app(
                options={"projectId": FIREBASE_PROJECT_ID}
            )

        _firebase_initialized = True
        return _firebase_app

    except Exception as exc:
        print(f"Firebase Admin initialization note: {exc}")
        return None


# ============================================================
# TOKEN VERIFICATION DEPENDENCIES
# ============================================================

async def verify_firebase_token(
    auth_credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme)
) -> Optional[Dict[str, Any]]:
    """
    Extracts and verifies the Firebase ID token from the Authorization header.
    Returns the decoded token dictionary if valid, or None if no token provided.
    Raises HTTPException(401) if token is invalid or expired.
    """
    if not auth_credentials or not auth_credentials.credentials:
        return None

    token = auth_credentials.credentials

    # Ensure Firebase Admin is initialized
    initialize_firebase_admin()

    try:
        # verify_id_token validates the signature, expiration, and audience
        decoded_token = auth.verify_id_token(token)
        return decoded_token

    except auth.ExpiredIdTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except auth.InvalidIdTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication token: {str(exc)}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token verification failed: {str(exc)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    user: Optional[Dict[str, Any]] = Depends(verify_firebase_token)
) -> Dict[str, Any]:
    """
    FastAPI dependency for strictly protected endpoints.
    Requires a valid Firebase ID token; raises 401 Unauthorized if not authenticated.
    """
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please sign in to access this resource.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
