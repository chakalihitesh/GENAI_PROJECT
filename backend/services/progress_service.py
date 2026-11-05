import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Dict, Any, Optional

from config import METADATA_DIR, REPOSITORIES_DIR

logger = logging.getLogger(__name__)


class ProgressService:
    """
    Thread-safe repository indexing progress tracker with on-disk JSON persistence.
    Tracks state across server recycles and prevents duplicate concurrent indexing jobs.

    Handles states:
    - pending
    - cloning
    - extracting
    - scanning
    - chunking
    - embedding
    - indexing
    - completed
    - failed
    """

    def __init__(self, metadata_dir: Path = METADATA_DIR):
        self._progress: Dict[str, Dict[str, Any]] = {}
        self._lock = Lock()
        self._active_indexing_jobs: set[str] = set()
        self.metadata_dir = Path(metadata_dir)
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        self._load_all_from_disk()

    def _get_meta_path(self, repository_id: str) -> Path:
        return self.metadata_dir / f"{repository_id}.json"

    def _persist(self, repository_id: str, data: Dict[str, Any]) -> None:
        """Save progress data to disk for persistent tracking across restarts."""
        try:
            target_path = self._get_meta_path(repository_id)
            target_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

            # Also persist inside the repository directory if it exists
            repo_folder = REPOSITORIES_DIR / repository_id
            if repo_folder.is_dir():
                (repo_folder / ".codelens_meta.json").write_text(
                    json.dumps(data, indent=2), encoding="utf-8"
                )
        except Exception as e:
            logger.warning(f"Failed to persist progress metadata for {repository_id}: {e}")

    def _load_all_from_disk(self) -> None:
        """Preload saved metadata from disk on startup."""
        try:
            for p in self.metadata_dir.glob("*.json"):
                try:
                    repo_id = p.stem
                    data = json.loads(p.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        self._progress[repo_id] = data
                except Exception:
                    pass
        except Exception:
            pass

    def is_indexing(self, repository_id: str) -> bool:
        """Check if an indexing job is currently active for this repository."""
        with self._lock:
            return repository_id in self._active_indexing_jobs

    def acquire_indexing(self, repository_id: str) -> bool:
        """
        Attempt to acquire indexing lock for repository_id.
        Returns True if lock acquired, False if job is already active.
        """
        with self._lock:
            if repository_id in self._active_indexing_jobs:
                return False
            self._active_indexing_jobs.add(repository_id)
            return True

    def release_indexing(self, repository_id: str) -> None:
        """Release indexing lock."""
        with self._lock:
            self._active_indexing_jobs.discard(repository_id)

    def initialize(
        self,
        repository_id: str,
        *,
        status: str = "initialized",
        stage: str = "initialized",
        progress: int = 0,
        message: str = "Repository processing initialized."
    ) -> None:
        """
        Initialize progress tracking for a repository.
        """
        with self._lock:
            now_iso = datetime.now(timezone.utc).isoformat()
            data = {
                "repository_id": repository_id,
                "status": status,
                "stage": stage,
                "progress": progress,
                "processed_files": 0,
                "total_files": 0,
                "processed_chunks": 0,
                "total_chunks": 0,
                "message": message,
                "error": None,
                "updated_at": now_iso,
            }
            self._progress[repository_id] = data
            self._persist(repository_id, data)

    def update(
        self,
        repository_id: str,
        *,
        status: str | None = None,
        stage: str | None = None,
        progress: int | None = None,
        processed_files: int | None = None,
        total_files: int | None = None,
        processed_chunks: int | None = None,
        total_chunks: int | None = None,
        message: str | None = None,
        error: str | None = None,
    ) -> None:
        """
        Update one or more progress fields and persist to disk.
        """
        with self._lock:
            if repository_id not in self._progress:
                self.initialize(repository_id)

            current = self._progress[repository_id]

            if status is not None:
                current["status"] = status
            if stage is not None:
                current["stage"] = stage
            if progress is not None:
                current["progress"] = max(0, min(100, progress))
            if processed_files is not None:
                current["processed_files"] = processed_files
            if total_files is not None:
                current["total_files"] = total_files
            if processed_chunks is not None:
                current["processed_chunks"] = processed_chunks
            if total_chunks is not None:
                current["total_chunks"] = total_chunks
            if message is not None:
                current["message"] = message
            if error is not None:
                current["error"] = error

            current["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._persist(repository_id, current)

    def get(self, repository_id: str) -> Optional[Dict[str, Any]]:
        """
        Get current progress for a repository.
        Checks memory first, then disk persistence.
        """
        with self._lock:
            prog = self._progress.get(repository_id)
            if prog is not None:
                return prog.copy()

        # Fallback to persistent JSON file in metadata/
        meta_file = self._get_meta_path(repository_id)
        if meta_file.is_file():
            try:
                data = json.loads(meta_file.read_text(encoding="utf-8"))
                with self._lock:
                    self._progress[repository_id] = data
                return data.copy()
            except Exception:
                pass

        # Fallback to repository directory .codelens_meta.json
        repo_meta = REPOSITORIES_DIR / repository_id / ".codelens_meta.json"
        if repo_meta.is_file():
            try:
                data = json.loads(repo_meta.read_text(encoding="utf-8"))
                with self._lock:
                    self._progress[repository_id] = data
                return data.copy()
            except Exception:
                pass

        return None

    def complete(
        self,
        repository_id: str,
        *,
        processed_files: int | None = None,
        total_files: int | None = None,
        processed_chunks: int | None = None,
        total_chunks: int | None = None,
    ) -> None:
        """
        Mark repository processing as completed.
        """
        self.update(
            repository_id,
            status="completed",
            stage="completed",
            progress=100,
            processed_files=processed_files,
            total_files=total_files,
            processed_chunks=processed_chunks,
            total_chunks=total_chunks,
            message="Repository indexed successfully.",
        )

    def fail(
        self,
        repository_id: str,
        message: str,
        error: str | None = None,
    ) -> None:
        """
        Mark repository processing as failed.
        """
        self.update(
            repository_id,
            status="failed",
            stage="failed",
            message=message,
            error=error or message,
        )

    def remove(self, repository_id: str) -> None:
        """
        Remove progress information for a repository.
        """
        with self._lock:
            self._progress.pop(repository_id, None)
            self._active_indexing_jobs.discard(repository_id)
        try:
            self._get_meta_path(repository_id).unlink(missing_ok=True)
        except Exception:
            pass


progress_service = ProgressService()
