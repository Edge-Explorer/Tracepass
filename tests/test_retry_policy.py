"""Tests for Failure Modes & Retry Policy (Decision 5)."""

import pytest

from core.retry_policy import (
    AccountLocked,
    AuthenticationRequired,
    BotDetectionBlocked,
    CaptchaRequired,
    CredentialRejected,
    LoginFormNotFound,
    MagicLinkRequired,
    MultiStepTransitionTimeout,
    NavigationLoopDetected,
    OTPPrimaryRequired,
    PageLoadTimeout,
    PasskeyRequired,
    RetryPolicy,
    TwoFactorTimeout,
)

try:
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
except ImportError:
    PlaywrightTimeoutError = None


def test_decision_5_matrix_prohibits_dangerous_retries():
    """Verify CredentialRejected, AccountLocked, 2FA, Captcha, and Loop errors never retry."""
    policy = RetryPolicy()

    dangerous_exceptions = [
        CredentialRejected("Invalid credentials"),
        AccountLocked("Too many attempts"),
        TwoFactorTimeout("TOTP timed out"),
        CaptchaRequired("reCAPTCHA detected"),
        LoginFormNotFound("No form"),
        NavigationLoopDetected("Redirect loop"),
        AuthenticationRequired("No session"),
        BotDetectionBlocked("Cloudflare Turnstile"),
        PasskeyRequired("domain.com"),
        OTPPrimaryRequired("domain.com"),
        MagicLinkRequired("domain.com"),
    ]

    for exc in dangerous_exceptions:
        decision = policy.get_decision(exc, attempt=1)
        assert not decision.should_retry, f"{type(exc).__name__} should never retry!"
        assert decision.delay_seconds == 0.0


def test_out_of_scope_exceptions_do_not_retry():
    """Verify unknown/unhandled exceptions (KeyError, RuntimeError) never retry."""
    policy = RetryPolicy()
    out_of_scope = [
        RuntimeError("Unexpected system failure"),
        KeyError("Missing key"),
        AttributeError("NoneType has no attribute"),
    ]
    for exc in out_of_scope:
        decision = policy.get_decision(exc, attempt=1)
        assert decision.should_retry is False


def test_explicit_empty_max_retries_map_disables_retries():
    """Verify passing max_retries_map={} explicitly disables all retries."""
    policy = RetryPolicy(max_retries_map={})
    exc = PageLoadTimeout("Navigation timeout")
    decision = policy.get_decision(exc, attempt=1)
    assert decision.should_retry is False


def test_page_load_timeout_retries_once_with_3s_delay():
    """Verify PageLoadTimeout retries exactly once with a 3-second delay."""
    policy = RetryPolicy()
    exc = PageLoadTimeout("Navigation timeout")

    # Attempt 1 -> Retry with 3.0s delay
    decision1 = policy.get_decision(exc, attempt=1)
    assert decision1.should_retry is True
    assert decision1.delay_seconds == 3.0
    assert decision1.reload_from_scratch is False

    # Attempt 2 -> Exceeded retries
    decision2 = policy.get_decision(exc, attempt=2)
    assert decision2.should_retry is False


def test_playwright_native_timeout_error_retries_as_page_load_timeout():
    """Verify Playwright's native TimeoutError is treated as PageLoadTimeout."""
    if PlaywrightTimeoutError is None:
        pytest.skip("Playwright not installed in current environment")

    policy = RetryPolicy()
    exc = PlaywrightTimeoutError("Playwright navigation timeout")
    decision = policy.get_decision(exc, attempt=1)
    assert decision.should_retry is True
    assert decision.delay_seconds == 3.0


def test_multi_step_transition_timeout_retries_once_reloading_from_scratch():
    """Verify MultiStepTransitionTimeout retries once with reload_from_scratch=True."""
    policy = RetryPolicy()
    exc = MultiStepTransitionTimeout("Transition timeout")

    # Attempt 1 -> Retry with reload_from_scratch=True
    decision1 = policy.get_decision(exc, attempt=1)
    assert decision1.should_retry is True
    assert decision1.delay_seconds == 0.0
    assert decision1.reload_from_scratch is True

    # Attempt 2 -> Exceeded retries
    decision2 = policy.get_decision(exc, attempt=2)
    assert decision2.should_retry is False


@pytest.mark.anyio
async def test_execute_with_retry_succeeds_on_second_attempt():
    """Verify execute_with_retry retries transient PageLoadTimeout and succeeds."""
    policy = RetryPolicy()
    call_count = 0

    async def transient_action():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise PageLoadTimeout("Transient timeout")
        return "success"

    res = await policy.execute_with_retry(transient_action)
    assert res == "success"
    assert call_count == 2


@pytest.mark.anyio
async def test_execute_with_retry_raises_immediately_for_credential_rejected():
    """Verify execute_with_retry immediately raises CredentialRejected without retrying."""
    policy = RetryPolicy()
    call_count = 0

    async def failing_action():
        nonlocal call_count
        call_count += 1
        raise CredentialRejected("Wrong password")

    with pytest.raises(CredentialRejected, match="Wrong password"):
        await policy.execute_with_retry(failing_action)

    assert call_count == 1
