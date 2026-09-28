"""Single Sign-On and OAuth Federation (Type 5) Flow Handler.

Implements Section 2 (Type 5) & Section 7.4 of docs/login-engine.md:
- Arms popup and navigation event listeners before clicking SSO buttons.
- Handles third-party identity provider login in popup window or redirect chain.
- Waits for popup closure and parent page settlement.
"""

from __future__ import annotations

import logging
from typing import Any

from core.handlers.single_step import SingleStepHandler

logger = logging.getLogger(__name__)


class OAuthProviderNotFound(Exception):
    """Raised when the SSO/OAuth trigger button is not found or fails to render."""


class OAuthFlowTimeout(Exception):
    """Raised when the OAuth popup or redirect fails to open/settle within timeout."""


class OAuthLoginHandler:
    """Executes Single Sign-On and OAuth 2.0 (Type 5) login flows inside Scrapling page_action."""

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        typing_delay_ms: int = 90,
        popup_timeout_ms: int = 10000,
        redirect_timeout_ms: int = 15000,
        timeout_ms: int = 15000,
    ) -> None:
        """Initializes OAuth login handler with provider credentials and timeouts.

        Args:
            username: Username/email for the third-party identity provider.
            password: Password for the third-party identity provider.
            typing_delay_ms: Keystroke delay in milliseconds.
            popup_timeout_ms: Max time to wait for popup window creation.
            redirect_timeout_ms: Max time to wait for OAuth redirect round-trip.
            timeout_ms: Max time to wait for network settlement.
        """
        self.username = username
        self.password = password
        self.typing_delay_ms = typing_delay_ms
        self.popup_timeout_ms = popup_timeout_ms
        self.redirect_timeout_ms = redirect_timeout_ms
        self.timeout_ms = timeout_ms

    async def execute(
        self,
        page: Any,
        fields: dict[str, str | None],
        is_popup: bool = True,
        idp_fields: dict[str, str | None] | None = None,
    ) -> bool:
        """Executes OAuth SSO flow via popup window or redirect chain.

        Args:
            page: The Playwright Page instance provided by Scrapling page_action.
            fields: Selector map containing 'sso_button'.
            is_popup: Whether the SSO provider opens in a popup window (True) or same-tab redirect (False).
            idp_fields: Optional selector map for inputs on the third-party identity provider page.

        Returns:
            bool: True if OAuth flow completed and parent page settled.

        Raises:
            ValueError: If 'sso_button' selector is missing.
            OAuthFlowTimeout: If popup or redirect fails within timeout.
        """
        sso_button_sel = fields.get("sso_button") or fields.get("submit")
        if not sso_button_sel:
            raise ValueError(f"OAuthLoginHandler requires an 'sso_button' selector. Got: {fields}")

        sso_locator = page.locator(sso_button_sel)

        if is_popup:
            logger.info("Arming popup listener and clicking SSO button: %s", sso_button_sel)
            try:
                async with page.context.expect_event(
                    "page", timeout=self.popup_timeout_ms
                ) as popup_info:
                    await sso_locator.hover()
                    await sso_locator.click()
                popup_page = await popup_info.value
            except Exception as e:
                raise OAuthFlowTimeout(
                    f"OAuth popup failed to open within {self.popup_timeout_ms}ms after clicking {sso_button_sel}"
                ) from e

            # Wait for popup DOM to be ready
            await popup_page.wait_for_load_state("domcontentloaded")

            # If credentials and IdP selectors provided, execute login inside popup
            if self.username and self.password and idp_fields:
                logger.info("Executing IdP credentials fill inside popup page")
                idp_handler = SingleStepHandler(
                    username=self.username,
                    password=self.password,
                    typing_delay_ms=self.typing_delay_ms,
                    timeout_ms=self.timeout_ms,
                )
                await idp_handler.execute(popup_page, idp_fields)

            # Wait for popup to close automatically upon OAuth completion
            try:
                await popup_page.wait_for_event("close", timeout=self.redirect_timeout_ms)
            except Exception:
                logger.debug("Popup did not close automatically; closing manually if open")
                if not popup_page.is_closed():
                    await popup_page.close()

            # Wait for original page to settle post-OAuth
            try:
                await page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
            except Exception:
                logger.debug("networkidle timeout on parent page post-OAuth, continuing...")
                await page.wait_for_timeout(2000)

            return True

        # Redirect mode (same-tab)
        logger.info("Executing same-tab OAuth redirect flow on button: %s", sso_button_sel)
        try:
            nav_waiter = page.wait_for_navigation(timeout=self.redirect_timeout_ms)
            await sso_locator.hover()
            await sso_locator.click()
            await nav_waiter
        except Exception as e:
            raise OAuthFlowTimeout(
                f"OAuth redirect failed to navigate within {self.redirect_timeout_ms}ms"
            ) from e

        # If IdP fields and credentials provided on redirect page
        if self.username and self.password and idp_fields:
            logger.info("Executing IdP credentials fill on redirect page")
            idp_handler = SingleStepHandler(
                username=self.username,
                password=self.password,
                typing_delay_ms=self.typing_delay_ms,
                timeout_ms=self.timeout_ms,
            )
            await idp_handler.execute(page, idp_fields)

        try:
            await page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
        except Exception:
            logger.debug("networkidle timeout on redirect page post-OAuth, continuing...")
            await page.wait_for_timeout(2000)

        return True
