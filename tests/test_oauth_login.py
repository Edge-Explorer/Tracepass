"""Tests for OAuth / Single Sign-On (Type 5) login handler."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.handlers.oauth_login import (
    OAuthFlowTimeout,
    OAuthLoginHandler,
    OAuthProviderNotFound,
)


class AsyncContextManagerMock:
    """Mock for async context managers like page.expect_popup or page.expect_navigation."""

    def __init__(self, return_value: Any = None) -> None:
        """Initializes with the target return value."""
        self.return_value = return_value

    async def __aenter__(self) -> Any:
        """Enters the async context manager."""
        return self.return_value

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        """Exits the async context manager."""
        return False


class FailingContextManager:
    """Mock context manager that raises on enter."""

    def __init__(self, exc: Exception) -> None:
        """Initializes with the exception to raise."""
        self.exc = exc

    async def __aenter__(self) -> None:
        """Raises exception on enter."""
        raise self.exc

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        """Exits context."""
        return False


@pytest.mark.anyio
async def test_oauth_login_popup_flow_success():
    """Verify OAuth popup window interception, IdP execution, and closure."""
    handler = OAuthLoginHandler(
        username="user@gmail.com",
        password="oauth_password",
        typing_delay_ms=0,
        popup_timeout_ms=1000,
        redirect_timeout_ms=1000,
        timeout_ms=1000,
    )

    mock_page = MagicMock()
    mock_sso_btn = AsyncMock()
    mock_page.locator.return_value = mock_sso_btn
    mock_page.wait_for_selector = AsyncMock(return_value=True)
    mock_page.wait_for_load_state = AsyncMock()

    # Mock popup page
    mock_popup = MagicMock()
    mock_popup.is_closed.return_value = True
    mock_popup.close = AsyncMock()
    mock_popup.wait_for_load_state = AsyncMock()
    mock_popup.wait_for_event = AsyncMock(return_value=True)

    # Mock popup inputs
    mock_popup_locator = AsyncMock()
    mock_popup.locator.return_value = mock_popup_locator

    popup_info_holder = MagicMock()
    popup_info_holder.value = AsyncMock(return_value=mock_popup)()

    mock_page.expect_popup.return_value = AsyncContextManagerMock(popup_info_holder)

    fields = {"sso_button": "button:has-text('Continue with Google')"}
    idp_fields = {"username": "#email", "password": "#password", "submit": "#submit"}

    result = await handler.execute(mock_page, fields, is_popup=True, idp_fields=idp_fields)

    assert result is True
    mock_page.wait_for_selector.assert_called_once_with(
        "button:has-text('Continue with Google')", state="attached", timeout=1000
    )
    mock_sso_btn.click.assert_called_once()
    mock_popup.wait_for_load_state.assert_any_call("domcontentloaded")
    mock_popup_locator.press_sequentially.assert_any_call("user@gmail.com", delay=0)
    mock_popup_locator.press_sequentially.assert_any_call("oauth_password", delay=0)


@pytest.mark.anyio
async def test_oauth_login_redirect_flow_success():
    """Verify OAuth same-tab redirect navigation and callback settlement."""
    handler = OAuthLoginHandler(
        username="user@github.com",
        password="github_password",
        typing_delay_ms=0,
    )

    mock_page = MagicMock()
    mock_sso_btn = AsyncMock()
    mock_page.locator.return_value = mock_sso_btn
    mock_page.wait_for_selector = AsyncMock(return_value=True)
    mock_page.expect_navigation.return_value = AsyncContextManagerMock()
    mock_page.wait_for_load_state = AsyncMock()

    fields = {"sso_button": "a:has-text('Sign in with GitHub')"}

    result = await handler.execute(mock_page, fields, is_popup=False)

    assert result is True
    mock_sso_btn.click.assert_called_once()
    assert mock_page.expect_navigation.call_count >= 1


@pytest.mark.anyio
async def test_oauth_provider_not_found_raises():
    """If SSO trigger button fails to render, OAuthProviderNotFound is raised."""
    handler = OAuthLoginHandler(popup_timeout_ms=100)
    mock_page = MagicMock()
    mock_page.wait_for_selector = AsyncMock(side_effect=TimeoutError("Button not found"))

    fields = {"sso_button": "#missing-sso-btn"}

    with pytest.raises(OAuthProviderNotFound, match="not found or failed to render"):
        await handler.execute(mock_page, fields, is_popup=True)


@pytest.mark.anyio
async def test_oauth_popup_timeout_raises():
    """If popup window fails to open, OAuthFlowTimeout is raised."""
    handler = OAuthLoginHandler(popup_timeout_ms=100)
    mock_page = MagicMock()
    mock_sso_btn = AsyncMock()
    mock_page.locator.return_value = mock_sso_btn
    mock_page.wait_for_selector = AsyncMock(return_value=True)
    mock_page.expect_popup.return_value = FailingContextManager(TimeoutError("Popup did not open"))

    fields = {"sso_button": "#google-sso"}

    with pytest.raises(OAuthFlowTimeout, match="OAuth popup failed to open"):
        await handler.execute(mock_page, fields, is_popup=True)


@pytest.mark.anyio
async def test_oauth_popup_close_timeout_raises():
    """If popup window fails to close within timeout, OAuthFlowTimeout is raised."""
    handler = OAuthLoginHandler(redirect_timeout_ms=100)
    mock_page = MagicMock()
    mock_sso_btn = AsyncMock()
    mock_page.locator.return_value = mock_sso_btn
    mock_page.wait_for_selector = AsyncMock(return_value=True)

    mock_popup = MagicMock()
    mock_popup.is_closed.return_value = False
    mock_popup.close = AsyncMock()
    mock_popup.wait_for_load_state = AsyncMock()
    mock_popup.wait_for_event = AsyncMock(side_effect=TimeoutError("Close timeout"))

    popup_info_holder = MagicMock()
    popup_info_holder.value = AsyncMock(return_value=mock_popup)()
    mock_page.expect_popup.return_value = AsyncContextManagerMock(popup_info_holder)

    fields = {"sso_button": "#google-sso"}

    with pytest.raises(OAuthFlowTimeout, match="did not close within"):
        await handler.execute(mock_page, fields, is_popup=True)


@pytest.mark.anyio
async def test_oauth_missing_button_raises():
    """Missing sso_button selector in fields raises ValueError."""
    handler = OAuthLoginHandler()
    mock_page = MagicMock()

    with pytest.raises(ValueError, match="requires an 'sso_button' selector"):
        await handler.execute(mock_page, {"sso_button": None})
