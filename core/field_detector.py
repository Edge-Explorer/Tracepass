"""Semantic Field Detector Module for Tracepass Login Engine.

Implements Section 6 of docs/login-engine.md:
- Honeypot pre-filtering (removes hidden / offscreen traps and hidden ancestors)
- Two-mode field detection (Adaptive Mode vs. Discovery Mode)
- Semantic waterfall for username, password, submit, next, and modal trigger.
"""

from __future__ import annotations

import re
from typing import Any


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
        """Pre-filter check: returns True if element is a bot trap / hidden honeypot.

        Checks:
        1. Explicit type='hidden'
        2. Inline CSS display:none, visibility:hidden, opacity:0
        3. aria-hidden='true' or hidden attribute
        4. Off-screen positioning (e.g. left: -9999px)
        5. Any hidden or display:none ancestor containers
        """
        attrib = getattr(element, "attrib", {})

        # Type hidden is never an interactive field
        if attrib.get("type", "").lower() == "hidden":
            return True

        if attrib.get("aria-hidden", "").lower() == "true":
            return True

        if "hidden" in attrib:
            return True

        # Check inline styles for common honeypot hiding techniques
        style = attrib.get("style", "").lower().replace(" ", "")
        if "display:none" in style or "visibility:hidden" in style or "opacity:0" in style:
            return True

        # Check offscreen positioning in style
        if "left:-" in style or "top:-" in style:
            return True

        # Check classes named 'honeypot', 'hp', 'trap', 'hidden'
        class_name = attrib.get("class", "").lower()
        if any(trap in class_name for trap in ("honeypot", "hidden-field", "visually-hidden")):
            return True

        # Check ancestors for hidden containers
        if hasattr(element, "iterancestors"):
            for ancestor in element.iterancestors():
                anc_attrib = getattr(ancestor, "attrib", {})
                if anc_attrib.get("aria-hidden", "").lower() == "true" or "hidden" in anc_attrib:
                    return True
                anc_style = anc_attrib.get("style", "").lower().replace(" ", "")
                if (
                    "display:none" in anc_style
                    or "visibility:hidden" in anc_style
                    or "opacity:0" in anc_style
                ):
                    return True

        return False

    @classmethod
    def detect_username(
        cls, response: Any, allow_fallback: bool = True
    ) -> tuple[Any | None, str | None, bool]:
        """Discovery waterfall for username / email field.

        Returns (element, selector, is_confident_match).
        """
        candidates = response.css("input, faceplate-text-input, reddit-input")

        valid_candidates = [
            el
            for el in candidates
            if not cls.is_honeypot(el)
            and el.attrib.get("type", "text").lower() in ("text", "email", "tel", "username", "")
        ]

        if not valid_candidates:
            return None, None, False

        # Tier 1: autocomplete="username" or "email"
        for el in valid_candidates:
            autocomplete = el.attrib.get("autocomplete", "").lower()
            if "username" in autocomplete or "email" in autocomplete:
                return el, el.generate_css_selector, True

        # Tier 2: type="email"
        for el in valid_candidates:
            if el.attrib.get("type", "").lower() == "email":
                return el, el.generate_css_selector, True

        # Tier 3: name or id matches regex
        for el in valid_candidates:
            name_val = el.attrib.get("name", "")
            id_val = el.attrib.get("id", "")
            if cls.USERNAME_NAME_RE.search(name_val) or cls.USERNAME_NAME_RE.search(id_val):
                return el, el.generate_css_selector, True

        # Tier 4: placeholder or aria-label matches regex
        for el in valid_candidates:
            placeholder = el.attrib.get("placeholder", "")
            aria_label = el.attrib.get("aria-label", "")
            label = el.attrib.get("label", "")
            if (
                cls.USERNAME_HINT_RE.search(placeholder)
                or cls.USERNAME_HINT_RE.search(aria_label)
                or cls.USERNAME_HINT_RE.search(label)
            ):
                return el, el.generate_css_selector, True

        # Tier 5: Fallback to the first visible text input (only if allowed)
        if allow_fallback:
            first_el = valid_candidates[0]
            return first_el, first_el.generate_css_selector, False

        return None, None, False

    @classmethod
    def detect_password(cls, response: Any) -> tuple[Any | None, str | None]:
        """Discovery for password field."""
        candidates = response.css("input, faceplate-text-input, reddit-input")

        valid_candidates = [
            el
            for el in candidates
            if not cls.is_honeypot(el)
            and (
                el.attrib.get("type", "").lower() == "password"
                or "current-password" in el.attrib.get("autocomplete", "").lower()
            )
        ]

        if not valid_candidates:
            return None, None

        pw_el = valid_candidates[0]
        return pw_el, pw_el.generate_css_selector

    @classmethod
    def detect_submit(
        cls, response: Any, scope_element: Any | None = None
    ) -> tuple[Any | None, str | None]:
        """Discovery waterfall for submit button.

        Prefers submit buttons within the same <form> container as the password/username input.
        """
        # If a scope element (e.g. password input) is provided, check its parent form first
        if scope_element is not None and hasattr(scope_element, "find_ancestor"):
            parent_form = scope_element.find_ancestor(
                lambda anc: getattr(anc, "tag", "").lower() == "form"
            )
            if parent_form is not None:
                form_buttons = parent_form.css(
                    "button, input[type='submit'], div[role='button'], a[role='button']"
                )
                valid_form_buttons = [btn for btn in form_buttons if not cls.is_honeypot(btn)]
                for btn in valid_form_buttons:
                    if btn.attrib.get("type", "").lower() == "submit":
                        return btn, btn.generate_css_selector
                for btn in valid_form_buttons:
                    text = cls._get_text(btn)
                    aria_label = btn.attrib.get("aria-label", "")
                    if cls.SUBMIT_TEXT_RE.search(text) or cls.SUBMIT_TEXT_RE.search(aria_label):
                        return btn, btn.generate_css_selector

        # Page-wide search
        buttons = response.css("button, input[type='submit'], div[role='button'], a[role='button']")
        valid_buttons = [btn for btn in buttons if not cls.is_honeypot(btn)]
        if not valid_buttons:
            return None, None

        # Tier 1: button[type="submit"] or input[type="submit"]
        for btn in valid_buttons:
            if btn.attrib.get("type", "").lower() == "submit":
                return btn, btn.generate_css_selector

        # Tier 2: Button text (including descendants) matches submit regex
        for btn in valid_buttons:
            text = cls._get_text(btn)
            aria_label = btn.attrib.get("aria-label", "")
            if cls.SUBMIT_TEXT_RE.search(text) or cls.SUBMIT_TEXT_RE.search(aria_label):
                return btn, btn.generate_css_selector

        # Tier 3: First button element
        first_btn = valid_buttons[0]
        return first_btn, first_btn.generate_css_selector

    @classmethod
    def detect_modal_trigger(cls, response: Any) -> str | None:
        """Detects a modal or overlay trigger button."""
        triggers = response.css("button, a, div[role='button']")
        for trigger in triggers:
            if not cls.is_honeypot(trigger):
                text = cls._get_text(trigger)
                aria_haspopup = trigger.attrib.get("aria-haspopup", "").lower()
                if aria_haspopup == "dialog" or cls.MODAL_TRIGGER_RE.search(text):
                    return trigger.generate_css_selector
        return None

    @classmethod
    def detect_fields(cls, response: Any) -> dict[str, str | None]:
        """Main entrypoint: scans the DOM and returns a selector map of all 5 field types."""
        pw_el, password_sel = cls.detect_password(response)

        # Detect username (confident vs fallback)
        user_el, username_sel, is_confident_user = cls.detect_username(
            response, allow_fallback=True
        )

        # Check for modal trigger if no password field exists
        modal_trigger_sel = None
        if not password_sel:
            modal_trigger_sel = cls.detect_modal_trigger(response)
            # If a modal trigger is found and username was only an unconfident tier-5 fallback (e.g. search box),
            # give priority to the modal trigger flow!
            if modal_trigger_sel and not is_confident_user:
                username_sel = None
                user_el = None

        # Detect submit button scoped to password/username form when available
        scope_el = pw_el or user_el
        submit_btn, submit_sel = cls.detect_submit(response, scope_element=scope_el)

        # Check for multi-step 'Next' button if only username is visible
        next_sel = None
        if username_sel and not password_sel:
            # Check all visible inputs
            all_inputs = [
                el
                for el in response.css("input, faceplate-text-input, reddit-input")
                if not cls.is_honeypot(el)
            ]
            # Next button: either explicit Next text, or generic submit ONLY when exactly one input is present
            if submit_btn:
                btn_text = cls._get_text(submit_btn)
                if cls.NEXT_TEXT_RE.search(btn_text) or len(all_inputs) == 1:
                    next_sel = submit_sel
                    submit_sel = None

        return {
            "username": username_sel,
            "password": password_sel,
            "submit": submit_sel,
            "next-button": next_sel,
            "modal-trigger": modal_trigger_sel,
        }
