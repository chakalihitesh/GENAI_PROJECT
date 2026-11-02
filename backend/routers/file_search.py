from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from config import REPOSITORIES_DIR
from services.repository_file_search import list_files, find_text

router = APIRouter(prefix="/api/repositories", tags=["file-search"])


@router.get("/{repository_id}/files")
def repository_files(
    repository_id: str,
    query: str = Query(default=""),
    extension: str = Query(default=""),
):
    """
    Return repository-relative file list matching query/extension.
    """
    if not repository_id or Path(repository_id).name != repository_id:
        raise HTTPException(status_code=400, detail="Invalid repository ID")

    root = REPOSITORIES_DIR / repository_id
    try:
        files = list_files(root, query=query, extension=extension)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Repository not found")

    return {
        "repository_id": repository_id,
        "count": len(files),
        "files": files,
    }


@router.get("/{repository_id}/search-text")
def repository_search_text(
    repository_id: str,
    query: str = Query(default=""),
    max_matches: int = Query(default=50, ge=1, le=200),
):
    """
    Search text across all repository files and embedded archives for literal matches.
    """
    if not repository_id or Path(repository_id).name != repository_id:
        raise HTTPException(status_code=400, detail="Invalid repository ID")

    root = REPOSITORIES_DIR / repository_id
    try:
        matches = find_text(root, query=query, max_matches=max_matches)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Repository not found")

    return {
        "repository_id": repository_id,
        "query": query,
        "count": len(matches),
        "matches": matches,
    }
