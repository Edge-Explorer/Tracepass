from unittest.mock import AsyncMock, MagicMock
import pytest
from core.handlers.single_step import SingleStepHandler


@pytest.mark.anyio
async def test_single_step_execution_with_submit_button():
    """Verify that SingleStepHandler clicks and types into username, password, and submit locators."""
    handler = SingleStepHandler(
        username="test_user",
        password="secret_password",
        typing_delay_ms=0,
        timeout_ms=1000,
    )

    mock_page = MagicMock()
    mock_locator = AsyncMock()
    mock_page.locator.return_value = mock_locator
    mock_page.wait_for_load_state = AsyncMock()

    fields = {
        "username": "#username",
        "password": "#password",
        "submit": "#submit_btn",
    }

    result = await handler.execute(mock_page, fields)

    assert result is True
    # Verify username locator calls
    assert mock_page.locator.call_count == 3
    mock_page.locator.assert_any_call("#username")
    mock_page.locator.assert_any_call("#password")
    mock_page.locator.assert_any_call("#submit_btn")


@pytest.mark.anyio
async def test_single_step_execution_with_enter_fallback():
    """Verify Enter key fallback when no submit button is detected."""
    handler = SingleStepHandler(
        username="test_user",
        password="secret_password",
        typing_delay_ms=0,
    )

    mock_page = MagicMock()
    mock_locator = AsyncMock()
    mock_page.locator.return_value = mock_locator
    mock_page.wait_for_load_state = AsyncMock()

    fields = {
        "username": "#username",
        "password": "#password",
        "submit": None,
    }

    result = await handler.execute(mock_page, fields)

    assert result is True
    # Password locator should have received the "Enter" key press
    mock_locator.press.assert_called_with("Enter")


@pytest.mark.anyio
async def test_single_step_raises_on_missing_fields():
    """Verify ValueError is raised if username or password selector is missing."""
    handler = SingleStepHandler(username="usr", password="pwd")
    mock_page = MagicMock()

    with pytest.raises(ValueError, match="SingleStepHandler requires both username and password"):
        await handler.execute(mock_page, {"username": "#usr", "password": None})