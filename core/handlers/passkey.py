"""Passkey and WebAuthn (Type 9) Flow Handler with Fallback Detection.

Implements Section 2 (Type 9) of docs/login-engine.md:
- Detects WebAuthn / Passkey prompts.
- Scans for accessible password / OTP fallback options ('Use password instead', 'Try another way', 'Use verification code').
- Inspects accessible names, aria-labels, and inner text.
- Automatically transitions the page to automatable password-based login.
- Raises PasskeyRequired only when no automatable fallback exists.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class PasskeyRequired(Exception):
    """Raised when a site requires hardware passkey authentication with no fallback."""

    def __init__(self, domain: str, message: str | None = None) -> None:
        self.domain = domain
        super().__init__(
            message
            or f"Passkey authentication required for '{domain}'. No automatable password or OTP fallback was available."
        )


class PasskeyHandler:
    """Handles Passkey / WebAuthn detection and fallback resolution."""

    FALLBACK_REGEX = re.compile(
        r"(use.*password|try another way|sign in.*differently|use.*different.*method|"
        r"enter password|other options|verification code|one-time code|send.*code|"
        r"use.*code|use.*otp|use.*sms|text.*code)",
        re.IGNORECASE,
    )

    DEFAULT_FALLBACK_INPUTS = (
        "input[type='password'], input[type='text'], input[type='email'], "
        "input[autocomplete='one-time-code']"
    )

    def __init__(self, timeout_ms: int = 8000) -> None:
        """Initializes PasskeyHandler.

        Args:
            timeout_ms: Timeout in milliseconds to wait for fallback transition.
        """
        self.timeout_ms = timeout_ms

    async def _wait_for_fallback_transition(self, page: Any) -> None:
        """Waits for password or OTP input controls to render after clicking fallback."""
        try:
            await page.wait_for_selector(
                self.DEFAULT_FALLBACK_INPUTS,
                state="visible",
                timeout=self.timeout_ms,
            )
        except Exception:
            logger.debug(
                "Fallback input selector not immediately visible within %sms, waiting for network settle",
                self.timeout_ms,
            )
            try:
                await page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
            except Exception:
                await page.wait_for_timeout(1000)

    async def handle_passkey_or_fallback(
        self,
        page: Any,
        domain: str,
        fields: dict[str, str | None] | None = None,
    ) -> bool:
        """Checks for password/OTP fallback option on passkey prompt and clicks it.

        Args:
            page: Playwright Page instance.
            domain: Target domain or origin URL.
            fields: Optional selector map containing explicit 'fallback_button'.

        Returns:
            bool: True if a fallback was found and clicked, transitioning page to password flow.

        Raises:
            PasskeyRequired: If no fallback option is available on the passkey prompt.
        """
        explicit_fallback_sel = fields.get("fallback_button") if fields else None

        # 1. Try explicit fallback selector if provided and currently present
        if explicit_fallback_sel:
            try:
                explicit_locator = page.locator(explicit_fallback_sel).first
                if await explicit_locator.count() > 0 and await explicit_locator.is_visible():
                    logger.info(
                        "Clicking explicit passkey fallback selector: %s", explicit_fallback_sel
                    )
                    await explicit_locator.hover()
                    await explicit_locator.click()
                    await self._wait_for_fallback_transition(page)
                    return True
                logger.debug(
                    "Configured explicit fallback '%s' not visible in DOM, scanning page...",
                    explicit_fallback_sel,
                )
            except Exception as e:
                logger.debug("Explicit fallback check failed (%s), proceeding to scan...", e)

        # 2. Scan for fallback links, buttons, or role=button matching text & accessible names
        logger.info("Scanning for visible passkey fallback controls on %s", domain)
        fallback_candidates = page.locator(
            "a, button, [role='button'], input[type='button'], input[type='submit']"
        )
        count = await fallback_candidates.count()

        for i in range(count):
            candidate = fallback_candidates.nth(i)
            if not await candidate.is_visible():
                continue

            # Check text content, aria-label, title, and value attributes for accessible names
            text_parts = [
                await candidate.text_content() or "",
                await candidate.get_attribute("aria-label") or "",
                await candidate.get_attribute("title") or "",
                await candidate.get_attribute("value") or "",
            ]
            combined_text = " ".join(t.strip() for t in text_parts if t.strip())

            if self.FALLBACK_REGEX.search(combined_text):
                logger.info(
                    "Found passkey fallback element with accessible text '%s'; clicking",
                    combined_text,
                )
                await candidate.hover()
                await candidate.click()
                await self._wait_for_fallback_transition(page)
                return True

        logger.warning(
            "No password/OTP fallback available on passkey prompt for domain: %s", domain
        )
        raise PasskeyRequired(domain)

    async def execute(
        self,
        page: Any,
        domain: str,
        fields: dict[str, str | None] | None = None,
    ) -> bool:
        """Standard handler execute interface for PasskeyHandler."""
        return await self.handle_passkey_or_fallback(page, domain=domain, fields=fields)
