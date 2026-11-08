import pytest

from app.forge.languages import (
    ALLOWED_SUFFIXES,
    get_language,
    list_languages,
)
from app.forge.python_executor import ForgePythonCandidateExecutor
from app.forge.verification import build_candidate_verification_report


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("py", "python"),
        ("Python", "python"),
        ("js", "javascript"),
        ("node", "javascript"),
        ("ts", "typescript"),
        ("c++", "cpp"),
        ("c#", "csharp"),
        ("golang", "go"),
        ("rs", "rust"),
    ],
)
def test_language_aliases_resolve_to_canonical_ids(value, expected):
    assert get_language(value).language_id == expected


def test_language_registry_has_unique_ids_and_suffixes():
    languages = list_languages()
    ids = [language.language_id for language in languages]
    suffixes = [
        suffix
        for language in languages
        for suffix in language.suffixes
    ]

    assert len(ids) == len(set(ids))
    assert len(suffixes) == len(set(suffixes))
    assert set(suffixes).issubset(ALLOWED_SUFFIXES)


@pytest.mark.parametrize(
    "language",
    [
        "javascript",
        "typescript",
        "java",
        "c",
        "cpp",
        "csharp",
        "go",
        "rust",
        "php",
        "ruby",
        "swift",
        "kotlin",
        "dart",
        "sql",
    ],
)
def test_unconfigured_source_languages_remain_inconclusive(language):
    suffix = get_language(language).suffixes[0]
    checks = ForgePythonCandidateExecutor._static_checks(
        {f"src/example{suffix}": "candidate source"}
    )

    assert len(checks) == 1
    assert checks[0]["status"] == "inconclusive"
    assert checks[0]["passed"] is False


def test_inconclusive_check_makes_candidate_report_inconclusive():
    files = {
        "src/main.rs": "fn main() {}",
        "README.md": "Candidate",
    }
    checks = ForgePythonCandidateExecutor._static_checks(files)

    report = build_candidate_verification_report(files, checks)

    assert report["static_analysis"]["status"] == "inconclusive"
    assert report["readiness"]["candidate_validation"] == "inconclusive"
    assert report["readiness"]["production_ready"] is False
    assert report["readiness"]["release_authorized"] is False


def test_python_syntax_error_is_a_failure():
    checks = ForgePythonCandidateExecutor._static_checks(
        {"src/main.py": "def broken(:\n    pass"}
    )

    assert checks[0]["status"] == "fail"
    assert checks[0]["passed"] is False


def test_html_is_tokenized_but_not_claimed_as_browser_verified():
    checks = ForgePythonCandidateExecutor._static_checks(
        {"index.html": "<html><body>Hello</body></html>"}
    )

    assert checks[0]["status"] == "pass"
    assert "browser rendering was not tested" in checks[0]["message"]


def test_unknown_language_is_rejected():
    with pytest.raises(ValueError, match="Unsupported Forge language"):
        get_language("brainfuck")


def test_empty_language_is_rejected():
    with pytest.raises(ValueError, match="non-empty"):
        get_language("  ")
