"""Trusted, declarative toolchain registry for Forge.

This module describes approved toolchain adapters. It does not execute code,
invoke a shell, install dependencies, or enable local generated-code execution.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.forge.languages import get_language, list_languages


@dataclass(frozen=True)
class ToolchainSpec:
    language_id: str
    runner_profile: str
    static_adapter: str | None
    build_adapter: str | None
    test_adapter: str | None
    adapter_status: str


_SPECS = (
    ToolchainSpec("python", "python-isolated", "python_ast", "python_compile", "python_tests", "static_only"),
    ToolchainSpec("javascript", "node-isolated", "node_check", "node_build", "node_tests", "planned"),
    ToolchainSpec("typescript", "node-typescript-isolated", "tsc_check", "tsc_build", "node_tests", "planned"),
    ToolchainSpec("java", "jvm-isolated", "javac_check", "javac_build", "junit_tests", "planned"),
    ToolchainSpec("c", "native-c-isolated", "clang_check", "clang_build", "c_test_harness", "planned"),
    ToolchainSpec("cpp", "native-cpp-isolated", "clang_cpp_check", "clang_cpp_build", "cpp_test_harness", "planned"),
    ToolchainSpec("csharp", "dotnet-isolated", "dotnet_check", "dotnet_build", "dotnet_tests", "planned"),
    ToolchainSpec("go", "go-isolated", "go_check", "go_build", "go_tests", "planned"),
    ToolchainSpec("rust", "rust-isolated", "rust_check", "cargo_build", "cargo_tests", "planned"),
    ToolchainSpec("php", "php-isolated", "php_lint", "composer_build", "php_tests", "planned"),
    ToolchainSpec("ruby", "ruby-isolated", "ruby_syntax", "bundler_build", "ruby_tests", "planned"),
    ToolchainSpec("swift", "swift-isolated", "swift_check", "swift_build", "swift_tests", "planned"),
    ToolchainSpec("kotlin", "kotlin-isolated", "kotlin_check", "kotlin_build", "kotlin_tests", "planned"),
    ToolchainSpec("dart", "dart-isolated", "dart_analyze", "dart_build", "dart_tests", "planned"),
    ToolchainSpec("sql", "sql-dialect-isolated", None, None, "sql_tests", "dialect_required"),
    ToolchainSpec("html", "browser-isolated", "html_tokenizer", "browser_build", "browser_tests", "tokenizer_only"),
    ToolchainSpec("css", "browser-isolated", "css_lint", "browser_build", "browser_tests", "planned"),
)

_BY_LANGUAGE = {item.language_id: item for item in _SPECS}

# This remains false until a separately secured isolated runner is implemented.
GENERATED_CODE_EXECUTION_ENABLED = False


def get_toolchain(language: str) -> ToolchainSpec:
    canonical = get_language(language).language_id
    try:
        return _BY_LANGUAGE[canonical]
    except KeyError as exc:
        raise ValueError(
            f"No trusted toolchain profile exists for {canonical!r}."
        ) from exc


def list_toolchains() -> tuple[ToolchainSpec, ...]:
    return _SPECS


def build_toolchain_plan(language: str) -> dict:
    """Describe work Forge could request; never execute the plan."""
    spec = get_toolchain(language)
    adapters = {
        "static": spec.static_adapter,
        "build": spec.build_adapter,
        "tests": spec.test_adapter,
    }
    return {
        "language": spec.language_id,
        "runner_profile": spec.runner_profile,
        "adapter_status": spec.adapter_status,
        "adapters": adapters,
        "execution_enabled": GENERATED_CODE_EXECUTION_ENABLED,
        "requires_isolated_runner": True,
        "execution_status": "blocked_no_isolated_runner",
        "shell_execution_allowed": False,
        "dependency_installation_allowed": False,
    }


def validate_toolchain_registry() -> None:
    """Fail closed if a language is missing or duplicated."""
    language_ids = [item.language_id for item in list_languages()]
    toolchain_ids = [item.language_id for item in _SPECS]

    if len(toolchain_ids) != len(set(toolchain_ids)):
        raise ValueError("Duplicate Forge toolchain language profile.")
    if set(language_ids) != set(toolchain_ids):
        missing = sorted(set(language_ids) - set(toolchain_ids))
        extra = sorted(set(toolchain_ids) - set(language_ids))
        raise ValueError(
            f"Forge toolchain registry mismatch; missing={missing}, extra={extra}."
        )


validate_toolchain_registry()
