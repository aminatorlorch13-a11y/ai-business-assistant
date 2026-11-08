import pytest

from app.forge.languages import list_languages
from app.forge.toolchains import (
    GENERATED_CODE_EXECUTION_ENABLED,
    build_toolchain_plan,
    get_toolchain,
    list_toolchains,
    validate_toolchain_registry,
)


def test_every_registered_language_has_one_toolchain_profile():
    validate_toolchain_registry()
    assert {
        item.language_id for item in list_toolchains()
    } == {
        item.language_id for item in list_languages()
    }


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [
        ("py", "python"),
        ("js", "javascript"),
        ("ts", "typescript"),
        ("c++", "cpp"),
        ("c#", "csharp"),
        ("golang", "go"),
        ("rs", "rust"),
    ],
)
def test_toolchain_lookup_accepts_language_aliases(alias, canonical):
    assert get_toolchain(alias).language_id == canonical


@pytest.mark.parametrize(
    "language",
    [item.language_id for item in list_languages()],
)
def test_all_toolchain_plans_fail_closed(language):
    plan = build_toolchain_plan(language)

    assert plan["execution_enabled"] is False
    assert plan["requires_isolated_runner"] is True
    assert plan["execution_status"] == "blocked_no_isolated_runner"
    assert plan["shell_execution_allowed"] is False
    assert plan["dependency_installation_allowed"] is False


def test_global_generated_code_execution_is_disabled():
    assert GENERATED_CODE_EXECUTION_ENABLED is False


def test_python_profile_identifies_existing_static_checker():
    spec = get_toolchain("python")
    assert spec.static_adapter == "python_ast"
    assert spec.adapter_status == "static_only"


def test_html_profile_does_not_claim_browser_verification():
    spec = get_toolchain("html")
    assert spec.static_adapter == "html_tokenizer"
    assert spec.adapter_status == "tokenizer_only"


def test_sql_profile_requires_a_dialect_aware_adapter():
    spec = get_toolchain("sql")
    assert spec.adapter_status == "dialect_required"
    assert spec.static_adapter is None
