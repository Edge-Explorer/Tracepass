"""Single-Step (Type 1) Standard Login Flow Handler.

Implements Section 7.1 of docs/login-engine.md:
- Types username and password with humanized keystroke delays.
- Clicks the submit button with mouse hover or falls back to Enter key.
- Waits for network idle / URL navigation state.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SingleStepHandler:
    """Executes single-step (Type 1) login flows inside Scrapling page_action."""

    def __init__(
        self,
        username: str,
        password: str,
        typing_delay_ms: int = 90,
        timeout_ms: int = 15000,
    ) -> None:
        self.username = username
        self.password = password
        self.typing_delay_ms = typing_delay_ms
        self.timeout_ms = timeout_ms

    async def execute(self, page: Any, fields: dict[str, str | None]) -> bool:
        """Executes form fill and submission on the Playwright page.

        Args:
            page: The Playwright Page instance provided by Scrapling page_action.
            fields: The selector map resolved by FieldDetector.

        Returns:
            bool: True if the actions executed and submitted without uncaught exceptions.
        """
        username_sel = fields.get("username")
        password_sel = fields.get("password")
        submit_sel = fields.get("submit")

        if not username_sel or not password_sel:
            raise ValueError(
                f"SingleStepHandler requires both username and password selectors. Got: {fields}"
            )

        logger.info("Filling username field: %s", username_sel)
        username_locator = page.locator(username_sel)
        await username_locator.click()
        await username_locator.press_sequentially(self.username, delay=self.typing_delay_ms)

        logger.info("Filling password field: %s", password_sel)
        password_locator = page.locator(password_sel)
        await password_locator.click()
        await password_locator.press_sequentially(self.password, delay=self.typing_delay_ms)

        if submit_sel:
            logger.info("Submitting form via button: %s", submit_sel)
            submit_locator = page.locator(submit_sel)
            await submit_locator.hover()
            await submit_locator.click()
        else:
            logger.info("Submitting form via Enter key on password input")
            await password_locator.press("Enter")

        # Wait for navigation / network requests to settle
        try:
            await page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
        except Exception:
            # Some SPAs don't trigger full networkidle, wait fallback
            logger.debug("networkidle timeout reached, continuing...")
            await page.wait_for_timeout(2000)

        return True
