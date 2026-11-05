import sys
from pathlib import Path

# Add backend directory to sys.path so modules and configs can be imported
# seamlessly regardless of whether Uvicorn runs from repository root or backend/
_BACKEND_DIR = Path(__file__).resolve().parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import os
import gc
import asyncio
import re
import shutil
import subprocess
from pathlib import Path
import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import REPOSITORIES_DIR, FRONTEND_DIR, DATA_DIR
from repository.manager import (
    save_uploaded_repository,
    get_supported_files,
    create_repository_id,
    is_safe_zip_path,
    IGNORED_DIRECTORIES,
    get_repository_info,
    extract_repository,
    summarize_languages,
    inspect_env_files,
    parse_dependency_manifests,
)
from rag.embedding_service import EmbeddingService
from rag.vector_store import VectorStore
from rag.search_service import SearchService
from rag.llm_service import LLMService
from rag.rag_service import RAGService
from analysis.overview_analyzer import RepositoryOverviewAnalyzer
from analysis.tech_stack_detector import TechnologyStackDetector
from analysis.importance_analyzer import ImportantFileAnalyzer
from analysis.structure_analyzer import RepositoryStructureAnalyzer
from analysis.api_analyzer import APIAnalyzer
from analysis.architecture_analyzer import ArchitectureAnalyzer
from analysis.dependency_analyzer import DependencyAnalyzer
from analysis.impact_analyzer import ImpactAnalyzer
from analysis.onboarding_analyzer import OnboardingAnalyzer
from services.progress_service import progress_service
from repository.chunker import chunk_repository, chunk_file
from routers.file_search import router as file_search_router
from routers.auth import router as auth_router
# ============================================================
# APP CONFIGURATION
# ============================================================

app = FastAPI(
    title="CodeLens AI",
    description="Generative AI Codebase Q&A Assistant",
    version="1.0.0",
)


# ============================================================
app.include_router(file_search_router)
app.include_router(auth_router)

# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "https://genaiproject-frontend.vercel.app",
        "https://genai-project-frontend.vercel.app",
        "https://codelense-backend.onrender.com",
    ],
    allow_origin_regex=r"^https://([a-zA-Z0-9_-]+\.)*vercel\.app$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# SERVICE INITIALIZATION
# ============================================================

print("Initializing CodeLens AI services...")

embedding_service = EmbeddingService()

vector_store = VectorStore()

search_service = SearchService(
    embedding_service,
    vector_store,
)

llm_service = LLMService()

rag_service = RAGService(
    search_service,
    llm_service,
)

print("CodeLens AI services initialized successfully.")


# ============================================================
# REQUEST MODELS
# ============================================================

class AskRequest(BaseModel):
    question: str
    top_k: int = 5

class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
# ============================================================
# ROOT / HEALTH
# ============================================================

@app.get("/")
@app.get("/api")
def root():
    return {
        "message": "CodeLens AI backend is running.",
        "version": "1.0.0",
        "status": "healthy",
    }


@app.get("/health")
@app.get("/api/health")
def health():
    return {
        "status": "healthy",
        "service": "CodeLens AI",
    }



@app.get("/health/groq")
@app.get("/api/health/groq")
def health_groq():
    """
    Verification endpoint for the Groq integration.
    Sends a minimal ping and returns status without leaking API keys.
    """
    try:
        if not llm_service.client:
            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                return {
                    "status": "error",
                    "service": "groq",
                    "message": "GROQ_API_KEY is not configured in environment or .env file.",
                }
            from groq import Groq
            llm_service.client = Groq(api_key=api_key)

        working_model = None
        reply = ""
        last_err = None

        for model_to_test in llm_service.models:
            try:
                response = llm_service.client.chat.completions.create(
                    messages=[
                        {
                            "role": "user",
                            "content": "Respond with the single word 'ready'.",
                        }
                    ],
                    model=model_to_test,
                    max_tokens=60,
                )
                reply = response.choices[0].message.content.strip() if response.choices else ""
                working_model = model_to_test
                break
            except Exception as test_err:
                last_err = test_err
                continue

        if not working_model:
            raise last_err or RuntimeError("All Groq models failed health check.")

        return {
            "status": "healthy",
            "service": "groq",
            "model": working_model,
            "response": reply[:50],
            "message": "Groq API integration verified successfully.",
        }

    except Exception as exc:
        err_text = str(exc)
        if "gsk_" in err_text:
            err_text = "Authentication failed. Check GROQ_API_KEY in .env."

        return {
            "status": "error",
            "service": "groq",
            "message": f"Groq check failed: {err_text}",
        }






# ============================================================
# UPLOAD REPOSITORY
# ============================================================

@app.post("/api/repositories/upload")
async def upload_repository(
    file: UploadFile = File(...)
):
    """
    Upload a ZIP repository.

    This endpoint:
    1. Receives the ZIP file.
    2. Extracts the repository.
    3. Creates a unique repository ID.
    4. Returns repository information.

    Indexing is performed separately by /index.
    """

    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="No repository file was provided.",
        )

    if not file.filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=400,
            detail="Only ZIP repository files are supported.",
        )

    try:
        repository = await save_uploaded_repository(
            file
        )

        progress_service.initialize(repository["repository_id"])
        progress_service.update(
            repository["repository_id"],
            status="uploaded",
            stage="uploaded",
            progress=10,
            message="Repository uploaded successfully. Ready for indexing.",
        )

        return {
            "message": "Repository uploaded successfully.",
            "repository_id": repository["repository_id"],
            "repository": repository,
        }

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:

        print(
            f"Repository upload failed: {exc}"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to upload and extract the repository: "
                f"{str(exc)}"
            ),
        )

class GitHubImportRequest(BaseModel):
    url: str
    branch: str | None = None


# ============================================================
# FOLDER UPLOAD
# ============================================================

@app.post("/api/repositories/upload-folder")
async def upload_folder(
    files: list[UploadFile] = File(...),
    paths: list[str] = Form(...),
):
    """
    Upload a local project folder directly with relative file paths.
    """
    if not files or not paths:
        raise HTTPException(
            status_code=400,
            detail="No folder files were provided.",
        )

    repository_id = create_repository_id()
    repository_path = REPOSITORIES_DIR / repository_id
    repository_path.mkdir(parents=True, exist_ok=True)

    try:
        saved_files_count = 0
        for upload_file, rel_path in zip(files, paths):
            clean_rel = rel_path.strip().lstrip("/\\")
            if not clean_rel:
                continue

            if not is_safe_zip_path(repository_path, clean_rel):
                continue

            normalized_parts = Path(clean_rel.replace("\\", "/")).parts
            if any(part in IGNORED_DIRECTORIES for part in normalized_parts):
                continue

            target_path = repository_path / clean_rel
            target_path.parent.mkdir(parents=True, exist_ok=True)

            with open(target_path, "wb") as destination:
                while chunk := await upload_file.read(1024 * 1024):
                    destination.write(chunk)
            saved_files_count += 1

        if saved_files_count == 0:
            raise ValueError("No supported files found in the uploaded folder.")

        repository_info = get_repository_info(repository_path)
        progress_service.initialize(repository_id)
        progress_service.update(
            repository_id,
            status="uploaded",
            stage="uploaded",
            progress=10,
            message="Folder uploaded successfully. Ready for indexing.",
        )
        return {
            "message": "Folder uploaded successfully.",
            "repository_id": repository_id,
            "repository": repository_info,
        }

    except Exception as exc:
        if repository_path.exists():
            shutil.rmtree(repository_path, ignore_errors=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process uploaded folder: {str(exc)}",
        )


# ============================================================
# GITHUB REPOSITORY IMPORT
# ============================================================

@app.post("/api/repositories/github")
async def import_github_repository(payload: GitHubImportRequest):
    """
    Import a repository directly from a public HTTPS GitHub URL.
    Validates URL format, downloads the archive, and routes through
    the exact same safe extraction/indexing pipeline as ZIP uploads.
    """
    url = (payload.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="GitHub URL is required.")

    # Strict HTTPS GitHub URL validation
    # Format: https://github.com/owner/repo or https://github.com/owner/repo/tree/branch
    match = re.match(
        r"^https://github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+?)(?:\.git)?(?:/(?:tree|commits)/([a-zA-Z0-9_.-]+))?/?$",
        url
    )
    if not match:
        raise HTTPException(
            status_code=400,
            detail="Invalid GitHub repository URL. Must be an HTTPS URL such as https://github.com/owner/repository."
        )

    owner = match.group(1)
    repo = match.group(2)
    branch = payload.branch or match.group(3)

    repository_id = create_repository_id()
    repository_path = REPOSITORIES_DIR / repository_id
    zip_path = DATA_DIR / "uploads" / f"{repository_id}.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    branches_to_try = [branch] if branch else ["main", "master"]
    downloaded = False

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=90.0) as client:
            for b in branches_to_try:
                zip_url = f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{b}"
                resp = await client.get(zip_url)
                if resp.status_code == 200:
                    zip_path.write_bytes(resp.content)
                    downloaded = True
                    break

        if not downloaded:
            raise HTTPException(
                status_code=404,
                detail="GitHub repository was not found, is private, or specified branch does not exist."
            )

        # Send downloaded archive through the exact same safe extraction pipeline
        extract_repository(
            zip_path=str(zip_path),
            repository_id=repository_id
        )

        repository_info = get_repository_info(repository_path)
        progress_service.initialize(repository_id)
        progress_service.update(
            repository_id,
            status="uploaded",
            stage="uploaded",
            progress=10,
            message="Repository imported successfully from GitHub. Ready for indexing.",
        )
        return {
            "message": "Repository imported successfully from GitHub.",
            "repository_id": repository_id,
            "repository": repository_info,
        }

    except HTTPException:
        if repository_path.exists():
            shutil.rmtree(repository_path, ignore_errors=True)
        raise

    except Exception as exc:
        if repository_path.exists():
            shutil.rmtree(repository_path, ignore_errors=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process GitHub repository: {str(exc)}"
        )

    finally:
        if zip_path.exists():
            try:
                zip_path.unlink()
            except OSError:
                pass


# ============================================================
# REPOSITORY SUMMARY (LANGUAGES, DEPS, SAFE ENV)
# ============================================================

@app.get("/api/repositories/{repository_id}/summary")
def get_repository_summary(repository_id: str):
    """
    Return language summary, dependency manifests, and safe environment inventory.
    Secrets are always redacted.
    """
    repository_path = REPOSITORIES_DIR / repository_id
    if not repository_path.exists():
        raise HTTPException(status_code=404, detail="Repository not found.")

    return {
        "repository_id": repository_id,
        "language_summary": summarize_languages(repository_path),
        "dependency_manifests": parse_dependency_manifests(repository_path),
        "environment_files": inspect_env_files(repository_path),
    }


# ============================================================
# REPOSITORY OVERVIEW
# ============================================================

@app.get(
    "/api/repositories/{repository_id}/overview"
)
def get_repository_overview(
    repository_id: str
):
    """
    Analyze the uploaded repository and return
    deterministic repository-level information.
    """

    repository_path = (
        REPOSITORIES_DIR / repository_id
    )

    if not repository_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Repository not found.",
        )

    if not repository_path.is_dir():
        raise HTTPException(
            status_code=400,
            detail="Repository path is invalid.",
        )

    try:

        analyzer = RepositoryOverviewAnalyzer(
            repository_path
        )

        overview = analyzer.analyze()

        return {
            "repository_id": repository_id,
            "overview": overview,
        }

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:

        print(
            f"Repository overview failed: {exc}"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to analyze repository: "
                f"{str(exc)}"
            ),
        )
# ============================================================
# TECHNOLOGY STACK
# ============================================================

@app.get(
    "/api/repositories/{repository_id}/technology-stack"
)
def get_technology_stack(
    repository_id: str
):
    """
    Detect the technologies used by the repository.

    Detection is primarily deterministic and based on:
    - file extensions
    - dependency files
    - imports
    - project configuration
    """

    repository_path = (
        REPOSITORIES_DIR / repository_id
    )

    if not repository_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Repository not found.",
        )

    if not repository_path.is_dir():
        raise HTTPException(
            status_code=400,
            detail="Repository path is invalid.",
        )

    try:

        detector = TechnologyStackDetector(
            repository_path
        )

        technology_stack = detector.detect()

        return {
            "repository_id": repository_id,
            "technology_stack": technology_stack,
        }

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:

        print(
            f"Technology stack detection failed: {exc}"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to detect technology stack: "
                f"{str(exc)}"
            ),
        )
# ============================================================
# IMPORTANT FILES
# ============================================================

@app.get(
    "/api/repositories/{repository_id}/important-files"
)
def get_important_files(
    repository_id: str,
    top_k: int = 20,
):
    """
    Identify files that are most important for
    understanding the repository.
    """

    repository_path = (
        REPOSITORIES_DIR / repository_id
    )

    if not repository_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Repository not found.",
        )

    if not repository_path.is_dir():
        raise HTTPException(
            status_code=400,
            detail="Repository path is invalid.",
        )

    if top_k < 1:
        raise HTTPException(
            status_code=400,
            detail="top_k must be at least 1.",
        )

    try:

        analyzer = ImportantFileAnalyzer(
            repository_path
        )

        important_files = analyzer.analyze(
            top_k=top_k
        )

        return {
            "repository_id": repository_id,
            "total_files_analyzed": len(
                analyzer.get_files()
            ),
            "important_files": important_files,
        }

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:

        print(
            f"Important file analysis failed: {exc}"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to analyze important files: "
                f"{str(exc)}"
            ),
        )
# ============================================================
# REPOSITORY STRUCTURE
# ============================================================

@app.get(
    "/api/repositories/{repository_id}/structure"
)
def get_repository_structure(
    repository_id: str,
):
    """
    Analyze the structural organization of a repository.
    """

    repository_path = (
        REPOSITORIES_DIR / repository_id
    )

    if not repository_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Repository not found.",
        )

    if not repository_path.is_dir():
        raise HTTPException(
            status_code=400,
            detail="Repository path is invalid.",
        )

    try:

        analyzer = RepositoryStructureAnalyzer(
            repository_path
        )

        result = analyzer.analyze()

        return {
            "repository_id": repository_id,
            "structure": result,
        }

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:

        print(
            f"Repository structure analysis failed: {exc}"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to analyze repository structure: "
                f"{str(exc)}"
            ),
        )
# ============================================================
# API DISCOVERY
# ============================================================

@app.get(
    "/api/repositories/{repository_id}/apis"
)
def get_repository_apis(
    repository_id: str,
):
    """
    Discover API endpoints exposed by a repository.
    """

    repository_path = (
        REPOSITORIES_DIR / repository_id
    )

    if not repository_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Repository not found.",
        )

    if not repository_path.is_dir():
        raise HTTPException(
            status_code=400,
            detail="Repository path is invalid.",
        )

    try:

        analyzer = APIAnalyzer(
            repository_id
        )

        result = analyzer.analyze()

        return {
            "repository_id": repository_id,
            "api_discovery": result,
        }

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:

        print(
            f"API discovery failed: {exc}"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to discover APIs: "
                f"{str(exc)}"
            ),
        )
@app.get("/api/repositories/{repository_id}/architecture")
def get_repository_architecture(repository_id: str):
    """
    Analyze the static architecture of a repository.
    """

    try:
        analyzer = ArchitectureAnalyzer(repository_id)
        result = analyzer.analyze()

        return {
            "repository_id": repository_id,
            "architecture": result,
        }

    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Architecture analysis failed: {str(exc)}",
        )
@app.get("/api/repositories/{repository_id}/dependencies")
def analyze_dependencies(repository_id: str):
    analyzer = DependencyAnalyzer(repository_id)

    try:
        result = analyzer.analyze()

        return {
            "repository_id": repository_id,
            "dependency_analysis": result,
        }

    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )
@app.get(
    "/api/repositories/{repository_id}/impact/{file_path:path}"
)
def analyze_file_impact(
    repository_id: str,
    file_path: str,
):
    analyzer = ImpactAnalyzer(
        repository_id
    )

    try:
        return {
            "repository_id": repository_id,
            "impact_analysis": analyzer.analyze(
                file_path
            ),
        }

    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )
@app.get(
    "/api/repositories/{repository_id}/impact"
)
def analyze_repository_impact(
    repository_id: str,
):
    analyzer = ImpactAnalyzer(
        repository_id
    )

    try:
        return {
            "repository_id": repository_id,
            "impact_analysis": analyzer.analyze(),
        }

    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )
@app.get(
    "/api/repositories/{repository_id}/onboarding"
)
def analyze_onboarding(
    repository_id: str,
):
    analyzer = OnboardingAnalyzer(
        repository_id
    )

    try:
        return {
            "repository_id": repository_id,
            "onboarding": analyzer.analyze(),
        }

    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )
# ============================================================
# INDEX REPOSITORY
# ============================================================

@app.post(
    "/api/repositories/{repository_id}/index"
)
def index_repository(
    repository_id: str
):
    """
    Index an uploaded repository into the vector database.

    Indexing pipeline:

        scanning
            ↓
        chunking
            ↓
        embedding
            ↓
        indexing
            ↓
        completed

    Progress is tracked using progress_service.
    """

    # --------------------------------------------------------
    # INITIALIZE PROGRESS
    # --------------------------------------------------------

    progress_service.initialize(
        repository_id
    )

    try:

        # ====================================================
        # REPOSITORY PATH
        # ====================================================

        repository_path = (
            REPOSITORIES_DIR / repository_id
        )

        # ----------------------------------------------------
        # VALIDATE REPOSITORY
        # ----------------------------------------------------

        if not repository_path.exists():

            progress_service.fail(
                repository_id,
                "Repository not found."
            )

            raise HTTPException(
                status_code=404,
                detail="Repository not found."
            )

        if not repository_path.is_dir():

            progress_service.fail(
                repository_id,
                "Repository path is not a directory."
            )

            raise HTTPException(
                status_code=400,
                detail=(
                    "Repository path is not a directory."
                )
            )

        # ====================================================
        # STEP 1: SCANNING
        # ====================================================

        progress_service.update(
            repository_id,
            status="indexing",
            stage="scanning",
            progress=10,
            processed_files=0,
            total_files=0,
            processed_chunks=0,
            total_chunks=0,
            message=(
                "Scanning repository files..."
            )
        )

        # Get supported files using the existing
        # repository manager function.
        files = get_supported_files(
            repository_path
        )

        total_files = len(files)

        progress_service.update(
            repository_id,
            stage="scanning",
            progress=20,
            processed_files=0,
            total_files=total_files,
            processed_chunks=0,
            total_chunks=0,
            message=(
                f"Found {total_files} "
                "supported files."
            )
        )

        # ====================================================
        # STEP 2: CHUNKING
        # ====================================================

        progress_service.update(
            repository_id,
            stage="chunking",
            progress=30,
            processed_files=0,
            total_files=total_files,
            processed_chunks=0,
            total_chunks=0,
            message=(
                "Creating code-aware chunks..."
            )
        )

        # ----------------------------------------------------
        # ----------------------------------------------------
        # STREAMING BATCH INDEXING FOR LOW RAM (512MB)
        #
        # Instead of accumulating all chunks and embeddings in memory,
        # files are processed incrementally and chunks are embedded and
        # stored in ChromaDB in small, bounded batches (24 chunks).
        # Memory usage remains O(batch_size) rather than O(repo_size).
        # ----------------------------------------------------

        # Clear any existing index for this repository
        vector_store.delete_repository(repository_id)

        CHUNK_BATCH_LIMIT = int(os.getenv("INDEXING_CHUNK_BATCH_SIZE", "24"))
        chunk_buffer = []
        total_chunks = 0

        for file_idx, file_path in enumerate(files):
            file_chunks = chunk_file(
                file_path=file_path,
                repository_root=repository_path,
                repository_id=repository_id
            )
            if file_chunks:
                chunk_buffer.extend(file_chunks)

            # When chunk buffer reaches threshold, embed and upsert immediately
            if len(chunk_buffer) >= CHUNK_BATCH_LIMIT:
                docs = [c["content"] for c in chunk_buffer]
                embs = embedding_service.embed_documents(docs)
                vector_store.add_chunks(repository_id, chunk_buffer, embs)
                total_chunks += len(chunk_buffer)

                chunk_buffer.clear()
                docs.clear()
                embs.clear()
                gc.collect()

                calc_progress = min(85, 30 + int(((file_idx + 1) / total_files) * 55))
                progress_service.update(
                    repository_id,
                    stage="indexing",
                    progress=calc_progress,
                    processed_files=file_idx + 1,
                    total_files=total_files,
                    processed_chunks=total_chunks,
                    total_chunks=total_chunks,
                    message=f"Indexed {total_chunks} chunks ({file_idx + 1}/{total_files} files)..."
                )

        # Process any remaining chunks in final batch
        if chunk_buffer:
            docs = [c["content"] for c in chunk_buffer]
            embs = embedding_service.embed_documents(docs)
            vector_store.add_chunks(repository_id, chunk_buffer, embs)
            total_chunks += len(chunk_buffer)
            chunk_buffer.clear()
            docs.clear()
            embs.clear()
            gc.collect()

        # Check for empty repository
        if total_chunks == 0:
            progress_service.fail(
                repository_id,
                "No supported content was found to index."
            )
            raise HTTPException(
                status_code=400,
                detail="No supported content was found to index."
            )

        progress_service.update(
            repository_id,
            stage="indexing",
            progress=95,
            processed_files=total_files,
            total_files=total_files,
            processed_chunks=total_chunks,
            total_chunks=total_chunks,
            message="Repository indexed in ChromaDB."
        )

        progress_service.complete(
            repository_id,
            processed_files=total_files,
            total_files=total_files,
            processed_chunks=total_chunks,
            total_chunks=total_chunks
        )

        return {
            "repository_id": repository_id,
            "status": "completed",
            "message": "Repository indexed successfully.",
            "total_files": total_files,
            "total_chunks": total_chunks
        }

    # ========================================================
    # HTTP EXCEPTIONS
    # ========================================================

    except HTTPException:
        raise

    # ========================================================
    # UNEXPECTED ERRORS
    # ========================================================

    except Exception as exc:

        # Update progress state to failed.
        progress_service.fail(
            repository_id,
            str(exc)
        )

        # Print error in terminal for debugging.
        print(
            "Repository indexing failed:",
            str(exc)
        )

        raise HTTPException(
            status_code=500,
            detail=str(exc)
        )
# ============================================================
# REPOSITORY INDEXING PROGRESS
# ============================================================

@app.get(
    "/api/repositories/{repository_id}/progress"
)
def get_repository_progress(repository_id: str):
    """
    Return the current indexing progress of a repository.
    Handles in-memory tracking as well as on-disk existing repositories.
    """
    progress = progress_service.get(repository_id)
    if progress is not None:
        return progress

    repository_path = REPOSITORIES_DIR / repository_id
    if not repository_path.exists() or not repository_path.is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"Repository '{repository_id}' does not exist on server. Please click '+ New repository' to re-import.",
        )

    try:
        collection = vector_store.get_collection(repository_id)
        chunk_count = collection.count()
    except Exception:
        chunk_count = 0

    if chunk_count > 0:
        completed_info = {
            "repository_id": repository_id,
            "status": "completed",
            "stage": "completed",
            "progress": 100,
            "processed_chunks": chunk_count,
            "total_chunks": chunk_count,
            "message": "Repository is indexed and ready.",
            "exists": True,
        }
        progress_service.update(
            repository_id,
            status="completed",
            stage="completed",
            progress=100,
            message="Repository is indexed and ready.",
        )
        return completed_info

    return {
        "repository_id": repository_id,
        "status": "ready_for_indexing",
        "stage": "uploaded",
        "progress": 10,
        "message": "Repository files uploaded, ready for indexing.",
        "exists": True,
    }
# ============================================================
# SEMANTIC SEARCH
# ============================================================

@app.post(
    "/api/repositories/{repository_id}/search"
)
def semantic_search(
    repository_id: str,
    request: SearchRequest,
):
    """
    Perform semantic search over the selected repository.
    """

    if not request.query.strip():

        raise HTTPException(
            status_code=400,
            detail="Search query cannot be empty.",
        )

    if request.top_k < 1:

        raise HTTPException(
            status_code=400,
            detail="top_k must be at least 1.",
        )

    repository_path = REPOSITORIES_DIR / repository_id
    if not repository_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Repository not found on server. Please click '+ New repository' to re-import or upload your project.",
        )

    try:

        results = search_service.search(
            repository_id=repository_id,
            query=request.query,
            top_k=request.top_k,
        )

        return {
            "repository_id": repository_id,
            "query": request.query,
            "results": results,
        }

    except Exception as exc:

        print(
            f"Semantic search failed: {exc}"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Semantic search failed: "
                f"{str(exc)}"
            ),
        )


# ============================================================
# ASK CODELENS
# ============================================================

@app.post(
    "/api/repositories/{repository_id}/ask"
)
def ask_repository(
    repository_id: str,
    request: AskRequest,
):
    """
    Complete RAG pipeline:

    Question
        ↓
    Semantic retrieval
        ↓
    Relevant code chunks
        ↓
    Gemini
        ↓
    Grounded answer
    """

    if not request.question.strip():

        raise HTTPException(
            status_code=400,
            detail="Question cannot be empty.",
        )

    if request.top_k < 1:

        raise HTTPException(
            status_code=400,
            detail="top_k must be at least 1.",
        )

    repository_path = REPOSITORIES_DIR / repository_id
    if not repository_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Repository not found on server. Please click '+ New repository' to re-import or upload your project.",
        )

    try:

        result = rag_service.answer_question(
            repository_id=repository_id,
            question=request.question,
            top_k=request.top_k,
        )

        return result

    except Exception as exc:

        print(
            f"RAG request failed: {exc}"
        )

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


# ============================================================
# ============================================================
# LOGIN ROUTE
# ============================================================

@app.get("/login")
def login_route():
    login_file = FRONTEND_DIR / "login.html"
    if login_file.exists():
        return FileResponse(str(login_file))
    return FileResponse(str(FRONTEND_DIR / "index.html"))


# ============================================================
# STATIC FILES (FRONTEND)
# ============================================================

if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


# ============================================================
# STARTUP
# ============================================================

@app.on_event("startup")
def startup_event():
    port = os.getenv("PORT", "8000")
    host = os.getenv("HOST", "0.0.0.0")

    print("")
    print("=" * 60)
    print("CodeLens AI started successfully!")
    print(f"Live Application URL: http://{host}:{port}")
    print(f"API Documentation:    http://{host}:{port}/docs")
    print("Worker mode:          Single worker (Render 512MB RAM optimized)")
    print("Embedding loading:    Lazy on-demand (all-MiniLM-L6-v2)")
    print("=" * 60)
    print("")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    print(f"Starting single-worker Uvicorn server on {host}:{port}...")
    uvicorn.run("main:app", host=host, port=port, workers=1, reload=False)