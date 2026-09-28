"""Authentication Verifier (Component E).

Implements Component E of docs/login-engine.md:
- Provides per-domain registered verification checks.
- Provides a robust generic fallback heuristic checking DOM state, cookies, storage tokens, and error banners.
- Distinguishes authenticated sessions from rejected credentials or hanging forms.
"""

from __future__ import annotations

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

    AUTH_SIGNAL_REGEX = re.compile(
        r"(log\s*out|sign\s*out|my\s+account|dashboard|profile|logged\s+in\s+as)",
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
                import inspect

                if inspect.iscoroutinefunction(verifier_fn):
                    return bool(await verifier_fn(page))
                return bool(verifier_fn(page))
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
        # Signal A: Check for explicit error banners/text on the page
        try:
            body_text = await page.locator("body").text_content(timeout=3000) or ""
            if self.ERROR_TEXT_REGEX.search(body_text):
                logger.warning("Generic verifier detected login error banner in page body text")
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

        # Signal C: Check for authenticated keywords (Logout, Account, Profile)
        try:
            auth_candidates = page.locator("a, button, [role='button'], nav, header")
            count = await auth_candidates.count()
            for i in range(min(count, 30)):
                elem = auth_candidates.nth(i)
                if not await elem.is_visible():
                    continue
                text = (await elem.text_content() or "").strip()
                if self.AUTH_SIGNAL_REGEX.search(text):
                    logger.info("Generic verifier matched auth signal element: '%s'", text)
                    return True
        except Exception:
            pass

        # Signal D: Check cookie / storage token state
        has_auth_cookies = bool(cookies and len(cookies) > 0)
        has_storage_token = bool(local_storage and len(local_storage) > 0)

        if has_auth_cookies or has_storage_token:
            logger.info(
                "Generic verifier confirmed session state (cookies: %s, storage: %s)",
                has_auth_cookies,
                has_storage_token,
            )
            return True

        logger.warning("Generic verifier could not confirm authenticated state")
        return False
