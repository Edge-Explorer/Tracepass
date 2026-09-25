"""Modal and Overlay Login (Type 3) Flow Handler.

Implements Section 7.3 of docs/login-engine.md:
- Identifies and clicks the modal trigger button in navigation/header.
- Waits for the dialog container ([role='dialog'], [aria-modal='true']) to appear.
- Scopes field interaction strictly within the modal container.
- Fills credentials with humanized delays and submits.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ModalTriggerTimeout(Exception):
    """Raised when clicking the trigger fails to open a modal dialog within timeout."""


class ModalLoginHandler:
    """Executes modal and overlay (Type 3) login flows inside Scrapling page_action."""

    DEFAULT_MODAL_CONTAINER = "[role='dialog'], [aria-modal='true'], .modal, .dialog"

    def __init__(
        self,
        username: str,
        password: str,
        typing_delay_ms: int = 90,
        modal_timeout_ms: int = 8000,
        timeout_ms: int = 15000,
    ) -> None:
        self.username = username
        self.password = password
        self.typing_delay_ms = typing_delay_ms
        self.modal_timeout_ms = modal_timeout_ms
        self.timeout_ms = timeout_ms

    async def execute(self, page: Any, fields: dict[str, str | None]) -> bool:
        """Executes modal trigger, dialog wait, scoped form fill, and submission.

        Args:
            page: The Playwright Page instance provided by Scrapling page_action.
            fields: The selector map resolved by FieldDetector (contains modal_trigger, username, password, submit).

        Returns:
            bool: True if the actions executed and submitted successfully.

        Raises:
            ValueError: If username or password selector is missing.
            ModalTriggerTimeout: If the modal dialog fails to appear after clicking the trigger.
        """
        modal_trigger_sel = fields.get("modal_trigger")
        username_sel = fields.get("username")
        password_sel = fields.get("password")
        submit_sel = fields.get("submit")
        container_sel = fields.get("modal_container") or self.DEFAULT_MODAL_CONTAINER

        if not username_sel or not password_sel:
            raise ValueError(
                f"ModalLoginHandler requires both username and password selectors. Got: {fields}"
            )

        # Step 1: Click modal trigger if present
        if modal_trigger_sel:
            logger.info("Clicking modal trigger: %s", modal_trigger_sel)
            trigger_locator = page.locator(modal_trigger_sel)
            await trigger_locator.hover()
            await trigger_locator.click()

            # Step 2: Wait for modal container to become visible
            logger.info("Waiting for modal dialog container: %s", container_sel)
            try:
                await page.wait_for_selector(
                    container_sel, state="visible", timeout=self.modal_timeout_ms
                )
            except Exception as e:
                raise ModalTriggerTimeout(
                    f"Modal dialog did not appear within {self.modal_timeout_ms}ms after clicking {modal_trigger_sel}"
                ) from e

        # Step 3: Scope locators to the modal container if container is present on page
        modal_locator = page.locator(container_sel).first if modal_trigger_sel else page

        logger.info("Filling scoped username field: %s", username_sel)
        user_input = modal_locator.locator(username_sel)
        await user_input.click()
        await user_input.press_sequentially(self.username, delay=self.typing_delay_ms)

        logger.info("Filling scoped password field: %s", password_sel)
        pass_input = modal_locator.locator(password_sel)
        await pass_input.click()
        await pass_input.press_sequentially(self.password, delay=self.typing_delay_ms)

        # Step 4: Submit scoped form
        if submit_sel:
            logger.info("Submitting modal form via button: %s", submit_sel)
            submit_btn = modal_locator.locator(submit_sel)
            await submit_btn.hover()
            await submit_btn.click()
        else:
            logger.info("Submitting modal form via Enter key on password field")
            await pass_input.press("Enter")

        # Step 5: Wait for settlement
        try:
            await page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
        except Exception:
            logger.debug("networkidle timeout reached in modal login, continuing...")
            await page.wait_for_timeout(2000)

        return True
