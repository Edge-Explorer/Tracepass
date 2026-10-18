"""Semantic Field Detector Module for Tracepass Login Engine.

Implements Section 6 of docs/login-engine.md:
- Honeypot pre-filtering (removes hidden / offscreen traps and hidden ancestors)
- Two-mode field detection (Adaptive Mode vs. Discovery Mode)
- Semantic waterfall for username, password, submit, next, and modal trigger.
- LoginFlowType classification.
"""

from __future__ import annotations

import re
from enum import Enum, auto
from typing import Any


class LoginFlowType(Enum):
    """Supported login flow classifications per docs/login-engine.md Section 2."""

    SINGLE_STEP = auto()  # Type 1: username + password in same view
    MULTI_STEP = auto()  # Type 2: username visible, password appears after next
    MODAL = auto()  # Type 3: modal trigger button must be clicked
    IFRAME = auto()  # Type 4: login form inside iframe
    OAUTH_SSO = auto()  # Type 5: OAuth / SSO provider buttons
    OTP_PRIMARY = auto()  # Type 8: OTP / magic link only
    PASSKEY = auto()  # Type 9: Passkey / WebAuthn
    NONE = auto()  # No automatable login fields detected


class FieldDetector:
    """Detects and resolves login form fields using semantic analysis."""

    # Regex patterns for semantic attribute matching
    USERNAME_NAME_RE = re.compile(r"(user|email|login|account|phone|session_key)", re.IGNORECASE)
    USERNAME_HINT_RE = re.compile(
        r"(email|username|user name|phone number|email or phone)", re.IGNORECASE
    )
    SUBMIT_TEXT_RE = re.compile(
        r"(sign in|log in|login|continue|next|submit|go|proceed)", re.IGNORECASE
    )
    NEXT_TEXT_RE = re.compile(r"(next|continue|proceed|forward)", re.IGNORECASE)
    MODAL_TRIGGER_RE = re.compile(r"(sign in|log in|login|get started|join|account)", re.IGNORECASE)

    @classmethod
    def _get_text(cls, element: Any) -> str:
        """Helper to extract full inner text including descendants."""
        if hasattr(element, "get_all_text"):
            return element.get_all_text().strip()
        text = getattr(element, "text", "")
        return text.strip() if text else ""

    @classmethod
    def is_honeypot(cls, element: Any) -> bool:
        """Pre-filter check: returns True if element is a bot trap / hidden honeypot."""
        attrib = getattr(element, "attrib", {})

        if attrib.get("type", "").lower() == "hidden":
            return True

        if attrib.get("aria-hidden", "").lower() == "true":
            return True

        if "hidden" in attrib:
            return True

        style = attrib.get("style", "").lower().replace(" ", "")
        if (
            "display:none" in style
            or "visibility:hidden" in style
            or "opacity:0" in style
            or "left:-" in style
        ):
            return True

        # Ancestor honeypot check
        curr = getattr(element, "parent", None)
        while curr is not None:
            c_attrib = getattr(curr, "attrib", {})
            c_style = c_attrib.get("style", "").lower().replace(" ", "")
            if (
                c_attrib.get("aria-hidden", "").lower() == "true"
                or "hidden" in c_attrib
                or "display:none" in c_style
                or "visibility:hidden" in c_style
                or "opacity:0" in c_style
            ):
                return True
            curr = getattr(curr, "parent", None)

        return False

    @classmethod
    def _make_selector(cls, element: Any) -> str:
        """Generates a robust CSS selector prioritizing name, autocomplete, and type over dynamic IDs."""
        if element is None:
            return ""
        attrib = getattr(element, "attrib", {})
        name = attrib.get("name", "").strip()
        inp_id = attrib.get("id", "").strip()
        ac = attrib.get("autocomplete", "").strip()
        inp_type = attrib.get("type", "").strip()
        tag = getattr(element, "tag", "input").lower()

        # If name is present and id is dynamic (e.g. uid_10, react-123), use name selector
        if name and (not inp_id or re.search(r"(uid_|react_|jsx_|ng_|ember_|:\w+:)", inp_id, re.I)):
            return f"{tag}[name='{name}']"

        # If autocomplete is explicit
        if ac and ac in ("username", "email", "current-password", "one-time-code"):
            return f"{tag}[autocomplete='{ac}']"

        # If type is password
        if inp_type == "password":
            return f"{tag}[type='password']" if tag != "input" else "input[type='password']"

        # If id is clean and static
        if inp_id and not re.search(r"(uid_\d+|react_\d+|:\w+:)", inp_id, re.I):
            return f"#{inp_id}"

        if name:
            return f"{tag}[name='{name}']"

        return getattr(element, "generate_css_selector", f"{tag}")

    @classmethod
    def detect_username(
        cls, response: Any, allow_fallback: bool = True
    ) -> tuple[Any | None, str | None, bool]:
        """Detects the username/email field via semantic waterfall."""
        inputs = response.css("input, faceplate-text-input, reddit-input")
        valid_inputs = [el for el in inputs if not cls.is_honeypot(el)]

        if not valid_inputs:
            return None, None, False

        # Tier 1: Explicit autocomplete='username' or 'email'
        for inp in valid_inputs:
            ac = inp.attrib.get("autocomplete", "").lower()
            if ac in ("username", "email"):
                return inp, cls._make_selector(inp), True

        # Tier 2: type='email'
        for inp in valid_inputs:
            if inp.attrib.get("type", "").lower() == "email":
                return inp, cls._make_selector(inp), True

        # Tier 3: name, id, or placeholder matching username/email regex
        for inp in valid_inputs:
            name = inp.attrib.get("name", "")
            inp_id = inp.attrib.get("id", "")
            ph = inp.attrib.get("placeholder", "")
            if (
                cls.USERNAME_NAME_RE.search(name)
                or cls.USERNAME_NAME_RE.search(inp_id)
                or cls.USERNAME_HINT_RE.search(ph)
            ):
                return inp, cls._make_selector(inp), True

        # Tier 4: Associated label text matches username/email regex
        for inp in valid_inputs:
            inp_id = inp.attrib.get("id", "")
            if inp_id:
                labels = response.css(f"label[for='{inp_id}']")
                for lbl in labels:
                    if cls.USERNAME_HINT_RE.search(cls._get_text(lbl)):
                        return inp, cls._make_selector(inp), True

        if not allow_fallback:
            return None, None, False

        # Tier 5: Fallback — first visible input that is NOT password, checkbox, radio, button, submit, search
        for inp in valid_inputs:
            inp_type = inp.attrib.get("type", "text").lower()
            if inp_type not in (
                "password",
                "checkbox",
                "radio",
                "button",
                "submit",
                "hidden",
                "search",
            ):
                return inp, cls._make_selector(inp), False

        return None, None, False

    @classmethod
    def detect_password(cls, response: Any) -> tuple[Any | None, str | None]:
        """Detects the password field (supporting standard input and custom Web Components)."""
        inputs = response.css(
            "input[type='password'], faceplate-text-input[type='password'], reddit-input[type='password']"
        )
        valid_inputs = [el for el in inputs if not cls.is_honeypot(el)]
        if valid_inputs:
            first_pw = valid_inputs[0]
            return first_pw, cls._make_selector(first_pw)
        return None, None

    @classmethod
    def detect_submit(
        cls, response: Any, scope_element: Any | None = None
    ) -> tuple[Any | None, str | None]:
        """Detects the submit button for the login form."""
        container = response
        if scope_element is not None:
            curr = getattr(scope_element, "parent", None)
            while curr is not None:
                tag = getattr(curr, "tag", "").lower() if hasattr(curr, "tag") else ""
                if tag in ("form", "dialog", "main", "body"):
                    container = curr
                    break
                curr = getattr(curr, "parent", None)

        buttons = container.css(
            "button, input[type='submit'], input[type='button'], div[role='button']"
        )
        valid_buttons = [btn for btn in buttons if not cls.is_honeypot(btn)]

        if not valid_buttons:
            return None, None

        # Tier 1: button[type="submit"] or input[type="submit"]
        for btn in valid_buttons:
            if btn.attrib.get("type", "").lower() == "submit":
                return btn, cls._make_selector(btn)

        # Tier 2: Button text matches submit regex
        for btn in valid_buttons:
            text = cls._get_text(btn)
            aria_label = btn.attrib.get("aria-label", "")
            if cls.SUBMIT_TEXT_RE.search(text) or cls.SUBMIT_TEXT_RE.search(aria_label):
                return btn, cls._make_selector(btn)

        # Tier 3: First button element
        first_btn = valid_buttons[0]
        return first_btn, cls._make_selector(first_btn)

    @classmethod
    def detect_modal_trigger(cls, response: Any) -> str | None:
        """Detects a modal or overlay trigger button (ignoring navigation hyperlinks)."""
        triggers = response.css("button, div[role='button'], a")
        for trigger in triggers:
            if not cls.is_honeypot(trigger):
                # Ignore navigation hyperlinks (<a> tags with page navigation hrefs)
                tag = getattr(trigger, "tag", "").lower()
                href = trigger.attrib.get("href", "").strip()
                if (
                    tag == "a"
                    and href
                    and not href.startswith("#")
                    and not href.startswith("javascript:")
                ):
                    continue

                text = cls._get_text(trigger)
                aria_haspopup = trigger.attrib.get("aria-haspopup", "").lower()
                if aria_haspopup == "dialog" or cls.MODAL_TRIGGER_RE.search(text):
                    return cls._make_selector(trigger)
        return None

    @classmethod
    def classify_flow(cls, fields: dict[str, str | None]) -> LoginFlowType:
        """Classifies the LoginFlowType based on the detected selector map."""
        if fields.get("password") and fields.get("username"):
            return LoginFlowType.SINGLE_STEP
        if (fields.get("next-button") or fields.get("next")) and fields.get("username"):
            return LoginFlowType.MULTI_STEP
        if fields.get("modal-trigger") or fields.get("modal_trigger"):
            return LoginFlowType.MODAL
        return LoginFlowType.NONE

    @classmethod
    def detect_fields(cls, response: Any) -> dict[str, str | None]:
        """Main entrypoint: scans the DOM and returns a selector map of all 5 field types."""
        pw_el, password_sel = cls.detect_password(response)

        user_el, username_sel, is_confident_user = cls.detect_username(
            response, allow_fallback=True
        )

        modal_trigger_sel = None
        if not password_sel:
            modal_trigger_sel = cls.detect_modal_trigger(response)
            if modal_trigger_sel and not is_confident_user:
                username_sel = None
                user_el = None

        scope_el = pw_el or user_el
        submit_btn, submit_sel = cls.detect_submit(response, scope_element=scope_el)

        next_sel = None
        if username_sel and not password_sel:
            all_inputs = [
                el
                for el in response.css("input, faceplate-text-input, reddit-input")
                if not cls.is_honeypot(el)
            ]
            if submit_btn:
                btn_text = cls._get_text(submit_btn)
                if cls.NEXT_TEXT_RE.search(btn_text) or len(all_inputs) == 1:
                    next_sel = submit_sel
                    submit_sel = None

        return {
            "username": username_sel,
            "password": password_sel,
            "submit": submit_sel,
            "next": next_sel,
            "next-button": next_sel,
            "modal_trigger": modal_trigger_sel,
            "modal-trigger": modal_trigger_sel,
        }
