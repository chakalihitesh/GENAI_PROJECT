import json
import re
import shutil
import uuid
import zipfile
from collections import Counter
from pathlib import Path

from config import (
    REPOSITORIES_DIR,
    DATA_DIR,
    MAX_ZIP_FILES,
    MAX_UNCOMPRESSED_BYTES,
    MAX_COMPRESSED_BYTES,
    MAX_SINGLE_FILE_SIZE,
    MAX_COMPRESSION_RATIO,
)


# ============================================================
# DIRECTORIES
# ============================================================

BASE_REPOSITORY_DIR = REPOSITORIES_DIR
UPLOAD_DIR = DATA_DIR / "uploads"


# ============================================================
# DIRECTORY FILTERING
# ============================================================

# Directories that should not be indexed because they normally
# contain dependencies, generated files, caches, or Git metadata.
IGNORED_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",

    "node_modules",

    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",

    ".venv",
    "venv",
    "env",
    "virtualenv",

    ".idea",
    ".vscode",

    "dist",
    "build",
    "out",
    ".next",
    ".nuxt",

    "coverage",
    ".coverage",

    "target",

    "vendor",
}


# ============================================================
# FILE FILTERING
# ============================================================

SUPPORTED_EXTENSIONS = {
    # Python
    ".py",
    ".pyw",

    # JavaScript / TypeScript
    ".js",
    ".jsx",
    ".ts",
    ".tsx",

    # Java
    ".java",

    # C / C++
    ".c",
    ".cpp",
    ".h",
    ".hpp",

    # C#
    ".cs",

    # Go
    ".go",

    # Rust
    ".rs",

    # PHP
    ".php",

    # Web
    ".html",
    ".htm",
    ".css",
    ".scss",
    ".sass",

    # Data / configuration
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",

    # Documentation
    ".md",
    ".rst",
    ".txt",

    # Database
    ".sql",

    # XML
    ".xml",

    # Shell
    ".sh",
    ".bash",
    ".bat",
    ".ps1",
}


# Files that should not be indexed even if their extension is
# technically supported.
IGNORED_FILES = {
    ".ds_store",
    "thumbs.db",
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
}


# ============================================================
# LIMITS
# ============================================================

MAX_FILES = MAX_ZIP_FILES
MAX_EXTRACTED_REPOSITORY_SIZE = MAX_UNCOMPRESSED_BYTES


# ============================================================
# REPOSITORY ID
# ============================================================

def create_repository_id() -> str:
    """
    Create a short unique repository ID.
    """

    return uuid.uuid4().hex[:12]


# ============================================================
# ZIP VALIDATION
# ============================================================

def validate_zip_file(zip_path: str) -> None:
    """
    Validate that the uploaded file is a valid ZIP archive.
    """

    if not zipfile.is_zipfile(zip_path):
        raise ValueError(
            "Uploaded file is not a valid ZIP archive."
        )


# ============================================================
# SAFE ZIP PATH VALIDATION
# ============================================================

def is_safe_zip_path(
    extraction_root: Path,
    member_name: str,
) -> bool:
    """
    Prevent ZIP-slip/path-traversal attacks.

    A malicious ZIP could contain something like:

        ../../some_file

    which could otherwise write files outside the repository
    directory.

    This function ensures every extracted file remains inside
    the intended repository directory.
    """

    if not member_name:
        return False

    # Convert ZIP separators to the local platform separator.
    normalized_name = member_name.replace("\\", "/")

    # Reject absolute paths.
    if normalized_name.startswith("/"):
        return False

    # Reject Windows drive paths such as C:/...
    if len(normalized_name) >= 2:
        if normalized_name[1] == ":":
            return False

    # Resolve the final extraction path.
    target_path = (
        extraction_root / normalized_name
    ).resolve()

    extraction_root_resolved = (
        extraction_root.resolve()
    )

    try:
        target_path.relative_to(
            extraction_root_resolved
        )
    except ValueError:
        return False

    return True


# ============================================================
# SAFE ZIP EXTRACTION
# ============================================================

def safe_extract_zip(
    zip_path: Path,
    destination: Path,
) -> None:
    """
    Safely extract a ZIP archive with configurable limit and traversal checks.
    Rejects path traversal, excessive file count, excessive expanded size,
    and suspicious compression ratios (zip bombs).
    """
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    zip_path = Path(zip_path)

    if not zip_path.exists():
        raise FileNotFoundError(f"ZIP file does not exist: {zip_path}")

    # Check compressed archive size
    compressed_size = zip_path.stat().st_size
    if compressed_size > MAX_COMPRESSED_BYTES:
        raise ValueError(
            f"Uploaded archive size ({compressed_size / (1024 * 1024):.1f} MB) "
            f"exceeds maximum allowed compressed limit ({MAX_COMPRESSED_BYTES / (1024 * 1024):.0f} MB)."
        )

    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            members = archive.infolist()

            limit_files = min(MAX_FILES, MAX_ZIP_FILES)
            if len(members) > limit_files:
                raise ValueError(
                    f"ZIP contains too many files ({len(members)} > {limit_files})."
                )

            total_size = sum(member.file_size for member in members)
            limit_uncompressed = min(MAX_EXTRACTED_REPOSITORY_SIZE, MAX_UNCOMPRESSED_BYTES)
            if total_size > limit_uncompressed:
                raise ValueError(
                    f"Extracted repository size ({total_size / (1024 * 1024):.1f} MB) "
                    f"exceeds maximum allowed size ({limit_uncompressed / (1024 * 1024):.0f} MB)."
                )

            # Check compression ratio (zip bomb defense)
            if compressed_size > 0:
                ratio = total_size / compressed_size
                if ratio > MAX_COMPRESSION_RATIO:
                    raise ValueError(
                        f"ZIP archive has an excessively high compression ratio "
                        f"({ratio:.1f}:1 > {MAX_COMPRESSION_RATIO:.0f}:1). Potential zip bomb rejected."
                    )

            for member in members:
                # Check individual file size limit
                if member.file_size > MAX_SINGLE_FILE_SIZE:
                    raise ValueError(
                        f"File {member.filename} ({member.file_size / (1024 * 1024):.1f} MB) "
                        f"exceeds maximum allowed single-file limit ({MAX_SINGLE_FILE_SIZE / (1024 * 1024):.0f} MB)."
                    )

                # Check for path traversal attempts
                normalized_name = member.filename.replace("\\", "/")
                if normalized_name.startswith("/"):
                    raise ValueError("Unsafe ZIP path detected: absolute paths are rejected.")

                if len(normalized_name) >= 2 and normalized_name[1] == ":":
                    raise ValueError("Unsafe ZIP path detected: Windows drive paths are rejected.")

                target = (destination / member.filename).resolve()

                if target != destination and destination not in target.parents:
                    raise ValueError(f"Unsafe ZIP path detected: '{member.filename}' escapes target directory.")

            archive.extractall(destination)

    except zipfile.BadZipFile as exc:
        raise ValueError("The uploaded file is not a valid ZIP archive.") from exc


def extract_repository_zip(
    zip_path: Path,
    repository_dir: Path,
) -> None:
    """
    Extract a repository ZIP archive, unpacking any single nested ZIP archive.
    """
    zip_path = Path(zip_path)
    repository_dir = Path(repository_dir).resolve()

    if not zip_path.exists():
        raise FileNotFoundError(f"ZIP file does not exist: {zip_path}")

    try:
        safe_extract_zip(zip_path, repository_dir)

        # Handle one nested ZIP only when it is the sole extracted file.
        extracted_files = [
            path
            for path in repository_dir.rglob("*")
            if path.is_file() and path.resolve() != zip_path.resolve()
        ]

        if len(extracted_files) == 1:
            nested_zip = extracted_files[0]

            if nested_zip.suffix.lower() == ".zip":
                nested_destination = nested_zip.parent / "source"
                safe_extract_zip(nested_zip, nested_destination)

    except zipfile.BadZipFile as exc:
        raise ValueError("The uploaded file is not a valid ZIP archive") from exc


def extract_repository(
    zip_path: str,
    repository_id: str,
) -> Path:
    """
    Safely extract a repository ZIP archive.

    Features:
    - ZIP-slip protection
    - extracted-size and file-count protection
    - individual-file-size protection
    - single nested ZIP extraction
    """

    BASE_REPOSITORY_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    repository_path = (
        BASE_REPOSITORY_DIR / repository_id
    )

    # Remove an existing repository with the same ID.
    if repository_path.exists():
        shutil.rmtree(repository_path)

    repository_path.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        extract_repository_zip(
            zip_path=Path(zip_path),
            repository_dir=repository_path,
        )
        return repository_path

    except Exception:
        # Clean up partially extracted repository if extraction fails.
        if repository_path.exists():
            shutil.rmtree(
                repository_path,
                ignore_errors=True,
            )
        raise


# ============================================================
# PATH FILTERING
# ============================================================

def is_ignored_path(
    path: Path,
) -> bool:
    """
    Return True if any directory in the path is ignored.
    """

    return any(
        part in IGNORED_DIRECTORIES
        for part in path.parts
    )


# ============================================================
# FILE SUPPORT CHECK
# ============================================================

def is_supported_file(
    file_path: Path,
) -> bool:
    """
    Determine whether a file should be processed by CodeLens.
    """

    # Ignore known unwanted filenames.
    if file_path.name.lower() in IGNORED_FILES:
        return False

    # Ignore files inside ignored directories.
    if is_ignored_path(file_path):
        return False

    # Only process supported text/code extensions.
    if (
        file_path.suffix.lower()
        not in SUPPORTED_EXTENSIONS
    ):
        return False

    # Ignore extremely large individual files.
    try:
        if (
            file_path.stat().st_size
            > MAX_SINGLE_FILE_SIZE
        ):
            return False
    except OSError:
        return False

    return True



# ============================================================
# LANGUAGE SUMMARY REFERENCE IMPLEMENTATION
# ============================================================

LANGUAGE_BY_SUFFIX = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".c": "C",
    ".h": "C/C++",
    ".cpp": "C++",
    ".cs": "C#",
    ".go": "Go",
    ".rs": "Rust",
    ".php": "PHP",
    ".rb": "Ruby",
    ".swift": "Swift",
    ".kt": "Kotlin",
    ".html": "HTML",
    ".css": "CSS",
    ".sql": "SQL",
}

def summarize_languages(repository_path: Path) -> dict:
    """
    Detect programming languages from extracted source files.
    Excludes generated/vendor folders (.git, node_modules, venv, dist, build).
    """
    repository_path = Path(repository_path)
    counts = Counter()
    source_files = 0

    for path in repository_path.rglob("*"):
        if not path.is_file():
            continue

        relative = path.relative_to(repository_path)
        if any(part in IGNORED_DIRECTORIES for part in relative.parts):
            continue

        language = LANGUAGE_BY_SUFFIX.get(path.suffix.lower())
        if language:
            counts[language] += 1
            source_files += 1

    return {
        "source_file_count": source_files,
        "languages": [
            {"name": name, "file_count": count}
            for name, count in sorted(
                counts.items(), key=lambda item: item[1], reverse=True
            )
        ],
    }


# ============================================================
# SAFE ENVIRONMENT-FILE INVENTORY
# ============================================================

ENV_NAMES = {".env", ".env.example", ".env.sample", ".env.template"}

def inspect_env_files(repository_path: Path) -> list[dict]:
    """
    Detect .env and env-example files, returning filenames and variable names ONLY.
    Never exposes, logs, or returns secret values.
    """
    repository_path = Path(repository_path)
    results = []

    for path in repository_path.rglob("*"):
        if not path.is_file():
            continue
        if path.name not in ENV_NAMES and not path.name.startswith(".env."):
            continue

        relative = path.relative_to(repository_path)
        if any(part in IGNORED_DIRECTORIES for part in relative.parts):
            continue

        variable_names = []
        try:
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name = line.split("=", 1)[0].strip()
                if name and name.replace("_", "").isalnum():
                    variable_names.append(name)
        except OSError:
            continue

        results.append({
            "file": str(relative).replace("\\", "/"),
            "variable_names": sorted(set(variable_names)),
            "values_redacted": True,
        })

    results.sort(key=lambda item: item["file"])
    return results


# ============================================================
# DEPENDENCY MANIFEST PARSER
# ============================================================

def parse_dependency_manifests(repository_path: Path) -> list[dict]:
    """
    Detect available dependency manifests (requirements.txt, package.json, pyproject.toml)
    and parse declared dependencies without inventing relationships.
    """
    repository_path = Path(repository_path)
    manifests = []

    # 1. requirements.txt / requirements-*.txt
    for path in repository_path.rglob("*requirements*.txt"):
        if not path.is_file():
            continue
        relative = path.relative_to(repository_path)
        if any(part in IGNORED_DIRECTORIES for part in relative.parts):
            continue

        deps = []
        try:
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-"):
                    continue
                match = re.match(r"^([a-zA-Z0-9_.-]+)\s*([=><~].*)?$", line)
                if match:
                    pkg_name = match.group(1).strip()
                    ver = match.group(2).strip() if match.group(2) else "unspecified"
                    deps.append({"name": pkg_name, "version": ver})
        except OSError:
            pass

        if deps:
            manifests.append({
                "file": str(relative).replace("\\", "/"),
                "dependencies": deps,
            })

    # 2. package.json
    for path in repository_path.rglob("package.json"):
        if not path.is_file():
            continue
        relative = path.relative_to(repository_path)
        if any(part in IGNORED_DIRECTORIES for part in relative.parts):
            continue

        deps = []
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
            for pkg, ver in data.get("dependencies", {}).items():
                deps.append({"name": pkg, "version": str(ver)})
            for pkg, ver in data.get("devDependencies", {}).items():
                deps.append({"name": pkg, "version": str(ver)})
        except (OSError, ValueError):
            pass

        if deps:
            manifests.append({
                "file": str(relative).replace("\\", "/"),
                "dependencies": deps,
            })

    # 3. pyproject.toml
    for path in repository_path.rglob("pyproject.toml"):
        if not path.is_file():
            continue
        relative = path.relative_to(repository_path)
        if any(part in IGNORED_DIRECTORIES for part in relative.parts):
            continue

        deps = []
        try:
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                match = re.match(r'^"?([a-zA-Z0-9_.-]+)"?\s*=\s*"([^"]+)"', line)
                if match and not line.startswith("["):
                    deps.append({"name": match.group(1), "version": match.group(2)})
        except OSError:
            pass

        if deps:
            manifests.append({
                "file": str(relative).replace("\\", "/"),
                "dependencies": deps,
            })

    manifests.sort(key=lambda m: m["file"])
    return manifests

# ============================================================
# GET SUPPORTED FILES
# ============================================================

def get_supported_files(
    repository_path: Path,
) -> list[Path]:
    """
    Return all supported source/documentation files.

    Files are discovered recursively without loading their
    contents into memory.
    """

    supported_files = []

    for file_path in repository_path.rglob("*"):

        if not file_path.is_file():
            continue

        if not is_supported_file(
            file_path
        ):
            continue

        supported_files.append(
            file_path
        )

    # Sort for deterministic results.
    supported_files.sort(
        key=lambda path: str(path).lower()
    )

    return supported_files


# ============================================================
# REPOSITORY INFORMATION
# ============================================================

def get_repository_info(
    repository_path: Path,
) -> dict:
    """
    Return metadata about the repository.
    """

    files = get_supported_files(
        repository_path
    )

    extensions = {}

    for file_path in files:

        extension = (
            file_path.suffix.lower()
        )

        if extension not in extensions:
            extensions[extension] = 0

        extensions[extension] += 1

    return {
        "repository_id": repository_path.name,
        "repository_path": str(
            repository_path
        ),
        "file_count": len(files),
        "file_types": extensions,
        "files": [
            str(
                file_path.relative_to(
                    repository_path
                )
            )
            for file_path in files
        ],
        "language_summary": summarize_languages(repository_path),
        "dependency_manifests": parse_dependency_manifests(repository_path),
        "environment_files": inspect_env_files(repository_path),
    }


# ============================================================
# STREAM UPLOADED ZIP TO DISK
# ============================================================

async def stream_upload_to_disk(
    upload_file,
    destination_path: Path,
) -> None:
    """
    Stream the uploaded ZIP file directly to disk.

    This avoids:

        await upload_file.read()

    which would load the entire ZIP into memory.

    The file is copied in 1 MB chunks.
    """

    with open(
        destination_path,
        "wb",
    ) as output_file:

        while True:

            chunk = await upload_file.read(
                1024 * 1024
            )

            if not chunk:
                break

            output_file.write(
                chunk
            )


# ============================================================
# SAVE UPLOADED REPOSITORY
# ============================================================

async def save_uploaded_repository(
    upload_file,
) -> dict:
    """
    Save and process an uploaded repository ZIP.

    Pipeline:

        Upload
          ↓
        Stream ZIP to disk
          ↓
        Validate ZIP
          ↓
        Safe extraction
          ↓
        File filtering
          ↓
        Repository metadata
    """

    if not upload_file.filename:
        raise ValueError(
            "Uploaded file has no filename."
        )

    filename = (
        upload_file.filename
        .lower()
    )

    if not filename.endswith(".zip"):
        raise ValueError(
            "Only ZIP files are supported."
        )

    # --------------------------------------------------------
    # CREATE REQUIRED DIRECTORIES
    # --------------------------------------------------------

    UPLOAD_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    BASE_REPOSITORY_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # CREATE REPOSITORY ID
    # --------------------------------------------------------

    repository_id = create_repository_id()

    zip_path = (
        UPLOAD_DIR
        / f"{repository_id}.zip"
    )

    try:

        # ----------------------------------------------------
        # STREAM UPLOAD TO DISK
        # ----------------------------------------------------

        print(
            f"Saving uploaded repository: "
            f"{upload_file.filename}"
        )

        await stream_upload_to_disk(
            upload_file=upload_file,
            destination_path=zip_path,
        )

        print(
            "Repository ZIP saved successfully."
        )

        # ----------------------------------------------------
        # VALIDATE ZIP
        # ----------------------------------------------------

        validate_zip_file(
            str(zip_path)
        )

        print(
            "ZIP validation successful."
        )

        # ----------------------------------------------------
        # EXTRACT REPOSITORY
        # ----------------------------------------------------

        repository_path = extract_repository(
            zip_path=str(zip_path),
            repository_id=repository_id,
        )

        print(
            f"Repository extracted to: "
            f"{repository_path}"
        )

        # ----------------------------------------------------
        # GET REPOSITORY INFORMATION
        # ----------------------------------------------------

        repository_info = get_repository_info(
            repository_path
        )

        print(
            "Repository information collected:"
        )

        print(
            f"Files: "
            f"{repository_info['file_count']}"
        )

        print(
            f"File types: "
            f"{repository_info['file_types']}"
        )

        return repository_info

    finally:

        # ----------------------------------------------------
        # REMOVE TEMPORARY ZIP
        # ----------------------------------------------------

        if zip_path.exists():

            try:
                zip_path.unlink()

            except OSError:
                pass