"""Tests for Passkey (Type 9) handler with fallback detection."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.handlers.passkey import PasskeyHandler, PasskeyRequired


@pytest.mark.anyio
async def test_passkey_clicks_explicit_fallback():
    """Verify clicking explicit fallback selector when provided and present."""
    handler = PasskeyHandler()
    mock_page = MagicMock()
    mock_fallback_btn = AsyncMock()
    mock_fallback_btn.count = AsyncMock(return_value=1)
    mock_fallback_btn.is_visible = AsyncMock(return_value=True)
    mock_page.locator.return_value.first = mock_fallback_btn
    mock_page.wait_for_selector = AsyncMock(return_value=True)

    fields = {"fallback_button": "#use-password-fallback"}
    result = await handler.handle_passkey_or_fallback(mock_page, "github.com", fields)

    assert result is True
    mock_fallback_btn.click.assert_called_once()
    mock_page.wait_for_selector.assert_called_once()


@pytest.mark.anyio
async def test_passkey_scans_fallback_when_explicit_is_stale():
    """If explicit fallback selector is stale/missing, handler scans page candidates."""
    handler = PasskeyHandler()
    mock_page = MagicMock()
    mock_page.wait_for_selector = AsyncMock(return_value=True)

    # Stale explicit locator returns count 0
    mock_stale = AsyncMock()
    mock_stale.count = AsyncMock(return_value=0)

    mock_candidate = AsyncMock()
    mock_candidate.is_visible = AsyncMock(return_value=True)
    mock_candidate.text_content = AsyncMock(return_value="Use password instead")
    mock_candidate.get_attribute = AsyncMock(return_value="")

    mock_candidates = MagicMock()
    mock_candidates.count = AsyncMock(return_value=1)
    mock_candidates.nth.return_value = mock_candidate

    def locator_side_effect(selector: str):
        if selector == "#stale-btn":
            mock_holder = MagicMock()
            mock_holder.first = mock_stale
            return mock_holder
        return mock_candidates

    mock_page.locator.side_effect = locator_side_effect

    fields = {"fallback_button": "#stale-btn"}
    result = await handler.handle_passkey_or_fallback(mock_page, "github.com", fields)

    assert result is True
    mock_candidate.click.assert_called_once()


@pytest.mark.anyio
async def test_passkey_matches_aria_label_and_verification_code():
    """Verify scanning matches aria-label attributes and verification code buttons."""
    handler = PasskeyHandler()
    mock_page = MagicMock()
    mock_page.wait_for_selector = AsyncMock(return_value=True)

    mock_candidate = AsyncMock()
    mock_candidate.is_visible = AsyncMock(return_value=True)
    mock_candidate.text_content = AsyncMock(return_value="")
    mock_candidate.get_attribute.side_effect = lambda attr: (
        "Use a verification code instead" if attr == "aria-label" else ""
    )

    mock_candidates = MagicMock()
    mock_candidates.count = AsyncMock(return_value=1)
    mock_candidates.nth.return_value = mock_candidate
    mock_page.locator.return_value = mock_candidates

    result = await handler.handle_passkey_or_fallback(mock_page, "github.com")

    assert result is True
    mock_candidate.click.assert_called_once()


@pytest.mark.anyio
async def test_passkey_no_fallback_raises_passkey_required():
    """If passkey prompt has no password/OTP fallback, PasskeyRequired is raised."""
    handler = PasskeyHandler()
    mock_page = MagicMock()

    mock_candidate = AsyncMock()
    mock_candidate.is_visible = AsyncMock(return_value=True)
    mock_candidate.text_content = AsyncMock(return_value="Sign in with Passkey only")
    mock_candidate.get_attribute = AsyncMock(return_value="")

    mock_candidates = MagicMock()
    mock_candidates.count = AsyncMock(return_value=1)
    mock_candidates.nth.return_value = mock_candidate
    mock_page.locator.return_value = mock_candidates

    with pytest.raises(
        PasskeyRequired,
        match="Passkey authentication required for 'secure-bank.com'",
    ):
        await handler.handle_passkey_or_fallback(mock_page, "secure-bank.com")
