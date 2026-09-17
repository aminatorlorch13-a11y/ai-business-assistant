import pytest

from app.identity import (
    AuthenticatedPrincipal,
    BusinessMembership,
    TenantContext,
    User,
    UserRole,
)


def make_principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id="user-1",
        business_id="business-1",
        role=UserRole.OWNER,
        session_id="session-1",
    )


def test_user_contains_identity_but_no_authentication_secret_fields():
    user = User(
        user_id="user-1",
        display_name="Owner",
        email="owner@example.com",
    )

    assert user.user_id == "user-1"
    assert not hasattr(user, "password")
    assert not hasattr(user, "password_hash")
    assert not hasattr(user, "access_token")
    assert not hasattr(user, "refresh_token")


def test_membership_binds_user_to_one_business_and_role():
    membership = BusinessMembership(
        user_id="user-1",
        business_id="business-1",
        role=UserRole.OWNER,
    )

    assert membership.role is UserRole.OWNER


def test_principal_is_tenant_bound():
    principal = make_principal()
    context = TenantContext(
        business_id="business-1",
        principal=principal,
    )

    assert context.business_id == "business-1"
    assert context.principal is principal


def test_principal_cannot_cross_tenant_context():
    with pytest.raises(ValueError, match="does not belong"):
        TenantContext(
            business_id="business-2",
            principal=make_principal(),
        )


def test_membership_must_match_current_user_and_business():
    context = TenantContext(
        business_id="business-1",
        principal=make_principal(),
    )

    context.require_membership(
        BusinessMembership(
            user_id="user-1",
            business_id="business-1",
            role=UserRole.OWNER,
        )
    )


def test_cross_business_membership_is_rejected():
    context = TenantContext(
        business_id="business-1",
        principal=make_principal(),
    )

    with pytest.raises(PermissionError, match="current business"):
        context.require_membership(
            BusinessMembership(
                user_id="user-1",
                business_id="business-2",
                role=UserRole.OWNER,
            )
        )


def test_cross_user_membership_is_rejected():
    context = TenantContext(
        business_id="business-1",
        principal=make_principal(),
    )

    with pytest.raises(PermissionError, match="authenticated user"):
        context.require_membership(
            BusinessMembership(
                user_id="user-2",
                business_id="business-1",
                role=UserRole.OWNER,
            )
        )


def test_role_mismatch_is_rejected():
    context = TenantContext(
        business_id="business-1",
        principal=make_principal(),
    )

    with pytest.raises(PermissionError, match="role"):
        context.require_membership(
            BusinessMembership(
                user_id="user-1",
                business_id="business-1",
                role=UserRole.ADMIN,
            )
        )


def test_identity_models_are_immutable():
    principal = make_principal()

    with pytest.raises(AttributeError):
        principal.business_id = "business-2"


def test_principal_rejects_secret_like_fields_by_contract():
    principal = make_principal()

    assert not hasattr(principal, "password")
    assert not hasattr(principal, "password_hash")
    assert not hasattr(principal, "access_token")
    assert not hasattr(principal, "provider_token")
