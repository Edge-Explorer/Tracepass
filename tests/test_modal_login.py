from unittest.mock import AsyncMock, MagicMock

import pytest

from core.handlers.modal_login import ModalLoginHandler, ModalTriggerTimeout


@pytest.mark.anyio
async def test_modal_login_success_with_trigger():
    """Verify that ModalLoginHandler clicks the trigger, waits for modal, scopes input actions, and waits for modal to close."""
    handler = ModalLoginHandler(
        username="test_user",
        password="secret_password",
        typing_delay_ms=0,
        modal_timeout_ms=1000,
        timeout_ms=1000,
    )

    mock_page = MagicMock()
    mock_trigger = AsyncMock()
    mock_container = MagicMock()
    mock_user_input = AsyncMock()
    mock_pass_input = AsyncMock()
    mock_submit_btn = AsyncMock()

    def locator_side_effect(selector: str):
        if selector == "#sign-in-btn":
            return mock_trigger
        if "[role='dialog']" in selector:
            return mock_container
        return AsyncMock()

    def container_locator_side_effect(selector: str):
        if selector == "#username":
            return mock_user_input
        if selector == "#password":
            return mock_pass_input
        if selector == "#modal-submit":
            return mock_submit_btn
        return AsyncMock()

    mock_page.locator.side_effect = locator_side_effect
    mock_page.wait_for_selector = AsyncMock(return_value=True)
    mock_page.wait_for_load_state = AsyncMock()
    mock_container.first = mock_container
    mock_container.locator.side_effect = container_locator_side_effect

    fields = {
        "modal_trigger": "#sign-in-btn",
        "username": "#username",
        "password": "#password",
        "submit": "#modal-submit",
    }

    result = await handler.execute(mock_page, fields)
    assert result is True

    # Check trigger was clicked
    mock_trigger.click.assert_called_once()
    # Check dialog container was waited on to open (visible) and close (hidden)
    mock_page.wait_for_selector.assert_any_call(
        ModalLoginHandler.DEFAULT_MODAL_CONTAINER, state="visible", timeout=1000
    )
    mock_page.wait_for_selector.assert_any_call(
        ModalLoginHandler.DEFAULT_MODAL_CONTAINER, state="hidden", timeout=1000
    )
    # Check scoped fields were typed into
    mock_user_input.press_sequentially.assert_called_once_with("test_user", delay=0)
    mock_pass_input.press_sequentially.assert_called_once_with("secret_password", delay=0)
    mock_submit_btn.click.assert_called_once()


@pytest.mark.anyio
async def test_modal_trigger_timeout_raises():
    """If modal dialog fails to appear within timeout, ModalTriggerTimeout is raised."""
    handler = ModalLoginHandler(
        username="usr",
        password="pwd",
        modal_timeout_ms=100,
    )

    mock_page = MagicMock()
    mock_trigger = AsyncMock()
    mock_page.locator.return_value = mock_trigger

    async def timeout_fn(*args, **kwargs):
        raise TimeoutError("Modal never appeared")

    mock_page.wait_for_selector = AsyncMock(side_effect=timeout_fn)

    fields = {
        "modal_trigger": "#missing-dialog-btn",
        "username": "#username",
        "password": "#password",
    }

    with pytest.raises(ModalTriggerTimeout, match="Modal dialog did not appear"):
        await handler.execute(mock_page, fields)


@pytest.mark.anyio
async def test_modal_login_enter_fallback():
    """Verify Enter key fallback inside modal when no submit button is provided."""
    handler = ModalLoginHandler(
        username="test_user",
        password="secret_password",
        typing_delay_ms=0,
    )

    mock_page = MagicMock()
    mock_trigger = AsyncMock()
    mock_container = MagicMock()
    mock_user_input = AsyncMock()
    mock_pass_input = AsyncMock()

    mock_page.locator.side_effect = lambda s: mock_trigger if s == "#trigger" else mock_container
    mock_container.first = mock_container
    mock_container.locator.side_effect = lambda s: (
        mock_user_input if s == "#user" else mock_pass_input
    )
    mock_page.wait_for_selector = AsyncMock(return_value=True)
    mock_page.wait_for_load_state = AsyncMock()

    fields = {
        "modal_trigger": "#trigger",
        "username": "#user",
        "password": "#pass",
        "submit": None,
    }

    result = await handler.execute(mock_page, fields)
    assert result is True
    mock_pass_input.press.assert_called_once_with("Enter")


@pytest.mark.anyio
async def test_modal_missing_credentials_raises():
    """Missing username or password selector raises ValueError."""
    handler = ModalLoginHandler(username="usr", password="pwd")
    mock_page = MagicMock()

    with pytest.raises(ValueError, match="ModalLoginHandler requires both username and password"):
        await handler.execute(mock_page, {"username": "#usr", "password": None})
