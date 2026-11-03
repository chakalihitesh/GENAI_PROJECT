"""
Authentication router for CodeLens AI.
Provides client Firebase configuration and token verification endpoints.
"""

import os
from fastapi import APIRouter, Depends
from services.firebase_auth import (
    get_current_user,
    verify_firebase_token,
    FIREBASE_PROJECT_ID,
    _firebase_initialized,
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.get("/config")
def get_firebase_client_config():
    """
    Returns public Firebase client configuration for frontend initialization.
    Values can be populated from environment variables or defaults.
    Private server credentials are NEVER returned.
    """
    api_key = os.getenv("FIREBASE_API_KEY", "")
    app_id = os.getenv("FIREBASE_APP_ID", "")
    project_id = os.getenv("FIREBASE_PROJECT_ID", FIREBASE_PROJECT_ID)

    return {
        "projectId": project_id,
        "authDomain": f"{project_id}.firebaseapp.com",
        "storageBucket": f"{project_id}.firebasestorage.app",
        "messagingSenderId": os.getenv("FIREBASE_MESSAGING_SENDER_ID", "962026177714"),
        "apiKey": api_key,
        "appId": app_id,
    }


@router.get("/status")
def get_auth_status():
    """
    Returns the backend Firebase Admin SDK status without leaking secrets.
    """
    service_account_configured = bool(
        os.getenv("FIREBASE_SERVICE_ACCOUNT_KEY") or
        os.path.exists("backend/serviceAccountKey.json")
    )

    return {
        "service": "Firebase Authentication",
        "projectId": FIREBASE_PROJECT_ID,
        "adminSdkInitialized": _firebase_initialized,
        "serviceAccountConfigured": service_account_configured,
        "supportedProviders": ["password", "google.com"],
    }


@router.get("/me")
async def get_authenticated_user_profile(user: dict = Depends(get_current_user)):
    """
    Protected endpoint: Verifies Firebase ID token and returns authenticated user info.
    """
    return {
        "status": "authenticated",
        "uid": user.get("uid"),
        "email": user.get("email"),
        "name": user.get("name") or user.get("display_name"),
        "picture": user.get("picture"),
        "email_verified": user.get("email_verified", False),
        "auth_time": user.get("auth_time"),
    }
