import ast
import hashlib
from pathlib import Path


# ============================================================
# CONFIGURATION
# ============================================================

TEXT_CHUNK_SIZE = 80
TEXT_CHUNK_OVERLAP = 15

# Maximum file size that will be loaded into memory for
# AST-based Python analysis.
MAX_AST_FILE_SIZE_MB = 5
MAX_AST_FILE_SIZE_BYTES = (
    MAX_AST_FILE_SIZE_MB * 1024 * 1024
)


# ============================================================
# LANGUAGE DETECTION
# ============================================================

LANGUAGE_MAP = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript React",
    ".ts": "TypeScript",
    ".tsx": "TypeScript React",
    ".java": "Java",
    ".c": "C",
    ".cpp": "C++",
    ".h": "C/C++ Header",
    ".hpp": "C++ Header",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".md": "Markdown",
    ".txt": "Text",
    ".sql": "SQL",
    ".xml": "XML",
}


# ============================================================
# LANGUAGE
# ============================================================

def get_language(file_path: Path) -> str:
    """Return the programming language based on file extension."""

    return LANGUAGE_MAP.get(
        file_path.suffix.lower(),
        "Unknown"
    )


# ============================================================
# CHUNK ID
# ============================================================

def create_chunk_id(
    repository_id: str,
    file_path: str,
    start_line: int,
    end_line: int,
    name: str,
) -> str:
    """
    Create a deterministic ID for a chunk.

    Deterministic IDs are important because the same chunk
    should receive the same identity during re-indexing.
    """

    raw_value = (
        f"{repository_id}|"
        f"{file_path}|"
        f"{start_line}|"
        f"{end_line}|"
        f"{name}"
    )

    digest = hashlib.sha256(
        raw_value.encode("utf-8")
    ).hexdigest()[:16]

    return (
        f"{repository_id}_chunk_{digest}"
    )


# ============================================================
# SAFE FILE READING
# ============================================================

def read_file(file_path: Path) -> str:
    """
    Read a source file safely.

    UTF-8 is preferred. Invalid characters are ignored so that
    one malformed character does not stop repository indexing.
    """

    try:
        return file_path.read_text(
            encoding="utf-8",
            errors="ignore"
        )

    except (
        OSError,
        UnicodeError
    ):
        return ""


# ============================================================
# FILE SIZE
# ============================================================

def get_file_size(
    file_path: Path
) -> int:
    """Return file size safely."""

    try:
        return file_path.stat().st_size

    except OSError:
        return 0


# ============================================================
# PYTHON CHUNKING
# ============================================================

def create_python_chunks(
    content: str,
    file_path: str,
    repository_id: str
) -> list[dict]:
    """
    Create code-aware chunks from a Python file.

    Classes and top-level functions are preserved as
    meaningful code units.
    """

    chunks = []

    try:
        tree = ast.parse(
            content
        )

    except (
        SyntaxError,
        ValueError,
        TypeError,
        MemoryError
    ):
        return create_text_chunks(
            content,
            file_path,
            repository_id,
            "Python"
        )

    lines = content.splitlines()

    # --------------------------------------------------------
    # Find meaningful top-level Python constructs
    # --------------------------------------------------------

    nodes = []

    for node in tree.body:

        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef,
            )
        ):
            nodes.append(node)

    # --------------------------------------------------------
    # Create one chunk per meaningful construct
    # --------------------------------------------------------

    for node in nodes:

        start_line = node.lineno

        # Include decorators in the chunk.
        if getattr(
            node,
            "decorator_list",
            None
        ):

            decorator_lines = [
                decorator.lineno
                for decorator
                in node.decorator_list
            ]

            if decorator_lines:
                start_line = min(
                    start_line,
                    min(decorator_lines)
                )

        end_line = getattr(
            node,
            "end_lineno",
            start_line
        )

        code = "\n".join(
            lines[
                start_line - 1:
                end_line
            ]
        )

        if not code.strip():
            continue

        # ----------------------------------------------------
        # Determine chunk type
        # ----------------------------------------------------

        if isinstance(
            node,
            ast.ClassDef
        ):
            chunk_type = "class"

        elif isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            )
        ):
            chunk_type = "function"

        else:
            chunk_type = "code"

        name = getattr(
            node,
            "name",
            "unknown"
        )

        chunk_id = create_chunk_id(
            repository_id=repository_id,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            name=name
        )

        chunks.append(
            {
                "chunk_id": chunk_id,
                "content": code,
                "metadata": {
                    "repository_id": repository_id,
                    "file_path": file_path,
                    "language": "Python",
                    "chunk_type": chunk_type,
                    "name": name,
                    "start_line": start_line,
                    "end_line": end_line,
                },
            }
        )

    # --------------------------------------------------------
    # If no meaningful AST nodes were found, fall back to
    # regular text chunking.
    # --------------------------------------------------------

    if not chunks and content.strip():

        return create_text_chunks(
            content,
            file_path,
            repository_id,
            "Python"
        )

    return chunks


# ============================================================
# TEXT CHUNKING
# ============================================================

def create_text_chunks(
    content: str,
    file_path: str,
    repository_id: str,
    language: str
) -> list[dict]:
    """
    Create overlapping line-based chunks.

    Used for:
    - JavaScript
    - TypeScript
    - Java
    - C/C++
    - HTML
    - CSS
    - JSON
    - YAML
    - Markdown
    - SQL
    - XML
    - Python fallback
    """

    lines = content.splitlines()

    if not lines:
        return []

    chunks = []

    start = 0
    chunk_number = 1

    while start < len(lines):

        end = min(
            start + TEXT_CHUNK_SIZE,
            len(lines)
        )

        chunk_lines = lines[
            start:end
        ]

        code = "\n".join(
            chunk_lines
        )

        if code.strip():

            name = (
                f"chunk_{chunk_number}"
            )

            chunk_id = create_chunk_id(
                repository_id=repository_id,
                file_path=file_path,
                start_line=start + 1,
                end_line=end,
                name=name
            )

            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "content": code,
                    "metadata": {
                        "repository_id": repository_id,
                        "file_path": file_path,
                        "language": language,
                        "chunk_type": "text_block",
                        "name": name,
                        "start_line": start + 1,
                        "end_line": end,
                    },
                }
            )

        if end >= len(lines):
            break

        start = (
            end -
            TEXT_CHUNK_OVERLAP
        )

        chunk_number += 1

    return chunks


# ============================================================
# LARGE FILE CHUNKING
# ============================================================

def create_large_file_chunks(
    file_path: Path,
    relative_path: str,
    repository_id: str,
    language: str
) -> list[dict]:
    """
    Process a large file without using AST parsing.

    The file is read line-by-line and converted into
    overlapping chunks.
    """

    chunks = []

    try:

        with file_path.open(
            "r",
            encoding="utf-8",
            errors="ignore"
        ) as file:

            buffer = []
            start_line = 1
            current_line = 0
            chunk_number = 1

            for line in file:

                current_line += 1

                buffer.append(
                    line.rstrip("\n")
                )

                if len(buffer) >= TEXT_CHUNK_SIZE:

                    end_line = current_line

                    code = "\n".join(
                        buffer
                    )

                    if code.strip():

                        name = (
                            f"chunk_{chunk_number}"
                        )

                        chunk_id = (
                            create_chunk_id(
                                repository_id,
                                relative_path,
                                start_line,
                                end_line,
                                name
                            )
                        )

                        chunks.append(
                            {
                                "chunk_id": chunk_id,
                                "content": code,
                                "metadata": {
                                    "repository_id": repository_id,
                                    "file_path": relative_path,
                                    "language": language,
                                    "chunk_type": "large_file_block",
                                    "name": name,
                                    "start_line": start_line,
                                    "end_line": end_line,
                                },
                            }
                        )

                    # ----------------------------------------
                    # Preserve overlap
                    # ----------------------------------------

                    overlap = buffer[
                        -TEXT_CHUNK_OVERLAP:
                    ]

                    start_line = (
                        current_line -
                        len(overlap) +
                        1
                    )

                    buffer = overlap

                    chunk_number += 1

            # ------------------------------------------------
            # Remaining lines
            # ------------------------------------------------

            if buffer:

                end_line = current_line

                code = "\n".join(
                    buffer
                )

                if code.strip():

                    name = (
                        f"chunk_{chunk_number}"
                    )

                    chunk_id = (
                        create_chunk_id(
                            repository_id,
                            relative_path,
                            start_line,
                            end_line,
                            name
                        )
                    )

                    chunks.append(
                        {
                            "chunk_id": chunk_id,
                            "content": code,
                            "metadata": {
                                "repository_id": repository_id,
                                "file_path": relative_path,
                                "language": language,
                                "chunk_type": "large_file_block",
                                "name": name,
                                "start_line": start_line,
                                "end_line": end_line,
                            },
                        }
                    )

    except (
        OSError,
        UnicodeError
    ):
        return []

    return chunks


# ============================================================
# CHUNK ONE FILE
# ============================================================

def chunk_file(
    file_path: Path,
    repository_root: Path,
    repository_id: str
) -> list[dict]:
    """
    Chunk one repository file.

    Small Python files use AST-aware chunking.

    Large files use incremental line-based chunking.
    """

    try:
        relative_path = str(
            file_path.relative_to(
                repository_root
            )
        )

    except ValueError:
        return []

    language = get_language(
        file_path
    )

    file_size = get_file_size(
        file_path
    )

    if file_size == 0:
        return []

    lower_name = file_path.name.lower()
    if (
        lower_name in {
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
            "poetry.lock",
            "cargo.lock",
            "composer.lock",
        }
        or lower_name.endswith(".min.js")
        or lower_name.endswith(".min.css")
        or lower_name.endswith(".bundle.js")
        or lower_name.endswith(".map")
    ):
        return []

    # --------------------------------------------------------
    # Large-file handling
    # --------------------------------------------------------

    if file_size > MAX_AST_FILE_SIZE_BYTES:

        return create_large_file_chunks(
            file_path=file_path,
            relative_path=relative_path,
            repository_id=repository_id,
            language=language
        )

    # --------------------------------------------------------
    # Normal file processing
    # --------------------------------------------------------

    content = read_file(
        file_path
    )

    if not content.strip():
        return []

    # --------------------------------------------------------
    # Python
    # --------------------------------------------------------

    if file_path.suffix.lower() == ".py":

        return create_python_chunks(
            content=content,
            file_path=relative_path,
            repository_id=repository_id
        )

    # --------------------------------------------------------
    # Other supported files
    # --------------------------------------------------------

    return create_text_chunks(
        content=content,
        file_path=relative_path,
        repository_id=repository_id,
        language=language
    )


# ============================================================
# CHUNK REPOSITORY
# ============================================================

def iter_chunks_for_files(
    repository_path: Path,
    repository_id: str,
    files: list[Path]
):
    """
    Generator that yields chunks file by file to avoid loading all
    repository chunks into memory simultaneously.
    """
    for file_path in files:
        file_chunks = chunk_file(
            file_path=file_path,
            repository_root=repository_path,
            repository_id=repository_id
        )
        for chunk in file_chunks:
            yield chunk


def chunk_repository(
    repository_path: Path,
    repository_id: str,
    files: list[Path]
) -> list[dict]:
    """
    Create chunks for all supported repository files.
    Preserves list return type for existing callers and backward compatibility.
    """
    return list(
        iter_chunks_for_files(
            repository_path=repository_path,
            repository_id=repository_id,
            files=files
        )
    )