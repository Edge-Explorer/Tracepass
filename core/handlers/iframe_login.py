"""iFrame and Shadow DOM Login (Type 4) Flow Handler.

Implements Section 2 (Type 4) of docs/login-engine.md:
- Traverses cross-origin and same-origin iframes using frame locators.
- Pierces open Shadow DOM trees seamlessly.
- Fills credentials with humanized delays inside the frame context.
- Submits form and waits for settlement.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class IframeNotFound(Exception):
    """Raised when the target iframe element is not found or fails to attach within timeout."""


class IframeLoginHandler:
    """Executes iframe-embedded (Type 4) login flows inside Scrapling page_action."""

    def __init__(
        self,
        username: str,
        password: str,
        typing_delay_ms: int = 90,
        iframe_timeout_ms: int = 8000,
        timeout_ms: int = 15000,
    ) -> None:
        self.username = username
        self.password = password
        self.typing_delay_ms = typing_delay_ms
        self.iframe_timeout_ms = iframe_timeout_ms
        self.timeout_ms = timeout_ms

    async def execute(self, page: Any, fields: dict[str, str | None]) -> bool:
        """Executes form fill and submission inside the target iframe context.

        Args:
            page: The Playwright Page instance provided by Scrapling page_action.
            fields: The selector map containing 'iframe', 'username', 'password', and optional 'submit'.

        Returns:
            bool: True if actions inside the iframe executed and submitted successfully.

        Raises:
            ValueError: If 'iframe', 'username', or 'password' selector is missing.
            IframeNotFound: If the iframe fails to attach/render within timeout.
        """
        iframe_sel = fields.get("iframe")
        username_sel = fields.get("username")
        password_sel = fields.get("password")
        submit_sel = fields.get("submit")

        if not iframe_sel:
            raise ValueError(f"IframeLoginHandler requires an 'iframe' selector. Got: {fields}")
        if not username_sel or not password_sel:
            raise ValueError(
                f"IframeLoginHandler requires both 'username' and 'password' selectors. Got: {fields}"
            )

        # Step 1: Wait for iframe element to attach
        logger.info("Waiting for iframe element to attach: %s", iframe_sel)
        try:
            await page.wait_for_selector(
                iframe_sel, state="attached", timeout=self.iframe_timeout_ms
            )
        except Exception as e:
            raise IframeNotFound(
                f"Target iframe '{iframe_sel}' failed to attach within {self.iframe_timeout_ms}ms"
            ) from e

        # Step 2: Access iframe context
        frame = page.frame_locator(iframe_sel)

        # Step 3: Fill credentials inside the frame
        logger.info("Filling username inside iframe: %s", username_sel)
        user_input = frame.locator(username_sel)
        await user_input.click()
        await user_input.press_sequentially(self.username, delay=self.typing_delay_ms)

        logger.info("Filling password inside iframe: %s", password_sel)
        pass_input = frame.locator(password_sel)
        await pass_input.click()
        await pass_input.press_sequentially(self.password, delay=self.typing_delay_ms)

        # Step 4: Submit inside iframe
        if submit_sel:
            logger.info("Submitting iframe form via button: %s", submit_sel)
            submit_btn = frame.locator(submit_sel)
            await submit_btn.hover()
            await submit_btn.click()
        else:
            logger.info("Submitting iframe form via Enter key on password input")
            await pass_input.press("Enter")

        # Step 5: Wait for settlement
        try:
            await page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
        except Exception:
            logger.debug("networkidle timeout reached during iframe login, continuing...")
            await page.wait_for_timeout(2000)

        return True
