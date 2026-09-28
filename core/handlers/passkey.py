"""Passkey and WebAuthn (Type 9) Flow Handler with Fallback Detection.

Implements Section 2 (Type 9) of docs/login-engine.md:
- Detects WebAuthn / Passkey prompts.
- Scans for accessible password / OTP fallback options ('Use password instead', 'Try another way').
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
        r"(use.*password|try another way|sign in.*differently|use.*different.*method|enter password|other options)",
        re.IGNORECASE,
    )

    def __init__(self, timeout_ms: int = 8000) -> None:
        """Initializes PasskeyHandler.

        Args:
            timeout_ms: Timeout in milliseconds to wait for fallback transition.
        """
        self.timeout_ms = timeout_ms

    async def handle_passkey_or_fallback(
        self,
        page: Any,
        domain: str,
        fields: dict[str, str | None] | None = None,
    ) -> bool:
        """Checks for password fallback option on passkey prompt and clicks it.

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

        if explicit_fallback_sel:
            logger.info("Clicking explicit passkey fallback selector: %s", explicit_fallback_sel)
            fallback_btn = page.locator(explicit_fallback_sel).first
            await fallback_btn.hover()
            await fallback_btn.click()
            await page.wait_for_load_state("domcontentloaded")
            return True

        # Search for fallback links or buttons matching text patterns
        logger.info("Scanning for visible passkey fallback links/buttons on %s", domain)
        fallback_candidates = page.locator("a, button, [role='button']")
        count = await fallback_candidates.count()

        for i in range(count):
            candidate = fallback_candidates.nth(i)
            if not await candidate.is_visible():
                continue

            text = (await candidate.text_content() or "").strip()
            if self.FALLBACK_REGEX.search(text):
                logger.info("Found passkey fallback element with text '%s'; clicking", text)
                await candidate.hover()
                await candidate.click()
                await page.wait_for_load_state("domcontentloaded")
                return True

        logger.warning("No password fallback available on passkey prompt for domain: %s", domain)
        raise PasskeyRequired(domain)
