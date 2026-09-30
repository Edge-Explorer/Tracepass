"""Integration & Unit Tests for Master Login Engine Orchestrator."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.field_detector import LoginFlowType
from core.login_engine import LoginEngine
from core.retry_policy import (
    AuthenticationRequired,
    CredentialRejected,
    LoginFormNotFound,
    PageLoadTimeout,
)


@pytest.mark.anyio
async def test_login_engine_session_cache_hit_skips_login():
    """Verify that a valid cached session restores state, verifies, and skips login execution."""
    session_mgr = MagicMock()
    session_mgr.has_valid_session.return_value = True
    session_mgr.load_session.return_value = {
        "cookies": [{"name": "auth_session", "value": "xyz123"}],
        "local_storage": {"token": "abc"},
    }

    cred_mgr = MagicMock()
    field_det = MagicMock()
    verifier = MagicMock()
    verifier.verify = AsyncMock(return_value=True)

    engine = LoginEngine(
        session_manager=session_mgr,
        credential_manager=cred_mgr,
        field_detector=field_det,
        auth_verifier=verifier,
    )

    mock_page = MagicMock()
    mock_page.goto = AsyncMock()
    mock_page.context.add_cookies = AsyncMock()
    mock_page.evaluate = AsyncMock()

    result = await engine.authenticate(mock_page, "https://example.com/dashboard")

    assert result is True
    session_mgr.has_valid_session.assert_called_once_with("https://example.com/dashboard")
    session_mgr.load_session.assert_called_once_with("https://example.com/dashboard")
    verifier.verify.assert_called_once()
    cred_mgr.get_credentials.assert_not_called()
    field_det.detect_fields.assert_not_called()


@pytest.mark.anyio
async def test_login_engine_missing_credentials_raises_authentication_required():
    """Verify AuthenticationRequired is raised when no session and no credentials exist."""
    session_mgr = MagicMock()
    session_mgr.has_valid_session.return_value = False

    cred_mgr = MagicMock()
    cred_mgr.get_credentials.return_value = None

    engine = LoginEngine(session_manager=session_mgr, credential_manager=cred_mgr)

    mock_page = MagicMock()
    with pytest.raises(AuthenticationRequired, match="No credentials or session found"):
        await engine.authenticate(mock_page, "https://example.com/login")


@pytest.mark.anyio
async def test_login_engine_single_step_login_pipeline_success():
    """Verify end-to-end execution of Single-Step login pipeline."""
    session_mgr = MagicMock()
    session_mgr.has_valid_session.return_value = False

    cred_mgr = MagicMock()
    cred_mgr.get_credentials.return_value = ("mock_user_identity", "mock_credential_secret")

    field_det = MagicMock()
    field_det.detect_fields.return_value = {
        "flow_type": LoginFlowType.SINGLE_STEP,
        "fields": {
            "username": "input[name='username']",
            "password": "input[name='password']",
            "submit": "button[type='submit']",
        },
    }

    verifier = MagicMock()
    verifier.verify = AsyncMock(return_value=True)

    engine = LoginEngine(
        session_manager=session_mgr,
        credential_manager=cred_mgr,
        field_detector=field_det,
        auth_verifier=verifier,
    )

    mock_page = MagicMock()
    mock_page.content = AsyncMock(return_value="<html><body><form>...</form></body></html>")
    mock_page.fill = AsyncMock()
    mock_page.click = AsyncMock()
    mock_page.hover = AsyncMock()
    mock_page.wait_for_load_state = AsyncMock()
    mock_page.wait_for_selector = AsyncMock()
    mock_page.context.cookies = AsyncMock(return_value=[])
    mock_page.evaluate = AsyncMock(return_value={})

    mock_element = AsyncMock()
    mock_element.is_visible = AsyncMock(return_value=True)
    mock_page.locator.return_value = mock_element

    result = await engine.authenticate(mock_page, "https://example.com/login")

    assert result is True
    verifier.verify.assert_called_once()
    session_mgr.save_session.assert_called_once()


@pytest.mark.anyio
async def test_login_engine_verification_failure_raises_credential_rejected():
    """Verify CredentialRejected is raised when post-login verification fails."""
    session_mgr = MagicMock()
    session_mgr.has_valid_session.return_value = False

    cred_mgr = MagicMock()
    cred_mgr.get_credentials.return_value = ("mock_user_identity", "invalid_credential_secret")

    field_det = MagicMock()
    field_det.detect_fields.return_value = {
        "flow_type": LoginFlowType.SINGLE_STEP,
        "fields": {
            "username": "input[name='username']",
            "password": "input[name='password']",
            "submit": "button[type='submit']",
        },
    }

    verifier = MagicMock()
    verifier.verify = AsyncMock(return_value=False)

    engine = LoginEngine(
        session_manager=session_mgr,
        credential_manager=cred_mgr,
        field_detector=field_det,
        auth_verifier=verifier,
    )

    mock_page = MagicMock()
    mock_page.content = AsyncMock(return_value="<html><body><form>...</form></body></html>")
    mock_page.fill = AsyncMock()
    mock_page.click = AsyncMock()
    mock_page.hover = AsyncMock()
    mock_page.wait_for_load_state = AsyncMock()
    mock_page.wait_for_selector = AsyncMock()

    mock_element = AsyncMock()
    mock_element.is_visible = AsyncMock(return_value=True)
    mock_page.locator.return_value = mock_element

    with pytest.raises(CredentialRejected, match="Authentication verification failed"):
        await engine.authenticate(mock_page, "https://example.com/login")


@pytest.mark.anyio
async def test_login_engine_no_form_found_raises_login_form_not_found():
    """Verify LoginFormNotFound is raised when no form fields are detected."""
    session_mgr = MagicMock()
    session_mgr.has_valid_session.return_value = False

    cred_mgr = MagicMock()
    cred_mgr.get_credentials.return_value = ("mock_user_identity", "mock_credential_secret")

    field_det = MagicMock()
    field_det.detect_fields.return_value = {
        "flow_type": LoginFlowType.NONE,
        "fields": {},
    }

    engine = LoginEngine(
        session_manager=session_mgr,
        credential_manager=cred_mgr,
        field_detector=field_det,
    )

    mock_page = MagicMock()
    mock_page.content = AsyncMock(return_value="<html><body><h1>No form</h1></body></html>")
    mock_page.wait_for_selector = AsyncMock()

    with pytest.raises(LoginFormNotFound, match="Unable to identify login fields"):
        await engine.authenticate(mock_page, "https://example.com/login")


@pytest.mark.anyio
async def test_login_engine_retries_transient_page_timeout():
    """Verify that transient PageLoadTimeout is retried automatically by the engine."""
    session_mgr = MagicMock()
    session_mgr.has_valid_session.return_value = False

    cred_mgr = MagicMock()
    cred_mgr.get_credentials.return_value = ("mock_user_identity", "mock_credential_secret")

    field_det = MagicMock()
    field_det.detect_fields.return_value = {
        "flow_type": LoginFlowType.SINGLE_STEP,
        "fields": {
            "username": "input[name='username']",
            "password": "input[name='password']",
            "submit": "button[type='submit']",
        },
    }

    verifier = MagicMock()
    attempt = 0

    async def flaky_verify(page, url, cookies=None, local_storage=None):
        nonlocal attempt
        attempt += 1
        if attempt == 1:
            raise PageLoadTimeout("Transient page timeout")
        return True

    verifier.verify = flaky_verify

    engine = LoginEngine(
        session_manager=session_mgr,
        credential_manager=cred_mgr,
        field_detector=field_det,
        auth_verifier=verifier,
    )

    mock_page = MagicMock()
    mock_page.content = AsyncMock(return_value="<html><body><form>...</form></body></html>")
    mock_page.fill = AsyncMock()
    mock_page.click = AsyncMock()
    mock_page.hover = AsyncMock()
    mock_page.wait_for_load_state = AsyncMock()
    mock_page.wait_for_selector = AsyncMock()
    mock_page.context.cookies = AsyncMock(return_value=[])
    mock_page.evaluate = AsyncMock(return_value={})

    mock_element = AsyncMock()
    mock_element.is_visible = AsyncMock(return_value=True)
    mock_page.locator.return_value = mock_element

    result = await engine.authenticate(mock_page, "https://example.com/login")

    assert result is True
    assert attempt == 2
