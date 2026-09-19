import dataclasses

import pytest

from app.identity import (
    AuthenticatedPrincipal,
    BusinessMembership,
    TenantContext,
    User,
    UserRole,
)


def principal(
    *,
    user_id="user-1",
    business_id="business-1",
    role=UserRole.OWNER,
    session_id="session-1",
):
    return AuthenticatedPrincipal(
        user_id=user_id,
        business_id=business_id,
        role=role,
        session_id=session_id,
    )


def context(**kwargs):
    p = principal(**kwargs)
    return TenantContext(
        business_id=p.business_id,
        principal=p,
    )


def membership(
    *,
    user_id="user-1",
    business_id="business-1",
    role=UserRole.OWNER,
):
    return BusinessMembership(
        user_id=user_id,
        business_id=business_id,
        role=role,
    )


# ---------------------------------------------------------------------------
# Cross-tenant attacks
# ---------------------------------------------------------------------------


def test_attack_cross_tenant_principal_into_existing_context_is_rejected():
    legitimate = principal(
        user_id="user-1",
        business_id="business-1",
    )

    with pytest.raises(ValueError):
        TenantContext(
            business_id="business-2",
            principal=legitimate,
        )


def test_attack_cross_tenant_membership_replay_is_rejected():
    ctx = context()

    with pytest.raises(PermissionError):
        ctx.require_membership(
            membership(business_id="business-2")
        )


def test_attack_cross_tenant_membership_with_different_user_is_rejected():
    ctx = context()

    with pytest.raises(PermissionError):
        ctx.require_membership(
            membership(
                user_id="attacker",
                business_id="business-2",
            )
        )


def test_attack_cross_tenant_principal_cannot_be_reinterpreted():
    attacker = principal(
        user_id="attacker",
        business_id="business-2",
        role=UserRole.OWNER,
    )

    with pytest.raises(ValueError):
        TenantContext(
            business_id="business-1",
            principal=attacker,
        )


# ---------------------------------------------------------------------------
# User substitution attacks
# ---------------------------------------------------------------------------


def test_attack_user_substitution_is_rejected():
    ctx = context()

    with pytest.raises(PermissionError):
        ctx.require_membership(
            membership(user_id="attacker")
        )


def test_attack_same_tenant_different_user_cannot_use_owner_membership():
    ctx = context()

    with pytest.raises(PermissionError):
        ctx.require_membership(
            membership(
                user_id="user-2",
                business_id="business-1",
                role=UserRole.OWNER,
            )
        )


# ---------------------------------------------------------------------------
# Role escalation attacks
# ---------------------------------------------------------------------------


def test_attack_member_cannot_reuse_owner_membership():
    ctx = TenantContext(
        business_id="business-1",
        principal=principal(role=UserRole.MEMBER),
    )

    with pytest.raises(PermissionError):
        ctx.require_membership(
            membership(role=UserRole.OWNER)
        )


def test_attack_admin_cannot_reuse_owner_membership():
    ctx = TenantContext(
        business_id="business-1",
        principal=principal(role=UserRole.ADMIN),
    )

    with pytest.raises(PermissionError):
        ctx.require_membership(
            membership(role=UserRole.OWNER)
        )


def test_attack_owner_cannot_present_admin_membership_as_owner():
    ctx = context()

    with pytest.raises(PermissionError):
        ctx.require_membership(
            membership(role=UserRole.ADMIN)
        )


def test_attack_string_role_cannot_replace_enum_role():
    with pytest.raises(TypeError):
        AuthenticatedPrincipal(
            user_id="user-1",
            business_id="business-1",
            role="owner",
            session_id="session-1",
        )


# ---------------------------------------------------------------------------
# Type confusion / object substitution
# ---------------------------------------------------------------------------


def test_attack_fake_membership_object_is_rejected():
    ctx = context()

    class FakeMembership:
        user_id = "user-1"
        business_id = "business-1"
        role = UserRole.OWNER

    with pytest.raises(TypeError):
        ctx.require_membership(FakeMembership())


def test_attack_fake_principal_object_is_rejected():
    class FakePrincipal:
        business_id = "business-1"

    with pytest.raises(TypeError):
        TenantContext(
            business_id="business-1",
            principal=FakePrincipal(),
        )


def test_attack_string_membership_is_rejected():
    ctx = context()

    with pytest.raises(TypeError):
        ctx.require_membership("business-1")


# ---------------------------------------------------------------------------
# Invalid identifier attacks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    ["user_id", "business_id", "session_id"],
)
def test_attack_empty_principal_identifiers_are_rejected(field):
    values = {
        "user_id": "user-1",
        "business_id": "business-1",
        "role": UserRole.OWNER,
        "session_id": "session-1",
    }
    values[field] = ""

    with pytest.raises(ValueError):
        AuthenticatedPrincipal(**values)


@pytest.mark.parametrize(
    "field",
    ["user_id", "business_id", "session_id"],
)
def test_attack_whitespace_principal_identifiers_are_rejected(field):
    values = {
        "user_id": "user-1",
        "business_id": "business-1",
        "role": UserRole.OWNER,
        "session_id": "session-1",
    }
    values[field] = "   "

    with pytest.raises(ValueError):
        AuthenticatedPrincipal(**values)


def test_attack_empty_tenant_identifier_is_rejected():
    with pytest.raises(ValueError):
        TenantContext(
            business_id="",
            principal=principal(),
        )


# ---------------------------------------------------------------------------
# Immutability attacks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("user_id", "attacker"),
        ("business_id", "business-2"),
        ("role", UserRole.ADMIN),
        ("session_id", "attacker-session"),
    ],
)
def test_attack_principal_cannot_be_mutated(field, value):
    p = principal()

    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(p, field, value)


def test_attack_membership_cannot_be_mutated():
    m = membership()

    with pytest.raises(dataclasses.FrozenInstanceError):
        m.business_id = "business-2"


def test_attack_tenant_context_cannot_be_mutated():
    ctx = context()

    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.business_id = "business-2"


# ---------------------------------------------------------------------------
# Secret injection attacks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "secret_field",
    [
        "password",
        "password_hash",
        "access_token",
        "refresh_token",
        "provider_token",
        "api_key",
        "secret",
        "client_secret",
    ],
)
def test_attack_identity_models_do_not_expose_secret_fields(secret_field):
    user = User(
        user_id="user-1",
        display_name="Owner",
        email="owner@example.com",
    )

    p = principal()

    assert not hasattr(user, secret_field)
    assert not hasattr(p, secret_field)


# ---------------------------------------------------------------------------
# Serialization / structural attacks
# ---------------------------------------------------------------------------


def test_attack_principal_has_only_expected_fields():
    fields = {
        field.name
        for field in dataclasses.fields(AuthenticatedPrincipal)
    }

    assert fields == {
        "user_id",
        "business_id",
        "role",
        "session_id",
        "scope",
    }


def test_attack_membership_has_only_expected_fields():
    fields = {
        field.name
        for field in dataclasses.fields(BusinessMembership)
    }

    assert fields == {
        "user_id",
        "business_id",
        "role",
    }


def test_attack_user_has_only_expected_fields():
    fields = {
        field.name
        for field in dataclasses.fields(User)
    }

    assert fields == {
        "user_id",
        "display_name",
        "email",
    }


# ---------------------------------------------------------------------------
# Tenant boundary invariant
# ---------------------------------------------------------------------------


def test_attack_membership_must_match_all_three_authorization_dimensions():
    ctx = context()

    attack_cases = [
        membership(
            user_id="attacker",
            business_id="business-1",
            role=UserRole.OWNER,
        ),
        membership(
            user_id="user-1",
            business_id="business-2",
            role=UserRole.OWNER,
        ),
        membership(
            user_id="user-1",
            business_id="business-1",
            role=UserRole.ADMIN,
        ),
    ]

    for attack in attack_cases:
        with pytest.raises(PermissionError):
            ctx.require_membership(attack)
