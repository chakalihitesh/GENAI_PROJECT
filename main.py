"""
CodeLens AI — Root Application Entrypoint
Allows Uvicorn, Gunicorn, and Render to start the application seamlessly
with standard commands like:
    uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1
or:
    python main.py
"""

import os
import sys
from pathlib import Path

# Add backend directory to sys.path so all application modules and configs resolve cleanly
ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Export the FastAPI app instance for ASGI servers (Uvicorn / Render)
from backend.main import app  # noqa: F401

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")

    print("")
    print("=" * 60)
    print(f"Starting CodeLens AI on {host}:{port} (Single Worker)...")
    print(f"Health Check: http://{host}:{port}/health")
    print("=" * 60)
    print("")

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        workers=1,
        reload=False,
    )
