import io
import sys
import zipfile
from pathlib import Path
import pytest

# Ensure backend root is on sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from repository.manager import (
    safe_extract_zip,
    extract_repository_zip,
    MAX_FILES,
    MAX_UNCOMPRESSED_BYTES,
)


def test_normal_zip_extraction(tmp_path: Path):
    """
    Test extraction of a standard ZIP archive containing valid files.
    """
    zip_path = tmp_path / "valid.zip"
    dest_path = tmp_path / "extracted_normal"

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("main.py", "print('hello world')")
        zf.writestr("subdir/helper.py", "def add(a, b): return a + b")

    safe_extract_zip(zip_path, dest_path)

    assert (dest_path / "main.py").exists()
    assert (dest_path / "main.py").read_text() == "print('hello world')"
    assert (dest_path / "subdir" / "helper.py").exists()


def test_nested_zip_extraction(tmp_path: Path):
    """
    Test that when an archive contains a single nested ZIP and no other files,
    the nested ZIP is automatically extracted into destination/source.
    """
    inner_zip_bytes = io.BytesIO()
    with zipfile.ZipFile(inner_zip_bytes, "w") as inner_zf:
        inner_zf.writestr("app.py", "print('inside nested')")
        inner_zf.writestr("config.json", '{"key": "value"}')

    outer_zip_path = tmp_path / "outer.zip"
    dest_path = tmp_path / "extracted_nested"

    with zipfile.ZipFile(outer_zip_path, "w") as outer_zf:
        outer_zf.writestr("project-repo.zip", inner_zip_bytes.getvalue())

    extract_repository_zip(outer_zip_path, dest_path)

    nested_target = dest_path / "source" / "app.py"
    assert nested_target.exists(), f"Expected {nested_target} to exist after extracting nested zip"
    assert nested_target.read_text() == "print('inside nested')"


def test_missing_zip_raises_error(tmp_path: Path):
    """
    Test that a non-existent ZIP file raises FileNotFoundError.
    """
    missing_path = tmp_path / "does_not_exist.zip"
    dest_path = tmp_path / "extracted_missing"

    with pytest.raises(FileNotFoundError):
        safe_extract_zip(missing_path, dest_path)


def test_invalid_zip_raises_value_error(tmp_path: Path):
    """
    Test that corrupted/invalid archive data raises a descriptive ValueError.
    """
    invalid_path = tmp_path / "corrupt.zip"
    invalid_path.write_bytes(b"NOT_A_VALID_ZIP_HEADER_DATA")
    dest_path = tmp_path / "extracted_corrupt"

    with pytest.raises(ValueError, match="not a valid ZIP archive"):
        safe_extract_zip(invalid_path, dest_path)


def test_path_traversal_rejection(tmp_path: Path):
    """
    Test that an archive containing relative path traversal (Zip Slip)
    is rejected and raises ValueError without extracting malicious files.
    """
    traversal_zip = tmp_path / "traversal.zip"
    dest_path = tmp_path / "safe_dest"
    dest_path.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(traversal_zip, "w") as zf:
        zf.writestr("../evil.txt", "MALICIOUS PAYLOAD")

    with pytest.raises(ValueError, match="Unsafe ZIP path detected"):
        safe_extract_zip(traversal_zip, dest_path)

    outside_file = tmp_path / "evil.txt"
    assert not outside_file.exists(), "Malicious file was extracted outside target directory!"


def test_max_file_count_limit(tmp_path: Path, monkeypatch):
    """
    Test that exceeding MAX_FILES raises ValueError.
    """
    import repository.manager as mgr
    monkeypatch.setattr(mgr, "MAX_FILES", 3)

    zip_path = tmp_path / "too_many_files.zip"
    dest_path = tmp_path / "dest_count"

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("f1.txt", "1")
        zf.writestr("f2.txt", "2")
        zf.writestr("f3.txt", "3")
        zf.writestr("f4.txt", "4")

    with pytest.raises(ValueError, match="too many files"):
        mgr.safe_extract_zip(zip_path, dest_path)
