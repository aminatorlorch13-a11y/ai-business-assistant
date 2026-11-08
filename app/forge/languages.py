"""Canonical language registry for Forge candidate projects."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ForgeLanguage:
    language_id: str
    display_name: str
    suffixes: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    static_checker: str | None = None


_LANGUAGES = (
    ForgeLanguage("python", "Python", (".py",), ("py",), "python"),
    ForgeLanguage("javascript", "JavaScript", (".js", ".jsx", ".mjs", ".cjs"), ("js", "node")),
    ForgeLanguage("typescript", "TypeScript", (".ts", ".tsx"), ("ts",)),
    ForgeLanguage("java", "Java", (".java",)),
    ForgeLanguage("c", "C", (".c", ".h")),
    ForgeLanguage("cpp", "C++", (".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx"), ("c++", "cplusplus")),
    ForgeLanguage("csharp", "C#", (".cs",), ("c#", "c-sharp")),
    ForgeLanguage("go", "Go", (".go",), ("golang",)),
    ForgeLanguage("rust", "Rust", (".rs",), ("rs",)),
    ForgeLanguage("php", "PHP", (".php",)),
    ForgeLanguage("ruby", "Ruby", (".rb",), ("rb",)),
    ForgeLanguage("swift", "Swift", (".swift",)),
    ForgeLanguage("kotlin", "Kotlin", (".kt", ".kts"), ("kt",)),
    ForgeLanguage("dart", "Dart", (".dart",)),
    ForgeLanguage("sql", "SQL", (".sql",)),
    ForgeLanguage("html", "HTML", (".html", ".htm")),
    ForgeLanguage("css", "CSS", (".css", ".scss")),
)

SHARED_SUFFIXES = frozenset({
    ".md", ".txt", ".json", ".toml", ".yaml", ".yml", ".xml",
})
LANGUAGE_SUFFIXES = frozenset(
    suffix for item in _LANGUAGES for suffix in item.suffixes
)
ALLOWED_SUFFIXES = LANGUAGE_SUFFIXES | SHARED_SUFFIXES

_BY_ID = {item.language_id: item for item in _LANGUAGES}
_BY_ALIAS = {
    alias.casefold(): item.language_id
    for item in _LANGUAGES
    for alias in (item.language_id, item.display_name, *item.aliases)
}


def get_language(value: str) -> ForgeLanguage:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Forge language must be a non-empty string.")
    language_id = _BY_ALIAS.get(value.strip().casefold())
    if language_id is None:
        raise ValueError(f"Unsupported Forge language: {value!r}.")
    return _BY_ID[language_id]


def list_languages() -> tuple[ForgeLanguage, ...]:
    return _LANGUAGES
