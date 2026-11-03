from pathlib import Path
from dotenv import load_dotenv
import os

# Disable ChromaDB telemetry to prevent network blocking on startup
os.environ["ANONYMIZED_TELEMETRY"] = "False"
# Enable offline mode for Hugging Face Hub if offline
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

# backend/
BASE_DIR = Path(__file__).resolve().parent

# Project root: CodeLens-AI/
PROJECT_ROOT = BASE_DIR.parent

# Load .env from project root or backend folder
ENV_PATH = PROJECT_ROOT / ".env"
BACKEND_ENV_PATH = BASE_DIR / ".env"

load_dotenv(ENV_PATH)
if BACKEND_ENV_PATH.exists():
    load_dotenv(BACKEND_ENV_PATH)

# Data directories
DATA_DIR = PROJECT_ROOT / "data"
REPOSITORIES_DIR = DATA_DIR / "repositories"
CHROMA_DIR = DATA_DIR / "chroma_db"
FRONTEND_DIR = PROJECT_ROOT / "frontend"

# Create required directories
REPOSITORIES_DIR.mkdir(parents=True, exist_ok=True)
CHROMA_DIR.mkdir(parents=True, exist_ok=True)

# AI API Keys
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Archive extraction limits (configurable via environment variables)
MAX_ZIP_FILES = int(os.getenv("MAX_ZIP_FILES", "50000"))
MAX_UNCOMPRESSED_BYTES = int(os.getenv("MAX_UNCOMPRESSED_BYTES", str(500 * 1024 * 1024)))  # 500 MB default
MAX_COMPRESSED_BYTES = int(os.getenv("MAX_COMPRESSED_BYTES", str(100 * 1024 * 1024)))      # 100 MB default
MAX_SINGLE_FILE_SIZE = int(os.getenv("MAX_SINGLE_FILE_SIZE", str(100 * 1024 * 1024)))      # 100 MB default
MAX_COMPRESSION_RATIO = float(os.getenv("MAX_COMPRESSION_RATIO", "100.0"))                  # 100:1 ratio default
