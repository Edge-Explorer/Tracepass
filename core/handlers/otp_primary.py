"""OTP-Primary and Magic Link (Type 8) Flow Handler.

Implements Section 2 (Type 8) & Section 11 (Decision 2) of docs/login-engine.md:
- Detects OTP-only and Magic Link authentication flows.
- Normalizes domain names to shell-safe uppercase environment variable keys.
- Validates page origin before injecting OTP secrets.
- Supports interactive terminal input when running locally and automated env bypass in CI.
- Surfaces clear error boundaries (OTPPrimaryRequired / MagicLinkRequired) without crashing pipelines.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from typing import Any
from urllib.parse import urlparse

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


class OTPOriginMismatch(Exception):
    """Raised when the active page origin does not match the target authentication domain."""


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
        allow_interactive: bool = True,
    ) -> None:
        """Initializes OTPPrimaryHandler.

        Args:
            typing_delay_ms: Keystroke delay in milliseconds.
            timeout_ms: Max time to wait for network settlement post-submission.
            allow_interactive: Whether to prompt via terminal input when env var is missing.
        """
        self.typing_delay_ms = typing_delay_ms
        self.timeout_ms = timeout_ms
        self.allow_interactive = allow_interactive

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
        safe_key = re.sub(r"[^a-zA-Z0-9]", "_", clean_domain).strip("_").upper()
        return safe_key

    @staticmethod
    def get_collision_free_env_key(domain: str) -> str:
        """Generates unambiguous collision-free env key distinguishing dots from hyphens.

        Example:
            'foo-bar.com' -> 'TRACEPASS_OTP_FOO_DASH_BAR_DOT_COM'
            'foo.bar.com' -> 'TRACEPASS_OTP_FOO_DOT_BAR_DOT_COM'
        """
        clean_domain = domain.strip().lower()
        if "://" in clean_domain:
            clean_domain = clean_domain.split("://", 1)[1]
        clean_domain = clean_domain.split("/", 1)[0]
        encoded = clean_domain.replace(".", "_DOT_").replace("-", "_DASH_").replace(":", "_PORT_")
        encoded = re.sub(r"[^a-zA-Z0-9_]", "_", encoded).upper()
        return f"TRACEPASS_OTP_{encoded}"

    def resolve_otp_code(self, domain: str) -> str | None:
        """Retrieves OTP code from environment variable or interactive terminal prompt."""
        # 1. Check collision-free specific env key first
        collision_free_key = self.get_collision_free_env_key(domain)
        code = os.environ.get(collision_free_key)
        if code and code.strip():
            logger.info("Found OTP code in specific env var %s", collision_free_key)
            return code.strip()

        # 2. Check standard safe env key
        safe_key = self.normalize_domain_to_env_key(domain)
        standard_key = f"TRACEPASS_OTP_{safe_key}"
        code = os.environ.get(standard_key)
        if code and code.strip():
            logger.info("Found OTP code in standard env var %s", standard_key)
            return code.strip()

        # 3. Interactive terminal prompt if running locally
        if self.allow_interactive and sys.stdin and sys.stdin.isatty():
            try:
                print(f"\n[Tracepass] Authentication code required for: {domain}")
                user_code = input("[Tracepass] Enter 6-digit OTP / SMS code: ").strip()
                if user_code:
                    return user_code
            except (EOFError, KeyboardInterrupt):
                logger.warning("Interactive OTP prompt cancelled by user")
                return None

        return None

    def verify_page_origin(self, page_url: str | None, target_domain: str) -> None:
        """Ensures active page origin matches target authentication domain before typing secrets."""
        if not page_url or page_url in ("about:blank", ""):
            return

        parsed_page = urlparse(page_url)
        page_netloc = (parsed_page.netloc or "").split(":")[0].lower()
        clean_target = target_domain.strip().lower()
        if "://" in clean_target:
            clean_target = clean_target.split("://", 1)[1]
        clean_target = clean_target.split("/", 1)[0].split(":")[0]

        if page_netloc and not (
            page_netloc == clean_target or page_netloc.endswith(f".{clean_target}")
        ):
            logger.warning(
                "Origin mismatch: active page '%s' does not match target '%s'",
                page_netloc,
                clean_target,
            )
            raise OTPOriginMismatch(
                f"Active page origin '{page_netloc}' does not match expected target domain '{clean_target}'"
            )

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
            OTPPrimaryRequired: If no OTP code is provided.
            OTPOriginMismatch: If active page origin is mismatched.
        """
        if is_magic_link:
            raise MagicLinkRequired(domain)

        # Validate origin binding before retrieving or typing secret
        page_url = getattr(page, "url", None)
        self.verify_page_origin(page_url, domain)

        otp_code = self.resolve_otp_code(domain)
        if not otp_code:
            logger.warning("No OTP code provided for domain: %s", domain)
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
