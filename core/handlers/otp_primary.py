"""OTP-Primary and Magic Link (Type 8) Flow Handler.

Implements Section 2 (Type 8) & Section 11 (Decision 2) of docs/login-engine.md:
- Detects OTP-only and Magic Link authentication flows.
- Normalizes domain names to shell-safe uppercase environment variable keys (TRACEPASS_OTP_<SAFE_DOMAIN>).
- Automatically fills OTP codes from environment variables in CI/headless modes.
- Surfaces clear error boundaries (OTPPrimaryRequired / MagicLinkRequired) without crashing pipelines.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)


class OTPPrimaryRequired(Exception):
    """Raised when an OTP code is required but not provided in the environment or interactive prompt."""

    def __init__(self, domain: str, message: str | None = None) -> None:
        self.domain = domain
        super().__init__(
            message
            or f"OTP authentication required for '{domain}'. Set TRACEPASS_OTP_{OTPPrimaryHandler.normalize_domain_to_env_key(domain)} or provide code."
        )


class MagicLinkRequired(Exception):
    """Raised when a site requires an email magic link that cannot be opened autonomously."""

    def __init__(self, domain: str, message: str | None = None) -> None:
        self.domain = domain
        super().__init__(
            message
            or f"Magic link login required for '{domain}'. The engine cannot access email inboxes autonomously in v1."
        )


class OTPPrimaryHandler:
    """Handles detection and submission for OTP-primary (Type 8) authentication."""

    DEFAULT_OTP_SELECTOR = (
        "input[autocomplete='one-time-code'], input[name*='otp'], "
        "input[name*='code'], input[type='tel'], input[id*='otp'], input[id*='code']"
    )

    def __init__(
        self,
        typing_delay_ms: int = 50,
        timeout_ms: int = 15000,
    ) -> None:
        """Initializes OTPPrimaryHandler.

        Args:
            typing_delay_ms: Keystroke delay in milliseconds.
            timeout_ms: Max time to wait for network settlement post-submission.
        """
        self.typing_delay_ms = typing_delay_ms
        self.timeout_ms = timeout_ms

    @staticmethod
    def normalize_domain_to_env_key(domain: str) -> str:
        """Converts domain to a shell-safe uppercase environment variable suffix.

        Examples:
            'example.com' -> 'EXAMPLE_COM'
            'sub.site-app.org:8080' -> 'SUB_SITE_APP_ORG_8080'
        """
        clean_domain = domain.strip().lower()
        if "://" in clean_domain:
            clean_domain = clean_domain.split("://", 1)[1]
        clean_domain = clean_domain.split("/", 1)[0]
        # Replace non-alphanumerics with underscores
        safe_key = re.sub(r"[^a-zA-Z0-9]", "_", clean_domain).strip("_").upper()
        return safe_key

    def get_env_otp_code(self, domain: str) -> str | None:
        """Retrieves OTP code from TRACEPASS_OTP_<SAFE_DOMAIN> if set."""
        safe_key = self.normalize_domain_to_env_key(domain)
        env_var_name = f"TRACEPASS_OTP_{safe_key}"
        return os.environ.get(env_var_name)

    async def execute(
        self,
        page: Any,
        domain: str,
        fields: dict[str, str | None],
        is_magic_link: bool = False,
    ) -> bool:
        """Executes OTP-primary submission or raises explicit error boundaries.

        Args:
            page: Playwright Page instance.
            domain: Target domain or origin URL.
            fields: Selector map containing optional 'otp_input' and 'submit'.
            is_magic_link: Whether the flow is a magic link rather than an OTP code.

        Returns:
            bool: True if OTP was successfully retrieved and submitted.

        Raises:
            MagicLinkRequired: If the site uses magic link authentication.
            OTPPrimaryRequired: If no OTP code is found in environment.
        """
        if is_magic_link:
            raise MagicLinkRequired(domain)

        otp_code = self.get_env_otp_code(domain)
        if not otp_code:
            logger.warning("No OTP code found in environment for domain: %s", domain)
            raise OTPPrimaryRequired(domain)

        otp_input_sel = fields.get("otp_input") or self.DEFAULT_OTP_SELECTOR
        submit_sel = fields.get("submit")

        logger.info("Filling OTP code for %s using selector: %s", domain, otp_input_sel)
        otp_locator = page.locator(otp_input_sel).first
        await otp_locator.click()
        await otp_locator.press_sequentially(otp_code, delay=self.typing_delay_ms)

        if submit_sel:
            logger.info("Submitting OTP form via button: %s", submit_sel)
            submit_btn = page.locator(submit_sel).first
            await submit_btn.hover()
            await submit_btn.click()
        else:
            logger.info("Submitting OTP form via Enter key")
            await otp_locator.press("Enter")

        try:
            await page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
        except Exception:
            logger.debug("networkidle timeout reached in OTP submission, continuing...")
            await page.wait_for_timeout(2000)

        return True
