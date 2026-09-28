"""Tests for Authentication Verifier (Component E)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.auth_verifier import AuthVerifier


@pytest.mark.anyio
async def test_custom_registered_verifier():
    """Verify custom domain-specific verifier registration and execution."""
    verifier = AuthVerifier()

    async def github_verifier(page):
        return await page.locator(".Header-item [aria-label='View profile and more']").is_visible()

    verifier.register_verifier("github.com", github_verifier)

    mock_page = MagicMock()
    mock_avatar = AsyncMock()
    mock_avatar.is_visible = AsyncMock(return_value=True)
    mock_page.locator.return_value = mock_avatar

    result = await verifier.verify(mock_page, "https://github.com/login")
    assert result is True


@pytest.mark.anyio
async def test_generic_heuristic_detects_error_banner():
    """Verify generic heuristic rejects login if error banner is found."""
    verifier = AuthVerifier()
    mock_page = MagicMock()

    mock_body = AsyncMock()
    mock_body.text_content = AsyncMock(
        return_value="Invalid username or password. Please try again."
    )
    mock_page.locator.return_value = mock_body

    result = await verifier.verify(mock_page, "example.com")
    assert result is False


@pytest.mark.anyio
async def test_generic_heuristic_detects_visible_password():
    """Verify generic heuristic rejects login if password input is still visible."""
    verifier = AuthVerifier()
    mock_page = MagicMock()

    mock_body = AsyncMock()
    mock_body.text_content = AsyncMock(return_value="Welcome to site")

    mock_pass = AsyncMock()
    mock_pass.is_visible = AsyncMock(return_value=True)
    mock_pass_holder = MagicMock()
    mock_pass_holder.count = AsyncMock(return_value=1)
    mock_pass_holder.nth.return_value = mock_pass

    def locator_side_effect(selector: str):
        if selector == "body":
            return mock_body
        if selector == "input[type='password']":
            return mock_pass_holder
        return MagicMock()

    mock_page.locator.side_effect = locator_side_effect

    result = await verifier.verify(mock_page, "example.com")
    assert result is False


@pytest.mark.anyio
async def test_generic_heuristic_confirms_auth_signals():
    """Verify generic heuristic confirms authentication when logout/profile button is visible."""
    verifier = AuthVerifier()
    mock_page = MagicMock()

    mock_body = AsyncMock()
    mock_body.text_content = AsyncMock(return_value="User Dashboard")

    mock_pass_holder = MagicMock()
    mock_pass_holder.count = AsyncMock(return_value=0)

    mock_logout_btn = AsyncMock()
    mock_logout_btn.is_visible = AsyncMock(return_value=True)
    mock_logout_btn.text_content = AsyncMock(return_value="Log Out")

    mock_candidates = MagicMock()
    mock_candidates.count = AsyncMock(return_value=1)
    mock_candidates.nth.return_value = mock_logout_btn

    def locator_side_effect(selector: str):
        if selector == "body":
            return mock_body
        if selector == "input[type='password']":
            return mock_pass_holder
        return mock_candidates

    mock_page.locator.side_effect = locator_side_effect

    result = await verifier.verify(mock_page, "example.com")
    assert result is True


@pytest.mark.anyio
async def test_generic_heuristic_confirms_via_cookies_or_storage():
    """Verify generic heuristic confirms login if cookies/storage exist and no errors/password present."""
    verifier = AuthVerifier()
    mock_page = MagicMock()

    mock_body = AsyncMock()
    mock_body.text_content = AsyncMock(return_value="Welcome")
    mock_pass_holder = MagicMock()
    mock_pass_holder.count = AsyncMock(return_value=0)
    mock_candidates = MagicMock()
    mock_candidates.count = AsyncMock(return_value=0)

    def locator_side_effect(selector: str):
        if selector == "body":
            return mock_body
        if selector == "input[type='password']":
            return mock_pass_holder
        return mock_candidates

    mock_page.locator.side_effect = locator_side_effect

    cookies = [{"name": "auth_token", "value": "xyz123"}]
    result = await verifier.verify(mock_page, "example.com", cookies=cookies)
    assert result is True
