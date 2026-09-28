"""Tests for OTP-Primary and Magic Link (Type 8) flow handler."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.handlers.otp_primary import (
    MagicLinkRequired,
    OTPOriginMismatch,
    OTPPrimaryHandler,
    OTPPrimaryRequired,
)


def test_env_domain_normalization():
    """Verify domain normalization produces shell-safe uppercase env suffixes."""
    assert OTPPrimaryHandler.normalize_domain_to_env_key("example.com") == "EXAMPLE_COM"
    assert (
        OTPPrimaryHandler.normalize_domain_to_env_key("https://sub.site-app.org:8080/path")
        == "SUB_SITE_APP_ORG_8080"
    )


def test_collision_free_env_key():
    """Verify collision-free env key generation distinguishes dots and hyphens."""
    dash_key = OTPPrimaryHandler.get_collision_free_env_key("foo-bar.com")
    dot_key = OTPPrimaryHandler.get_collision_free_env_key("foo.bar.com")
    assert dash_key != dot_key
    assert "DASH" in dash_key
    assert "DOT" in dot_key


@pytest.mark.anyio
async def test_otp_primary_with_env_code(monkeypatch: pytest.MonkeyPatch):
    """Verify OTP submission when TRACEPASS_OTP_<DOMAIN> is set."""
    monkeypatch.setenv("TRACEPASS_OTP_EXAMPLE_COM", "654321")

    handler = OTPPrimaryHandler(typing_delay_ms=0, allow_interactive=False)
    mock_page = MagicMock()
    mock_page.url = "https://example.com/login"
    mock_input = AsyncMock()
    mock_btn = AsyncMock()

    mock_page.locator.return_value.first = mock_input
    mock_page.wait_for_load_state = AsyncMock()

    def locator_side_effect(selector: str):
        mock_holder = MagicMock()
        if selector == "#submit-otp":
            mock_holder.first = mock_btn
        else:
            mock_holder.first = mock_input
        return mock_holder

    mock_page.locator.side_effect = locator_side_effect

    fields = {"otp_input": "#otp-code", "submit": "#submit-otp"}
    result = await handler.execute(mock_page, "example.com", fields)

    assert result is True
    mock_input.press_sequentially.assert_called_once_with("654321", delay=0)
    mock_btn.click.assert_called_once()


@pytest.mark.anyio
async def test_otp_primary_origin_mismatch_raises(monkeypatch: pytest.MonkeyPatch):
    """If page URL origin does not match expected target domain, OTPOriginMismatch is raised."""
    monkeypatch.setenv("TRACEPASS_OTP_EXAMPLE_COM", "654321")
    handler = OTPPrimaryHandler(allow_interactive=False)
    mock_page = MagicMock()
    mock_page.url = "https://malicious-phishing.com/login"

    with pytest.raises(OTPOriginMismatch, match="does not match expected target domain"):
        await handler.execute(mock_page, "example.com", {})


@pytest.mark.anyio
async def test_otp_primary_missing_env_raises():
    """If no OTP code is provided and interactive is disabled, OTPPrimaryRequired is raised."""
    handler = OTPPrimaryHandler(allow_interactive=False)
    mock_page = MagicMock()
    mock_page.url = "https://unknown.com/auth"

    with pytest.raises(OTPPrimaryRequired, match="OTP authentication required for 'unknown.com'"):
        await handler.execute(mock_page, "unknown.com", {})


@pytest.mark.anyio
async def test_magic_link_detected_raises():
    """If magic link is detected, MagicLinkRequired is raised immediately."""
    handler = OTPPrimaryHandler(allow_interactive=False)
    mock_page = MagicMock()

    with pytest.raises(MagicLinkRequired, match="Magic link login required for 'slack.com'"):
        await handler.execute(mock_page, "slack.com", {}, is_magic_link=True)
