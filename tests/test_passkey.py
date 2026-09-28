"""Tests for Passkey (Type 9) handler with fallback detection."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.handlers.passkey import PasskeyHandler, PasskeyRequired


@pytest.mark.anyio
async def test_passkey_clicks_explicit_fallback():
    """Verify clicking explicit fallback selector when provided."""
    handler = PasskeyHandler()
    mock_page = MagicMock()
    mock_fallback_btn = AsyncMock()
    mock_page.locator.return_value.first = mock_fallback_btn
    mock_page.wait_for_load_state = AsyncMock()

    fields = {"fallback_button": "#use-password-fallback"}
    result = await handler.handle_passkey_or_fallback(mock_page, "github.com", fields)

    assert result is True
    mock_fallback_btn.click.assert_called_once()


@pytest.mark.anyio
async def test_passkey_scans_and_clicks_text_fallback():
    """Verify scanning for 'Use password instead' button and clicking it."""
    handler = PasskeyHandler()
    mock_page = MagicMock()
    mock_page.wait_for_load_state = AsyncMock()

    mock_candidate1 = AsyncMock()
    mock_candidate1.is_visible = AsyncMock(return_value=True)
    mock_candidate1.text_content = AsyncMock(return_value="Sign in with Passkey")

    mock_candidate2 = AsyncMock()
    mock_candidate2.is_visible = AsyncMock(return_value=True)
    mock_candidate2.text_content = AsyncMock(return_value="Use password instead")

    mock_candidates = MagicMock()
    mock_candidates.count = AsyncMock(return_value=2)
    mock_candidates.nth.side_effect = lambda i: mock_candidate1 if i == 0 else mock_candidate2

    mock_page.locator.return_value = mock_candidates

    result = await handler.handle_passkey_or_fallback(mock_page, "github.com")

    assert result is True
    mock_candidate2.click.assert_called_once()


@pytest.mark.anyio
async def test_passkey_no_fallback_raises_passkey_required():
    """If passkey prompt has no password fallback, PasskeyRequired is raised."""
    handler = PasskeyHandler()
    mock_page = MagicMock()

    mock_candidate = AsyncMock()
    mock_candidate.is_visible = AsyncMock(return_value=True)
    mock_candidate.text_content = AsyncMock(return_value="Sign in with Passkey only")

    mock_candidates = MagicMock()
    mock_candidates.count = AsyncMock(return_value=1)
    mock_candidates.nth.return_value = mock_candidate
    mock_page.locator.return_value = mock_candidates

    with pytest.raises(
        PasskeyRequired,
        match="Passkey authentication required for 'secure-bank.com'",
    ):
        await handler.handle_passkey_or_fallback(mock_page, "secure-bank.com")
