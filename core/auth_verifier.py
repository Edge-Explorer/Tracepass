"""Authentication Verifier (Component E).

Implements Component E of docs/login-engine.md:
- Provides per-domain registered verification checks supporting both async and sync callable objects.
- Inspects visible error alerts/banners (ignoring hidden DOM nodes).
- Verifies explicit logout controls (e.g., 'Log out', 'Sign out') without false positives on generic navigation links.
- Inspects all candidate elements across the document.
- Checks domain-relevant authentication cookies and JWT storage tokens.
"""

from __future__ import annotations

import inspect
import logging
import re
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class AuthVerifier:
    """Verifies whether a login attempt successfully transitioned the page to an authenticated state."""

    ERROR_TEXT_REGEX = re.compile(
        r"(incorrect\s+(password|username|email|credentials)|invalid\s+(password|username|email|credentials|login)|"
        r"wrong\s+password|login\s+failed|could\s+not\s+log\s+in|authentication\s+failed|bad\s+credentials)",
        re.IGNORECASE,
    )

    LOGOUT_CONTROL_REGEX = re.compile(
        r"^(log\s*out|sign\s*out|logout|signout|disconnect|switch\s+account)$",
        re.IGNORECASE,
    )

    AUTH_TOKEN_REGEX = re.compile(
        r"(auth|token|session|jwt|sid|access_token|user_id|logged_in|credential|id_token)",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        """Initializes AuthVerifier with an empty per-domain registry."""
        self._domain_verifiers: dict[str, Callable[[Any], Any]] = {}

    def register_verifier(self, domain: str, verifier_fn: Callable[[Any], Any]) -> None:
        """Registers a domain-specific verification callback.

        Args:
            domain: Domain string or normalized host (e.g., 'github.com').
            verifier_fn: Async or sync callable taking (page) and returning bool.
        """
        clean_domain = domain.strip().lower()
        if "://" in clean_domain:
            clean_domain = clean_domain.split("://", 1)[1]
        clean_domain = clean_domain.split("/", 1)[0].split(":")[0]
        self._domain_verifiers[clean_domain] = verifier_fn

    async def verify(
        self,
        page: Any,
        domain: str,
        cookies: list[dict[str, Any]] | None = None,
        local_storage: dict[str, Any] | None = None,
    ) -> bool:
        """Verifies authentication state for the given page and domain.

        Args:
            page: Playwright Page instance.
            domain: Target domain or origin URL.
            cookies: Optional list of browser cookies captured post-login.
            local_storage: Optional localStorage dictionary captured post-login.

        Returns:
            bool: True if authentication is verified; False otherwise.
        """
        clean_domain = domain.strip().lower()
        if "://" in clean_domain:
            clean_domain = clean_domain.split("://", 1)[1]
        clean_domain = clean_domain.split("/", 1)[0].split(":")[0]

        # 1. Run domain-specific verifier if registered
        if clean_domain in self._domain_verifiers:
            logger.info("Executing registered verifier for domain: %s", clean_domain)
            verifier_fn = self._domain_verifiers[clean_domain]
            try:
                result = verifier_fn(page)
                if inspect.isawaitable(result):
                    result = await result
                return bool(result)
            except Exception as e:
                logger.warning("Custom verifier for %s raised exception: %s", clean_domain, e)
                return False

        # 2. Generic Heuristic Verification
        logger.info("Running generic heuristic auth verification for domain: %s", clean_domain)
        return await self._generic_heuristic_check(page, cookies, local_storage)

    async def _generic_heuristic_check(
        self,
        page: Any,
        cookies: list[dict[str, Any]] | None = None,
        local_storage: dict[str, Any] | None = None,
    ) -> bool:
        """Applies multi-signal heuristic rules to verify login success."""
        # Signal A: Check for VISIBLE error alerts/banners
        try:
            error_candidates = page.locator(
                "[role='alert'], .error, .alert, .error-message, .form-error, .login-error, [aria-live='assertive']"
            )
            count = await error_candidates.count()
            for i in range(count):
                cand = error_candidates.nth(i)
                if await cand.is_visible():
                    cand_text = (await cand.text_content() or "").strip()
                    if self.ERROR_TEXT_REGEX.search(cand_text):
                        logger.warning(
                            "Generic verifier detected visible login error banner: '%s'", cand_text
                        )
                        return False
        except Exception:
            pass

        # Signal B: Check if password input is still visible on the page
        password_still_visible = False
        try:
            pass_inputs = page.locator("input[type='password']")
            count = await pass_inputs.count()
            for i in range(count):
                if await pass_inputs.nth(i).is_visible():
                    password_still_visible = True
                    break
        except Exception:
            pass

        if password_still_visible:
            logger.warning("Generic verifier detected visible password input still present")
            return False

        # Signal C: Check for explicit, visible logout controls
        try:
            auth_candidates = page.locator("a, button, [role='button']")
            count = await auth_candidates.count()
            for i in range(count):
                elem = auth_candidates.nth(i)
                if not await elem.is_visible():
                    continue
                text = (await elem.text_content() or "").strip()
                aria_label = (await elem.get_attribute("aria-label") or "").strip()
                if self.LOGOUT_CONTROL_REGEX.search(text) or self.LOGOUT_CONTROL_REGEX.search(
                    aria_label
                ):
                    logger.info(
                        "Generic verifier matched explicit logout control: '%s'", text or aria_label
                    )
                    return True
        except Exception:
            pass

        # Signal D: Check for domain-relevant auth cookies or JWT storage tokens
        has_auth_cookies = any(
            self.AUTH_TOKEN_REGEX.search(c.get("name", "")) for c in (cookies or [])
        )
        has_auth_storage = any(self.AUTH_TOKEN_REGEX.search(k) for k in (local_storage or {}))

        if has_auth_cookies or has_auth_storage:
            logger.info(
                "Generic verifier confirmed auth state via credentials (auth_cookies: %s, auth_storage: %s)",
                has_auth_cookies,
                has_auth_storage,
            )
            return True

        logger.warning("Generic verifier could not confirm authenticated state")
        return False
