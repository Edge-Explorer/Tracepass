from unittest.mock import AsyncMock, MagicMock

import pytest

from core.handlers.iframe_login import IframeLoginHandler, IframeNotFound


@pytest.mark.anyio
async def test_iframe_login_success_with_submit():
    """Verify IframeLoginHandler switches to frame context and submits."""
    handler = IframeLoginHandler(
        username="test_user",
        password="secret_password",
        typing_delay_ms=0,
        iframe_timeout_ms=1000,
        timeout_ms=1000,
    )

    mock_page = MagicMock()
    mock_frame = MagicMock()
    mock_user_input = AsyncMock()
    mock_pass_input = AsyncMock()
    mock_submit_btn = AsyncMock()

    mock_page.wait_for_selector = AsyncMock(return_value=True)
    mock_page.frame_locator.return_value = mock_frame
    mock_page.wait_for_load_state = AsyncMock()

    def frame_locator_side_effect(selector: str):
        if selector == "#user":
            return mock_user_input
        if selector == "#pass":
            return mock_pass_input
        if selector == "#btn":
            return mock_submit_btn
        return AsyncMock()

    mock_frame.locator.side_effect = frame_locator_side_effect

    fields = {
        "iframe": "iframe#auth-frame",
        "username": "#user",
        "password": "#pass",
        "submit": "#btn",
    }

    result = await handler.execute(mock_page, fields)
    assert result is True

    mock_page.wait_for_selector.assert_called_once_with(
        "iframe#auth-frame", state="attached", timeout=1000
    )
    mock_page.frame_locator.assert_called_once_with("iframe#auth-frame")
    mock_user_input.press_sequentially.assert_called_once_with("test_user", delay=0)
    mock_pass_input.press_sequentially.assert_called_once_with("secret_password", delay=0)
    mock_submit_btn.click.assert_called_once()


@pytest.mark.anyio
async def test_iframe_login_enter_fallback():
    """Verify Enter key fallback inside frame when submit button is None."""
    handler = IframeLoginHandler(
        username="user",
        password="pass",
        typing_delay_ms=0,
    )

    mock_page = MagicMock()
    mock_frame = MagicMock()
    mock_user_input = AsyncMock()
    mock_pass_input = AsyncMock()

    mock_page.wait_for_selector = AsyncMock(return_value=True)
    mock_page.frame_locator.return_value = mock_frame
    mock_page.wait_for_load_state = AsyncMock()

    mock_frame.locator.side_effect = lambda s: mock_user_input if s == "#user" else mock_pass_input

    fields = {
        "iframe": "#frame",
        "username": "#user",
        "password": "#pass",
        "submit": None,
    }

    result = await handler.execute(mock_page, fields)
    assert result is True
    mock_pass_input.press.assert_called_once_with("Enter")


@pytest.mark.anyio
async def test_iframe_not_found_raises():
    """If target iframe does not attach within timeout, IframeNotFound is raised."""
    handler = IframeLoginHandler(
        username="user",
        password="pass",
        iframe_timeout_ms=100,
    )

    mock_page = MagicMock()

    async def timeout_fn(*args, **kwargs):
        raise TimeoutError("iframe not attached")

    mock_page.wait_for_selector = AsyncMock(side_effect=timeout_fn)

    fields = {
        "iframe": "#missing-frame",
        "username": "#user",
        "password": "#pass",
    }

    with pytest.raises(IframeNotFound, match="failed to attach"):
        await handler.execute(mock_page, fields)


@pytest.mark.anyio
async def test_iframe_missing_selectors_raises():
    """Missing iframe, username, or password selector raises ValueError."""
    handler = IframeLoginHandler(username="usr", password="pwd")
    mock_page = MagicMock()

    with pytest.raises(ValueError, match="requires an 'iframe' selector"):
        await handler.execute(mock_page, {"iframe": None, "username": "#u", "password": "#p"})

    with pytest.raises(ValueError, match="requires both 'username' and 'password'"):
        await handler.execute(mock_page, {"iframe": "#f", "username": "#u", "password": None})
