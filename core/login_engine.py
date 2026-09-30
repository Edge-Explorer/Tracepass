"""Master Orchestrator for Tracepass Autonomous Login Engine.

Implements Section 3 (Architecture) & Section 12 of docs/login-engine.md:
- Wires the 5-component autonomous login pipeline on top of Playwright / Scrapling.
- Stage 1: Session Cache Check (SessionManager) + Verification & Restoration
- Stage 2: Credential Resolution (CredentialManager)
- Stage 3: Login Flow Analysis & Field Detection (FieldDetector)
- Stage 4: Stealth Execution (Handler Dispatch)
- Stage 5: Authentication Verification (AuthVerifier) + Session Auto-Save (SessionManager)
- Wrapped in failure-type retry policy (RetryPolicy)
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from scrapling.parser import Adaptor

from core.auth_verifier import AuthVerifier
from core.credential_manager import CredentialManager
from core.field_detector import FieldDetector, LoginFlowType
from core.handlers import (
    IframeLoginHandler,
    ModalLoginHandler,
    MultiStepHandler,
    OAuthLoginHandler,
    OTPPrimaryHandler,
    PasskeyHandler,
    SingleStepHandler,
)
from core.retry_policy import (
    AuthenticationRequired,
    CredentialRejected,
    LoginFormNotFound,
    RetryPolicy,
)
from core.session_manager import SessionManager

logger = logging.getLogger(__name__)


class LoginEngine:
    """Master Orchestrator for Tracepass Autonomous Login Engine."""

    def __init__(
        self,
        session_manager: SessionManager | None = None,
        credential_manager: CredentialManager | None = None,
        field_detector: FieldDetector | None = None,
        auth_verifier: AuthVerifier | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        """Initializes LoginEngine with default or custom component instances."""
        self.session_manager = session_manager or SessionManager()
        self.credential_manager = credential_manager or CredentialManager()
        self.field_detector = field_detector or FieldDetector()
        self.auth_verifier = auth_verifier or AuthVerifier()
        self.retry_policy = retry_policy or RetryPolicy()

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extracts normalized hostname from a URL."""
        clean = url.strip().lower()
        if "://" in clean:
            clean = urlparse(clean).netloc
        return clean.split("/", 1)[0].split(":", 1)[0]

    def register_verifier(self, domain: str, verifier_fn: Callable[..., Any]) -> None:
        """Registers a domain-specific post-login authentication verifier callback."""
        self.auth_verifier.register_verifier(domain, verifier_fn)

    def inject_credentials(self, domain: str, username: str, password: str) -> None:
        """Injects credentials into in-process memory cache for target domain."""
        self.credential_manager.inject_credentials(domain, username, password)

    async def authenticate(
        self,
        page: Any,
        target_url: str,
        master_password: str | None = None,
    ) -> bool:
        """Runs the complete 5-stage autonomous login pipeline on a Playwright page."""

        async def _run_pipeline() -> bool:
            domain = self._extract_domain(target_url)

            # Stage 1: Session Cache Check & Restoration
            if self.session_manager.has_valid_session(target_url):
                session_data = self.session_manager.load_session(target_url)
                if session_data:
                    logger.info("Restoring cached session state for %s", domain)
                    cached_cookies = session_data.get("cookies", [])
                    cached_ls = session_data.get("local_storage", {})
                    cached_ss = session_data.get("session_storage", {})

                    if (
                        cached_cookies
                        and hasattr(page, "context")
                        and hasattr(page.context, "add_cookies")
                    ):
                        try:
                            await page.context.add_cookies(cached_cookies)
                        except Exception as e:
                            logger.debug("Error adding cached cookies to page context: %s", e)

                    if (cached_ls or cached_ss) and hasattr(page, "evaluate"):
                        try:
                            await page.evaluate(
                                """({ ls, ss }) => {
                                    if (ls) { for (const [k, v] of Object.entries(ls)) localStorage.setItem(k, v); }
                                    if (ss) { for (const [k, v] of Object.entries(ss)) sessionStorage.setItem(k, v); }
                                }""",
                                {"ls": cached_ls, "ss": cached_ss},
                            )
                        except Exception as e:
                            logger.debug("Error restoring localStorage/sessionStorage: %s", e)

                    with contextlib.suppress(Exception):
                        await page.goto(target_url)

                    if await self.auth_verifier.verify(
                        page, target_url, cookies=cached_cookies, local_storage=cached_ls
                    ):
                        logger.info("Restored session verified for %s. Skipping login.", domain)
                        return True

                    logger.warning(
                        "Restored session verification failed for %s. Invalidating cache.", domain
                    )
                    self.session_manager.invalidate_session(target_url)

            # Stage 2: Credential Resolution
            if master_password and not self.credential_manager.master_password:
                self.credential_manager.master_password = master_password

            creds = self.credential_manager.get_credentials(target_url)
            if not creds:
                raise AuthenticationRequired(
                    f"No credentials or session found for domain '{domain}'. "
                    "An existing account is required. Please provide credentials via TRACEPASS_CREDS "
                    "in environment or OS Keyring."
                )
            username, password = creds

            # Stage 3: DOM Flow Analysis
            # For SPAs (React/Vue/Angular), wait for visible input elements to render into the DOM
            try:
                await page.wait_for_selector(
                    "input[name='email'], input[name='username'], input[type='password'], input",
                    state="visible",
                    timeout=15000,
                )
            except Exception:
                logger.debug("No input elements visible within initial wait timeout")

            html_content = await page.content()
            adaptor = Adaptor(html_content)
            fields_res = self.field_detector.detect_fields(adaptor)

            if (
                isinstance(fields_res, dict)
                and "flow_type" in fields_res
                and fields_res["flow_type"] is not None
            ):
                flow_type = fields_res["flow_type"]
                fields = fields_res.get("fields", fields_res)
            else:
                fields = fields_res
                flow_type = self.field_detector.classify_flow(fields)

            logger.info(
                "Detected login flow '%s' for domain %s",
                flow_type.name if hasattr(flow_type, "name") else flow_type,
                domain,
            )

            # Stage 4: Stealth Execution (Handler Dispatch)
            if flow_type == LoginFlowType.SINGLE_STEP:
                handler_single = SingleStepHandler(username=username, password=password)
                await handler_single.execute(page, fields)

            elif flow_type == LoginFlowType.MULTI_STEP:
                handler_multi = MultiStepHandler(username=username, password=password)
                await handler_multi.execute(page, fields)

            elif flow_type == LoginFlowType.MODAL:
                handler_modal = ModalLoginHandler(username=username, password=password)
                await handler_modal.execute(page, fields)

            elif flow_type == LoginFlowType.IFRAME:
                handler_iframe = IframeLoginHandler(username=username, password=password)
                await handler_iframe.execute(page, fields)

            elif flow_type == LoginFlowType.OAUTH_SSO:
                handler_oauth = OAuthLoginHandler(username=username, password=password)
                await handler_oauth.execute(page, fields)

            elif flow_type == LoginFlowType.OTP_PRIMARY:
                handler_otp = OTPPrimaryHandler()
                await handler_otp.execute(page, domain=domain, fields=fields)

            elif flow_type == LoginFlowType.PASSKEY:
                handler_passkey = PasskeyHandler()
                await handler_passkey.execute(page, domain=domain, fields=fields)

            elif flow_type == LoginFlowType.NONE:
                raise LoginFormNotFound(
                    f"Unable to identify login fields on page for domain '{domain}'."
                )

            # Extract cookies & storage from Playwright page
            cookies = []
            if hasattr(page, "context") and hasattr(page.context, "cookies"):
                try:
                    cookies = await page.context.cookies()
                except Exception as e:
                    logger.debug("Failed to extract cookies from page.context: %s", e)

            local_storage = None
            session_storage = None
            if hasattr(page, "evaluate"):
                try:
                    local_storage = await page.evaluate("() => ({ ...localStorage })")
                except Exception:
                    local_storage = None
                try:
                    session_storage = await page.evaluate("() => ({ ...sessionStorage })")
                except Exception:
                    session_storage = None

            # Stage 5: Post-Login Verification & Session Save
            verified = await self.auth_verifier.verify(
                page, target_url, cookies=cookies, local_storage=local_storage
            )
            if not verified:
                raise CredentialRejected(
                    f"Authentication verification failed for domain '{domain}'. Check credentials."
                )

            # Synchronously save session using extracted browser state
            self.session_manager.save_session(
                domain_or_url=target_url,
                cookies=cookies,
                session_storage=session_storage,
                local_storage=local_storage,
            )
            logger.info("Successfully authenticated and saved session for %s", domain)
            return True

        return await self.retry_policy.execute_with_retry(_run_pipeline)
