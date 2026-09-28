"""Tests for Authentication Verifier (Component E)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.auth_verifier import AuthVerifier


@pytest.mark.anyio
async def test_custom_registered_verifier_async_function():
    """Verify custom async function verifier registration and execution."""
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
async def test_custom_registered_verifier_callable_object():
    """Verify custom callable object with async __call__ is properly awaited."""
    verifier = AuthVerifier()

    class CustomVerifierObject:
        async def __call__(self, page):
            return True

    verifier.register_verifier("example.com", CustomVerifierObject())
    mock_page = MagicMock()

    result = await verifier.verify(mock_page, "example.com")
    assert result is True


@pytest.mark.anyio
async def test_generic_heuristic_detects_visible_error_banner():
    """Verify generic heuristic rejects login if visible error alert is found."""
    verifier = AuthVerifier()
    mock_page = MagicMock()

    mock_error = AsyncMock()
    mock_error.is_visible = AsyncMock(return_value=True)
    mock_error.text_content = AsyncMock(return_value="Invalid credentials provided")

    mock_errors_holder = MagicMock()
    mock_errors_holder.count = AsyncMock(return_value=1)
    mock_errors_holder.nth.return_value = mock_error

    mock_page.locator.return_value = mock_errors_holder

    result = await verifier.verify(mock_page, "example.com")
    assert result is False


@pytest.mark.anyio
async def test_generic_heuristic_ignores_hidden_error_alert():
    """Verify hidden error alerts do not cause false rejections."""
    verifier = AuthVerifier()
    mock_page = MagicMock()

    mock_hidden_error = AsyncMock()
    mock_hidden_error.is_visible = AsyncMock(return_value=False)
    mock_hidden_error.text_content = AsyncMock(return_value="Invalid password")

    mock_errors_holder = MagicMock()
    mock_errors_holder.count = AsyncMock(return_value=1)
    mock_errors_holder.nth.return_value = mock_hidden_error

    mock_pass_holder = MagicMock()
    mock_pass_holder.count = AsyncMock(return_value=0)

    mock_candidates = MagicMock()
    mock_candidates.count = AsyncMock(return_value=0)

    def locator_side_effect(selector: str):
        if "[role='alert']" in selector:
            return mock_errors_holder
        if selector == "input[type='password']":
            return mock_pass_holder
        return mock_candidates

    mock_page.locator.side_effect = locator_side_effect

    cookies = [{"name": "session_id", "value": "abc123xyz"}]
    result = await verifier.verify(mock_page, "example.com", cookies=cookies)
    assert result is True


@pytest.mark.anyio
async def test_generic_heuristic_detects_visible_password():
    """Verify generic heuristic rejects login if password input is still visible."""
    verifier = AuthVerifier()
    mock_page = MagicMock()

    mock_errors_holder = MagicMock()
    mock_errors_holder.count = AsyncMock(return_value=0)

    mock_pass = AsyncMock()
    mock_pass.is_visible = AsyncMock(return_value=True)
    mock_pass_holder = MagicMock()
    mock_pass_holder.count = AsyncMock(return_value=1)
    mock_pass_holder.nth.return_value = mock_pass

    def locator_side_effect(selector: str):
        if "[role='alert']" in selector:
            return mock_errors_holder
        if selector == "input[type='password']":
            return mock_pass_holder
        return MagicMock()

    mock_page.locator.side_effect = locator_side_effect

    result = await verifier.verify(mock_page, "example.com")
    assert result is False


@pytest.mark.anyio
async def test_generic_heuristic_confirms_logout_control():
    """Verify generic heuristic confirms authentication when explicit Log out button is visible."""
    verifier = AuthVerifier()
    mock_page = MagicMock()

    mock_errors_holder = MagicMock()
    mock_errors_holder.count = AsyncMock(return_value=0)

    mock_pass_holder = MagicMock()
    mock_pass_holder.count = AsyncMock(return_value=0)

    mock_logout_btn = AsyncMock()
    mock_logout_btn.is_visible = AsyncMock(return_value=True)
    mock_logout_btn.text_content = AsyncMock(return_value="Log out")
    mock_logout_btn.get_attribute = AsyncMock(return_value="")

    mock_candidates = MagicMock()
    mock_candidates.count = AsyncMock(return_value=1)
    mock_candidates.nth.return_value = mock_logout_btn

    def locator_side_effect(selector: str):
        if "[role='alert']" in selector:
            return mock_errors_holder
        if selector == "input[type='password']":
            return mock_pass_holder
        return mock_candidates

    mock_page.locator.side_effect = locator_side_effect

    result = await verifier.verify(mock_page, "example.com")
    assert result is True


@pytest.mark.anyio
async def test_generic_heuristic_rejects_unrelated_analytics_cookies():
    """Verify generic heuristic rejects login if only analytics cookies/storage exist."""
    verifier = AuthVerifier()
    mock_page = MagicMock()

    mock_errors_holder = MagicMock()
    mock_errors_holder.count = AsyncMock(return_value=0)

    mock_pass_holder = MagicMock()
    mock_pass_holder.count = AsyncMock(return_value=0)

    mock_candidates = MagicMock()
    mock_candidates.count = AsyncMock(return_value=0)

    def locator_side_effect(selector: str):
        if "[role='alert']" in selector:
            return mock_errors_holder
        if selector == "input[type='password']":
            return mock_pass_holder
        return mock_candidates

    mock_page.locator.side_effect = locator_side_effect

    unrelated_cookies = [{"name": "_ga", "value": "GA1.2.34567"}]
    unrelated_storage = {"theme_mode": "dark"}

    result = await verifier.verify(
        mock_page, "example.com", cookies=unrelated_cookies, local_storage=unrelated_storage
    )
    assert result is False


@pytest.mark.anyio
async def test_generic_heuristic_confirms_via_auth_token_storage():
    """Verify generic heuristic confirms login if jwt/auth token exists in storage."""
    verifier = AuthVerifier()
    mock_page = MagicMock()

    mock_errors_holder = MagicMock()
    mock_errors_holder.count = AsyncMock(return_value=0)
    mock_pass_holder = MagicMock()
    mock_pass_holder.count = AsyncMock(return_value=0)
    mock_candidates = MagicMock()
    mock_candidates.count = AsyncMock(return_value=0)

    def locator_side_effect(selector: str):
        if "[role='alert']" in selector:
            return mock_errors_holder
        if selector == "input[type='password']":
            return mock_pass_holder
        return mock_candidates

    mock_page.locator.side_effect = locator_side_effect

    auth_storage = {"jwt_access_token": "eyJhbGciOiJIUzI1Ni..."}
    result = await verifier.verify(mock_page, "example.com", local_storage=auth_storage)
    assert result is True
