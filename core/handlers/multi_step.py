"""Multi-Step / Split Login (Type 2) Flow Handler.

Implements Section 7.2 of docs/login-engine.md:
- Fills initial identifier (email/username) with humanized keystrokes.
- Races page navigation vs in-place DOM mutation using asyncio.FIRST_COMPLETED.
- Fills password upon transition resolution.
- Submits final form and waits for settlement.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

logger = logging.getLogger(__name__)


class MultiStepTransitionTimeout(Exception):
    """Raised when neither navigation nor password field appears after submitting the initial step."""


class MultiStepHandler:
    """Executes multi-step (Type 2) split login flows inside Scrapling page_action."""

    def __init__(
        self,
        username: str,
        password: str,
        typing_delay_ms: int = 90,
        transition_timeout_ms: int = 10000,
        password_wait_timeout_ms: int = 5000,
        timeout_ms: int = 15000,
    ) -> None:
        self.username = username
        self.password = password
        self.typing_delay_ms = typing_delay_ms
        self.transition_timeout_ms = transition_timeout_ms
        self.password_wait_timeout_ms = password_wait_timeout_ms
        self.timeout_ms = timeout_ms

    async def execute(self, page: Any, fields: dict[str, str | None]) -> bool:
        """Executes multi-step form fill and submission on the Playwright page.

        Args:
            page: The Playwright Page instance provided by Scrapling page_action.
            fields: The selector map resolved by FieldDetector (or partial map).

        Returns:
            bool: True if the actions executed and submitted without uncaught exceptions.

        Raises:
            ValueError: If username selector is missing.
            MultiStepTransitionTimeout: If the transition to the password step fails/times out.
        """
        username_sel = fields.get("username")
        next_sel = fields.get("next") or fields.get("submit")
        password_sel = fields.get("password") or "input[type='password']"
        final_submit_sel = fields.get("password_submit") or fields.get("submit")

        if not username_sel:
            raise ValueError(f"MultiStepHandler requires a username selector. Got: {fields}")

        # Step 1: Fill username / email
        logger.info("Filling step 1 username field: %s", username_sel)
        username_locator = page.locator(username_sel)
        await username_locator.click()
        await username_locator.press_sequentially(self.username, delay=self.typing_delay_ms)

        # Step 2: Race navigation vs. DOM mutation — arm BOTH waiters before triggering transition
        logger.info("Arming navigation and DOM mutation waiters for step 2 transition")
        nav_waiter = asyncio.ensure_future(
            page.wait_for_navigation(timeout=self.transition_timeout_ms)
        )
        selector_waiter = asyncio.ensure_future(
            page.wait_for_selector(
                password_sel, state="visible", timeout=self.transition_timeout_ms
            )
        )

        if next_sel:
            logger.info("Clicking step 1 next/submit button: %s", next_sel)
            next_locator = page.locator(next_sel)
            await next_locator.hover()
            await next_locator.click()
        else:
            logger.info("Triggering step 1 transition via Enter key on username input")
            await username_locator.press("Enter")

        done, pending = await asyncio.wait(
            [nav_waiter, selector_waiter],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

        # Check if any task succeeded
        completed_tasks = [t for t in done if not t.cancelled() and t.exception() is None]
        if not completed_tasks:
            errors = [t.exception() for t in done if t.exception() is not None]
            raise MultiStepTransitionTimeout(
                f"Transition to password step timed out after {self.transition_timeout_ms}ms. Errors: {errors}"
            )

        if nav_waiter in completed_tasks:
            logger.info("Navigation transition resolved first. Waiting for password selector.")
            await page.wait_for_selector(
                password_sel, state="visible", timeout=self.password_wait_timeout_ms
            )
        else:
            logger.info("DOM mutation resolved first. Password selector is already visible.")

        # Step 3: Fill password
        logger.info("Filling step 2 password field: %s", password_sel)
        password_locator = page.locator(password_sel)
        await password_locator.click()
        await password_locator.press_sequentially(self.password, delay=self.typing_delay_ms)

        # Step 4: Final submit
        if final_submit_sel and final_submit_sel != next_sel:
            logger.info("Submitting step 2 form via button: %s", final_submit_sel)
            submit_locator = page.locator(final_submit_sel)
            await submit_locator.hover()
            await submit_locator.click()
        else:
            # Check if submit button exists, otherwise press Enter
            try:
                submit_locator = page.locator("button[type='submit'], input[type='submit']")
                if await submit_locator.count() > 0:
                    await submit_locator.first.hover()
                    await submit_locator.first.click()
                else:
                    logger.info("Submitting step 2 via Enter key on password input")
                    await password_locator.press("Enter")
            except Exception:
                logger.info("Fallback submitting step 2 via Enter key on password input")
                await password_locator.press("Enter")

        # Step 5: Wait for settlement
        try:
            await page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
        except Exception:
            logger.debug("networkidle timeout reached on step 2, continuing...")
            await page.wait_for_timeout(2000)

        return True
