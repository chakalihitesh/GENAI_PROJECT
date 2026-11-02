from pathlib import Path
from collections.abc import Iterable
import re
import zipfile

IGNORED = {
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    "dist", "build", ".next", "coverage", ".pytest_cache",
    ".ruff_cache", ".mypy_cache"
}

SENSITIVE = {".env", ".env.local", ".env.production", ".env.staging", ".env.development"}

LOCK_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "poetry.lock", "cargo.lock", "composer.lock"
}

TEXT_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css",
    ".scss", ".sass", ".json", ".md", ".txt", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".sql", ".sh", ".bash", ".xml"
}

EXT_MAP = {
    "css": ".css",
    "html": ".html",
    "python": ".py",
    "py": ".py",
    "typescript": ".ts",
    "ts": ".ts",
    "tsx": ".tsx",
    "javascript": ".js",
    "js": ".js",
    "jsx": ".jsx",
    "json": ".json",
    "sql": ".sql",
    "markdown": ".md",
    "md": ".md",
    "yaml": ".yaml",
    "yml": ".yml",
    "toml": ".toml",
    "scss": ".scss",
}


def _safe_files(root: Path) -> Iterable[Path]:
    """
    Yield all regular files in the repository directory, strictly
    excluding vendor/build directories and sensitive environment files.
    Read-only traversal; never mutates the repository.
    """
    root = root.resolve()
    if not root.is_dir():
        raise FileNotFoundError("Repository directory was not found")

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        rel = path.relative_to(root)
        if any(part in IGNORED for part in rel.parts):
            continue

        lower_name = path.name.lower()
        if lower_name in SENSITIVE or lower_name.startswith(".env"):
            continue

        yield path


def list_files(root: Path, query: str = "", extension: str = "") -> list[dict]:
    """
    Return repository-relative file inventory matching an optional query
    and/or file extension (e.g. 'css' or '.css').
    """
    root = Path(root).resolve()
    query = query.strip().casefold()
    extension = extension.strip().casefold()
    if extension and not extension.startswith("."):
        extension = "." + extension

    results = []
    for path in _safe_files(root):
        rel = path.relative_to(root).as_posix()
        if query and query not in rel.casefold():
            continue
        if extension and path.suffix.casefold() != extension:
            continue

        results.append({
            "path": rel,
            "extension": path.suffix.casefold(),
            "size_bytes": path.stat().st_size,
        })

    return sorted(results, key=lambda item: item["path"].casefold())


def find_text(root: Path, query: str, path_filter: str = "", max_matches: int = 50) -> list[dict]:
    """
    Search text files and embedded archives for literal query occurrences,
    returning exact repository-relative paths, line numbers, and excerpts.
    Never alters files. Excludes package lockfiles to avoid false positives.
    """
    root = Path(root).resolve()
    if not query or not query.strip():
        return []

    query_cf = query.strip().casefold()
    path_filter_cf = path_filter.strip().casefold()
    matches = []

    # Prioritize files whose path matches path_filter or query
    all_items = list_files(root)
    def _priority(item: dict) -> tuple[int, int, str]:
        p = item["path"].casefold()
        stem = Path(p).stem.casefold()
        filename = Path(p).name.casefold()
        if path_filter_cf and path_filter_cf == stem:
            return (0, len(p), p)
        if path_filter_cf and path_filter_cf in filename:
            return (1, len(p), p)
        if path_filter_cf and path_filter_cf in p:
            return (2, len(p), p)
        if query_cf in filename:
            return (3, len(p), p)
        if query_cf in p:
            return (4, len(p), p)
        return (5, len(p), p)

    sorted_items = sorted(all_items, key=_priority)

    for item in sorted_items:
        path = root / item["path"]
        if path.name.lower() in LOCK_FILES:
            continue

        suffix = path.suffix.casefold()

        # Handle standard source/text files
        if suffix in TEXT_EXTENSIONS:
            try:
                if path.stat().st_size > 1_000_000:
                    continue
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue

            for number, line in enumerate(lines, 1):
                if query_cf in line.casefold():
                    matches.append({
                        "path": item["path"],
                        "line": number,
                        "excerpt": line.strip()[:300],
                    })
                    if len(matches) >= max_matches:
                        return matches

        # Read-only search inside archive files without extracting or modifying disk
        elif suffix == ".zip":
            try:
                with zipfile.ZipFile(path, "r") as archive:
                    for info in archive.infolist():
                        if info.is_dir():
                            continue
                        sub_ext = Path(info.filename).suffix.casefold()
                        if sub_ext not in TEXT_EXTENSIONS:
                            continue
                        if any(part in IGNORED for part in Path(info.filename).parts):
                            continue
                        if Path(info.filename).name.lower() in LOCK_FILES:
                            continue
                        if info.file_size > 1_000_000:
                            continue

                        with archive.open(info, "r") as f:
                            content = f.read().decode("utf-8", errors="ignore")
                            for number, line in enumerate(content.splitlines(), 1):
                                if query_cf in line.casefold():
                                    matches.append({
                                        "path": f"{item['path']}:{info.filename}",
                                        "line": number,
                                        "excerpt": line.strip()[:300],
                                    })
                                    if len(matches) >= max_matches:
                                        return matches
            except (zipfile.BadZipFile, OSError):
                continue

    return matches


def retrieve_file_search_chunks(root: Path, question: str) -> list[dict]:
    """
    Produce grounded retrieval chunks from file inventory and literal text searches.
    Returns real repository-relative paths, line numbers, and excerpts.
    Never invents paths or code.
    """
    root = Path(root).resolve()
    if not root.is_dir() or not question:
        return []

    q_lower = question.lower()
    chunks = []

    # 1. Extension / file listing queries (e.g. "what are the css files", "list all css files")
    for word, ext in EXT_MAP.items():
        pattern = rf"(?:all\s+)?(?:\*\.)?{re.escape(word)}\s+files?|\b{re.escape(word)}\s+files?\b|\b\.{re.escape(word)}\b"
        if re.search(pattern, q_lower):
            matching_files = list_files(root, extension=ext)
            if matching_files:
                file_lines = [f"- {f['path']} ({f['size_bytes']} bytes)" for f in matching_files]
                content = (
                    f"Repository file inventory for extension '{ext}' "
                    f"({len(matching_files)} matching files found):\n"
                    + "\n".join(file_lines)
                )
                chunks.append({
                    "content": content,
                    "metadata": {
                        "file_path": f"*{ext}",
                        "name": f"file_inventory_{word}",
                        "start_line": 1,
                        "end_line": len(matching_files),
                        "chunk_type": "file_inventory",
                    },
                    "distance": 0.0,
                })
            break

    # 2. Path queries (e.g. "find paths containing 'dashboard'", "dashboard files")
    quoted_phrases = re.findall(r"['\"]([a-zA-Z0-9_\s.-]+)['\"]", question)
    path_term_matches = []
    for qp in quoted_phrases:
        cleaned = qp.strip()
        if cleaned:
            path_term_matches.append(cleaned)

    if not path_term_matches:
        m = re.search(r"(?:containing|named|with)\s+([a-zA-Z0-9_.-]+)", q_lower)
        if m:
            path_term_matches.append(m.group(1))
        stop_words = {
            "find", "paths", "path", "files", "file", "all", "what", "where",
            "which", "are", "the", "containing", "named", "with", "show",
            "list", "does", "this", "project", "and", "evidence", "defined", "how"
        }
        for word in re.findall(r"\b[a-zA-Z0-9_-]{3,}\b", q_lower):
            if word not in stop_words:
                path_term_matches.append(word)

    for term in set(path_term_matches):
        if len(term) >= 3 and term.lower() not in {"files", "file", "path", "paths", "all", "the", "and", "evidence"}:
            matches = list_files(root, query=term)
            if matches:
                path_lines = [f"- {f['path']}" for f in matches]
                content = (
                    f"Repository files matching path keyword '{term}' "
                    f"({len(matches)} files found):\n"
                    + "\n".join(path_lines)
                )
                chunks.append({
                    "content": content,
                    "metadata": {
                        "file_path": "Path Search",
                        "name": f"path_search_{term}",
                        "start_line": 1,
                        "end_line": len(matches),
                        "chunk_type": "path_inventory",
                    },
                    "distance": 0.0,
                })

    # 3. Source-location / text queries (e.g. "where is the dashboard title/color defined?")
    is_location_query = any(k in q_lower for k in [
        "where is", "where are", "how is", "what file", "which file",
        "defined", "title", "color", "colour", "background", "theme",
        "connect", "database", "auth", "login", "authenticate"
    ])

    if is_location_query or not chunks:
        candidate_terms = []
        # Exact quoted phrases get highest priority
        for qp in quoted_phrases:
            if qp not in candidate_terms:
                candidate_terms.append(qp)

        candidate_terms.extend([t for t in path_term_matches if t not in candidate_terms])
        keywords = ["title", "color", "colour", "dashboard", "authenticate", "auth", "login", "signup", "database", "db", "connect"]
        for kw in keywords:
            if kw in q_lower and kw not in candidate_terms:
                candidate_terms.append(kw)

        # Infer companion terms for concepts
        if any(w in q_lower for w in ["auth", "login", "signup", "signin", "authenticate"]):
            for extra in ["login", "signup", "auth"]:
                if extra not in candidate_terms:
                    candidate_terms.append(extra)

        if any(w in q_lower for w in ["database", "connect", "db"]):
            for extra in ["sqlite", "db", "database", "connect"]:
                if extra not in candidate_terms:
                    candidate_terms.append(extra)

        primary_filter = ""
        for pf in ["dashboard", "auth", "login", "signup", "database", "home", "header", "nav"]:
            if pf in q_lower:
                primary_filter = pf
                break

        for term in candidate_terms[:5]:
            text_matches = find_text(root, query=term, path_filter=primary_filter, max_matches=10)
            for tm in text_matches:
                chunks.append({
                    "content": (
                        f"Exact match for '{term}' at line {tm['line']} of {tm['path']}:\n"
                        f"{tm['excerpt']}"
                    ),
                    "metadata": {
                        "file_path": tm["path"],
                        "name": f"line_{tm['line']}",
                        "start_line": tm["line"],
                        "end_line": tm["line"],
                        "chunk_type": "source_location",
                    },
                    "distance": 0.0,
                })

    return chunks

    return chunks
