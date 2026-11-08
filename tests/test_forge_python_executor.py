import pytest

from app.forge.python_executor import (
    ForgeCandidateValidationError,
    ForgePythonCandidateExecutor,
)


def test_validate_files_accepts_valid_nested_paths():
    files = ForgePythonCandidateExecutor._validate_files({
        "src/module.py": "print('hello')",
        "docs/README.md": "Hello",
    })

    assert files == {
        "src/module.py": "print('hello')",
        "docs/README.md": "Hello",
    }


@pytest.mark.parametrize(
    "raw_path",
    [
        "folder//file.py",
        "folder/./file.py",
        "folder/../file.py",
        "folder/",
        "/file.py",
        r"folder\\file.py",
        "folder/" + chr(0) + "file.py",
        "folder/" + chr(10) + "file.py",
        "folder/" + chr(127) + "file.py",
    ],
)
def test_validate_files_rejects_malformed_paths(raw_path):
    with pytest.raises(ForgeCandidateValidationError):
        ForgePythonCandidateExecutor._validate_files({raw_path: "content"})


def test_validate_files_rejects_unsupported_suffix():
    with pytest.raises(ForgeCandidateValidationError):
        ForgePythonCandidateExecutor._validate_files({"script.exe": "content"})
