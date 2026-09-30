"""Failure Modes & Retry Policy Engine (Decision 5).

Implements Section 8 & Decision 5 of docs/login-engine.md:
- Failure-type-specific retry matrix.
- Conservative defaults to protect against account lockout.
- Differentiates between transient timeouts (1 retry allowed) and credential/lockout failures (0 retries).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from core.handlers.otp_primary import MagicLinkRequired, OTPPrimaryRequired
from core.handlers.passkey import PasskeyRequired

logger = logging.getLogger(__name__)

T = TypeVar("T")


# --- Exception Hierarchy ---


class LoginEngineError(Exception):
    """Base class for all Tracepass login engine exceptions."""


class CredentialRejected(LoginEngineError):
    """Raised when server rejects provided credentials (e.g. wrong password or invalid username)."""


class PageLoadTimeout(LoginEngineError):
    """Raised when initial page load or network navigation times out."""


class MultiStepTransitionTimeout(LoginEngineError):
    """Raised when multi-step split login fails to navigate or inject password input within deadline."""


class CaptchaRequired(LoginEngineError):
    """Raised when a CAPTCHA challenge is presented and cannot be solved automatically."""


class TwoFactorTimeout(LoginEngineError):
    """Raised when interactive 2FA / TOTP input prompt times out."""


class AccountLocked(LoginEngineError):
    """Raised when account is locked or rate-limited by the target service."""


class LoginFormNotFound(LoginEngineError):
    """Raised when no username/password form or modal trigger is detected on the page."""


class NavigationLoopDetected(LoginEngineError):
    """Raised when navigation depth exceeds maximum redirect limit (e.g. infinite loop)."""


class BotDetectionBlocked(LoginEngineError):
    """Raised when anti-bot challenges (Cloudflare Turnstile, Datadome, Akamai) block access."""


class TwoFactorRequired(LoginEngineError):
    """Raised when 2FA TOTP code is required post-password submission."""


class SMSOTPRequired(LoginEngineError):
    """Raised when SMS verification code is required."""


class EmailVerificationRequired(LoginEngineError):
    """Raised when email confirmation link must be clicked."""


class PasswordExpired(LoginEngineError):
    """Raised when password reset is enforced by server."""


class DeviceTrustRequired(LoginEngineError):
    """Raised when unrecognized device verification is triggered."""


class GeoRestricted(LoginEngineError):
    """Raised when site blocks access based on geographic region."""


class MaxAuthDepthExceeded(LoginEngineError):
    """Raised when cascading authentication steps exceed maximum allowed depth."""


class AuthenticationRequired(LoginEngineError):
    """Raised when no session or credentials exist for a domain."""


# Re-export handler exceptions under LoginEngineError
__all__ = [
    "AccountLocked",
    "AuthenticationRequired",
    "BotDetectionBlocked",
    "CaptchaRequired",
    "CredentialRejected",
    "DeviceTrustRequired",
    "EmailVerificationRequired",
    "GeoRestricted",
    "LoginFormNotFound",
    "LoginEngineError",
    "MagicLinkRequired",
    "MaxAuthDepthExceeded",
    "MultiStepTransitionTimeout",
    "NavigationLoopDetected",
    "OTPPrimaryRequired",
    "PageLoadTimeout",
    "PasskeyRequired",
    "PasswordExpired",
    "RetryDecision",
    "RetryPolicy",
    "SMSOTPRequired",
    "TwoFactorRequired",
    "TwoFactorTimeout",
]


# --- Retry Decision & Policy ---


@dataclass(frozen=True)
class RetryDecision:
    """Result of evaluating an exception against the Retry Policy."""

    should_retry: bool
    delay_seconds: float = 0.0
    reload_from_scratch: bool = False
    reason: str = ""


class RetryPolicy:
    """Evaluates login failures and enforces failure-type-specific retry rules per Decision 5."""

    DEFAULT_REASON_MAP: dict[type[BaseException], str] = {
        CredentialRejected: "Never retry. Raise immediately.",
        PageLoadTimeout: "Retry once after 3-second delay.",
        MultiStepTransitionTimeout: "Retry once by reloading from scratch.",
        CaptchaRequired: "Pause for solver or user. No auto-retry.",
        TwoFactorTimeout: "Abort. Raise immediately.",
        AccountLocked: "Abort immediately with cooldown info.",
        LoginFormNotFound: "Abort immediately.",
        NavigationLoopDetected: "Abort immediately.",
    }

    def __init__(
        self,
        max_retries_map: dict[type[BaseException], int] | None = None,
        default_max_retries: int = 0,
    ) -> None:
        """Initializes RetryPolicy.

        Args:
            max_retries_map: Optional custom mapping of exception types to allowed retry counts.
            default_max_retries: Default retry count for unlisted exceptions (default 0).
        """
        self.max_retries_map = max_retries_map or {
            PageLoadTimeout: 1,
            MultiStepTransitionTimeout: 1,
        }
        self.default_max_retries = default_max_retries

    def get_decision(self, exception: BaseException, attempt: int = 1) -> RetryDecision:
        """Evaluates an exception and attempt count against Decision 5 rules.

        Args:
            exception: The caught exception instance.
            attempt: Current attempt count (1-indexed). Attempt 1 is the initial run.

        Returns:
            RetryDecision: Details on whether to retry, delay duration, and reload behavior.
        """
        exc_type = type(exception)
        allowed_retries = self.max_retries_map.get(exc_type, self.default_max_retries)
        doc_reason = self.DEFAULT_REASON_MAP.get(exc_type, "Abort immediately.")

        if attempt > allowed_retries:
            return RetryDecision(
                should_retry=False,
                delay_seconds=0.0,
                reload_from_scratch=False,
                reason=f"Exceeded max retries ({allowed_retries}) for {exc_type.__name__}. {doc_reason}",
            )

        if exc_type is PageLoadTimeout:
            return RetryDecision(
                should_retry=True,
                delay_seconds=3.0,
                reload_from_scratch=False,
                reason=doc_reason,
            )

        if exc_type is MultiStepTransitionTimeout:
            return RetryDecision(
                should_retry=True,
                delay_seconds=0.0,
                reload_from_scratch=True,
                reason=doc_reason,
            )

        return RetryDecision(
            should_retry=False,
            delay_seconds=0.0,
            reload_from_scratch=False,
            reason=doc_reason,
        )

    async def execute_with_retry(
        self,
        async_func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Executes an async callable with automatic retry according to Decision 5.

        Args:
            async_func: Async function to execute.
            *args: Positional arguments for async_func.
            **kwargs: Keyword arguments for async_func.

        Returns:
            Any: The return value of async_func.

        Raises:
            BaseException: Re-raises the last exception when retries are exhausted or prohibited.
        """
        attempt = 1
        while True:
            try:
                return await async_func(*args, **kwargs)
            except Exception as exc:
                decision = self.get_decision(exc, attempt=attempt)
                logger.warning(
                    "Attempt %d failed with %s: %s (should_retry=%s)",
                    attempt,
                    type(exc).__name__,
                    exc,
                    decision.should_retry,
                )

                if not decision.should_retry:
                    raise

                if decision.delay_seconds > 0:
                    await asyncio.sleep(decision.delay_seconds)

                attempt += 1
