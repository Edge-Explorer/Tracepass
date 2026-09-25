import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.handlers.multi_step import MultiStepHandler, MultiStepTransitionTimeout


@pytest.mark.anyio
async def test_multi_step_navigation_wins():
    """When a full page navigation occurs after step 1, handler waits for password on new page."""
    handler = MultiStepHandler(
        username="user@example.com",
        password="secret_password",
        typing_delay_ms=0,
        transition_timeout_ms=1000,
        password_wait_timeout_ms=1000,
    )

    mock_page = MagicMock()
    mock_locator = AsyncMock()
    mock_locator.count = AsyncMock(return_value=1)
    mock_page.locator.return_value = mock_locator

    # Simulate navigation winning immediately
    async def mock_nav(timeout=1000):
        return True

    # Simulate selector lagging
    async def mock_slow_selector(*args, **kwargs):
        await asyncio.sleep(5)

    mock_page.wait_for_navigation = mock_nav
    mock_page.wait_for_selector = AsyncMock(side_effect=mock_slow_selector)
    mock_page.wait_for_load_state = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()

    fields = {
        "username": "#identifier",
        "next": "#identifierNext",
        "password": "#password_input",
        "password_submit": "#passwordNext",
    }

    result = await handler.execute(mock_page, fields)
    assert result is True
    mock_page.locator.assert_any_call("#identifier")
    mock_page.locator.assert_any_call("#identifierNext")
    mock_page.locator.assert_any_call("#password_input")
    mock_page.locator.assert_any_call("#passwordNext")


@pytest.mark.anyio
async def test_multi_step_dom_mutation_wins():
    """When password field appears via DOM mutation (SPA), handler proceeds without navigation."""
    handler = MultiStepHandler(
        username="user@example.com",
        password="secret_password",
        typing_delay_ms=0,
        transition_timeout_ms=1000,
    )

    mock_page = MagicMock()
    mock_locator = AsyncMock()
    mock_locator.count = AsyncMock(return_value=1)
    mock_page.locator.return_value = mock_locator

    # Simulate slow navigation
    async def mock_slow_nav(timeout=1000):
        await asyncio.sleep(5)

    # Simulate selector appearing immediately
    async def mock_selector(*args, **kwargs):
        return True

    mock_page.wait_for_navigation = mock_slow_nav
    mock_page.wait_for_selector = AsyncMock(side_effect=mock_selector)
    mock_page.wait_for_load_state = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()

    fields = {
        "username": "#username",
        "next": "#next-btn",
        "password": "#password",
        "submit": "#next-btn",
    }

    result = await handler.execute(mock_page, fields)
    assert result is True
    mock_page.locator.assert_any_call("#username")
    mock_page.locator.assert_any_call("#next-btn")
    mock_page.locator.assert_any_call("#password")


@pytest.mark.anyio
async def test_multi_step_transition_timeout_raises():
    """If neither navigation nor selector resolves in time, MultiStepTransitionTimeout is raised."""
    handler = MultiStepHandler(
        username="user@example.com",
        password="secret_password",
        typing_delay_ms=0,
        transition_timeout_ms=100,
    )

    mock_page = MagicMock()
    mock_locator = AsyncMock()
    mock_page.locator.return_value = mock_locator

    async def timeout_fn(*args, **kwargs):
        raise TimeoutError("Timed out")

    mock_page.wait_for_navigation = timeout_fn
    mock_page.wait_for_selector = timeout_fn

    fields = {"username": "#user", "next": "#next"}

    with pytest.raises(MultiStepTransitionTimeout, match="Transition to password step timed out"):
        await handler.execute(mock_page, fields)


@pytest.mark.anyio
async def test_multi_step_enter_key_fallback_step1():
    """When no next/submit button is in fields, Enter key is pressed on the username input."""
    handler = MultiStepHandler(
        username="user@example.com",
        password="secret_password",
        typing_delay_ms=0,
    )

    mock_page = MagicMock()
    mock_locator = AsyncMock()
    mock_locator.count = AsyncMock(return_value=0)
    mock_page.locator.return_value = mock_locator

    mock_page.wait_for_navigation = AsyncMock(return_value=True)
    mock_page.wait_for_selector = AsyncMock(return_value=True)
    mock_page.wait_for_load_state = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()

    fields = {"username": "#user", "next": None, "password": "#pass"}

    result = await handler.execute(mock_page, fields)
    assert result is True
    mock_locator.press.assert_any_call("Enter")


@pytest.mark.anyio
async def test_multi_step_missing_username_raises():
    """Missing username selector raises ValueError."""
    handler = MultiStepHandler(username="usr", password="pwd")
    mock_page = MagicMock()

    with pytest.raises(ValueError, match="MultiStepHandler requires a username selector"):
        await handler.execute(mock_page, {"username": None})
