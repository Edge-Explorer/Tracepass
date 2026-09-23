# Autonomous Login Engine — Design and Implementation Plan

## Document Purpose

This document is the authoritative technical design specification for the **Autonomous Login Engine** in Tracepass. It defines the Scrapling-native architecture, supported v1 login flow patterns (Types 1–9), credential management strategy, session lifecycle, edge case handling, worst-case scenarios, and time and space complexity analysis. The goal is to ensure that supported login pages are handled autonomously, while out-of-scope or anti-bot protected flows (Type 7 registration, OTP-primary, passkey without fallback) surface clear error boundaries and do not crash the broader scraping pipeline.

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Login Flow Taxonomy](#2-login-flow-taxonomy)
3. [System Architecture](#3-system-architecture)
4. [Credential Management](#4-credential-management)
5. [Session Lifecycle](#5-session-lifecycle)
6. [Field Detection Strategy](#6-field-detection-strategy)
7. [Execution Strategy per Login Type](#7-execution-strategy-per-login-type)
8. [Edge Cases and Failure Modes](#8-edge-cases-and-failure-modes)
9. [Worst-Case Scenarios](#9-worst-case-scenarios)
10. [Time and Space Complexity Analysis](#10-time-and-space-complexity-analysis)
11. [Design Decisions](#11-design-decisions)
12. [Implementation Checklist](#12-implementation-checklist)

---

## 1. Problem Statement

Web scraping tasks often require the agent to be in an authenticated state before target data is accessible. The core challenge is that authentication on the web is not a single, standardized interaction. Login flows differ by:

- Structural layout (single-step vs multi-step forms)
- Rendering mechanism (server-rendered HTML vs dynamically injected JavaScript)
- Anti-bot measures (CAPTCHA, device fingerprinting, rate limiting)
- Authentication protocol (native forms, OAuth 2.0, SSO federation, OTP-primary, passkey/FIDO2)
- Session persistence strategy (cookie-based, JWT in `localStorage`, IndexedDB refresh tokens, server-side sessions)

A human navigates all of these intuitively. The Tracepass Login Engine replicates this intuition through a combination of semantic DOM analysis, Scrapling's adaptive element relocation, stateful multi-turn execution via `page_action` callbacks, and intelligent session reuse via `auto_save`.

**Core requirement**: Given a target URL and a set of credentials for supported v1 login flows (Types 1–6), the agent must:

1. Detect the type of login flow present on the page.
2. Execute the login sequence correctly, handling intermediate DOM states.
3. Verify that authentication succeeded using a per-domain verification check.
4. Persist the authenticated session so future requests to the same domain do not repeat the login.
5. For Types 8 and 9, check for a password/OTP fallback path before raising `OTPPrimaryRequired` or `PasskeyRequired`.
6. Gracefully handle out-of-scope flows (Type 7 registration, unresolvable OTP-primary, passkey with no fallback) via clear error boundaries without crashing the broader scraping pipeline.


---

## 2. Login Flow Taxonomy

Every login flow encountered in the wild falls into one of the following categories. The Login Engine classifies and handles Types 1–6 autonomously. Types 8 and 9 are handled with fallback detection before raising an error. Type 7 is always out of scope.

### Type 1: Standard Single-Step Form

**Description**: A single HTML page containing a visible email/username input, a password input, and a submit button. All fields are present simultaneously in the DOM at page load.

**Examples**: Reddit, Stack Overflow, most legacy web applications.

**Identifying signals**:
- `input[type="email"]` or `input[type="text"]` and `input[type="password"]` are simultaneously in the DOM.
- Both inputs are visible and interactable without any user action.

**Execution path**: Load page → Fill username → Fill password → Click submit → Verify.

---

### Type 2: Multi-Step / Split Login

**Description**: The login is split across two or more sequential screens. The first screen typically requests an email or username. Upon submission, a second screen renders (sometimes via full page navigation, sometimes via partial DOM replacement) with the password field.

**Examples**: Google, Microsoft, LinkedIn, Amazon.

**Identifying signals**:
- Only one input field is visible in the initial DOM.
- A "Next" or "Continue" button is present.
- After clicking, a new input of `type="password"` appears either on a new URL or injected into the same page.

**Execution path**: Load page → Fill email → Click "Next" → Wait for DOM mutation (navigation or selector-appear, whichever fires first inside `page_action`) → Fill password → Click "Sign In" → Verify.

**Key challenge**: The agent must race two possible outcomes after clicking Next: a full page navigation to a new URL, or an in-place DOM mutation that reveals the password field. Both must be handled inside the same `page_action` callback. See Section 7.2 for the correct implementation.

---

### Type 3: Modal and Overlay Login

**Description**: The login form is not the primary page content. It appears in a modal dialog, drawer, or overlay that is triggered by a user action such as clicking a "Sign In" button in the navigation.

**Examples**: Twitter/X, many e-commerce sites, Medium.

**Identifying signals**:
- Page loads without any `input[type="password"]` in the visible DOM.
- A `role="dialog"`, element with `aria-modal="true"`, or a high-`z-index` container appears after a user action.

**Execution path**: Load page → Identify and click the modal trigger button → Wait for overlay to render → Execute standard login inside the modal → Verify.

**Key challenge**: The trigger button may not contain text like "Login". It may be an icon, a user avatar, or a button labeled "Get Started". Field detection must be applied to the trigger itself.

---

### Type 4: iFrame and Shadow DOM Login

**Description**: The login inputs are embedded inside an `<iframe>` element or inside a Shadow DOM tree. Standard DOM selectors operating at the top-level document will not find these inputs.

**Examples**: Embedded payment portals, enterprise identity providers embedded in SaaS dashboards, some banking sites.

**Identifying signals**:
- A `<iframe src="...">` element is present on the page.
- Inspecting the iframe's document reveals `input[type="password"]`.
- Shadow hosts with `shadowRoot` containing inputs.

**Execution path**: Detect iframe presence → Switch execution context to iframe's content frame using Playwright's `frame_locator()` → Execute standard login within that frame → Switch back to parent frame → Verify.

**Key challenge**: Playwright's frame API operates at the automation-protocol layer, above the page's own JavaScript sandbox. This means it is not subject to the browser's same-origin policy, which only restricts JavaScript executing inside the page context. This is true across all browser engines Scrapling targets (Camoufox/Firefox via StealthyFetcher) — the automation-protocol layer sits above the JS sandbox on all engines, regardless of the specific wire protocol each engine uses. `frame_locator()` can therefore access cross-origin iframes directly.

---

### Type 5: Single Sign-On and OAuth

**Description**: The page delegates authentication to a third-party provider such as Google, GitHub, Apple, or a corporate SAML identity provider. Clicking a "Continue with Google" button opens either a redirect or a popup window.

**Examples**: Most modern SaaS applications — Notion, Figma, GitHub login with Google.

**Identifying signals**:
- Buttons with text or icons referencing "Google", "GitHub", "Apple", "Microsoft", "SSO", or "Continue with".
- Clicking opens a `window.open()` popup or redirects to `accounts.google.com`, `github.com/login/oauth`, etc.

**Execution path (redirect)**: Click SSO button → Follow redirect to identity provider → Execute login on identity provider's page → Follow redirect back to original site → Verify.

**Execution path (popup)**: Click SSO button → Detect new Playwright page handle → Execute login in popup window → Wait for popup to close → Verify on original page.

**Key challenge**: OAuth state parameters, PKCE tokens, and CSRF tokens are generated per-session. The agent cannot pre-compute or cache these. Each OAuth login requires a fresh browser session following the full redirect chain.

---

### Type 6: API-Based Login (No Visible Form)

**Description**: Some modern single-page applications (SPAs) do not render traditional HTML forms. Instead, the frontend calls a backend API endpoint (`POST /api/auth/login`) with a JSON payload via `fetch()` or `axios`. The page may show a form, but the submission is entirely JavaScript-driven.

**Identifying signals**:
- The page has input elements but no traditional `<form action="...">` element.
- Intercepted network traffic shows an XHR or Fetch request to an auth endpoint on submit.

**Execution path**: This is functionally identical to Type 1 from the agent's perspective — fill inputs, click the button. Playwright handles the underlying JavaScript fetch call. No special handling is needed from the agent unless the API returns an error that does not update the visible DOM.

---

### Type 7: First-Time Registration (Sign-Up)

**Description**: The site has no existing account for the user. The agent must complete a sign-up flow before it can access authenticated content.

**Additional fields beyond standard login**:
- First name, last name, display name.
- Phone number for SMS verification.
- Date of birth, country of residence.
- CAPTCHA / reCAPTCHA / hCaptcha / Turnstile.
- Email verification link sent to inbox (agent cannot complete this step autonomously).
- Terms of Service checkbox agreement.
- Password confirmation field (the same password entered twice).

**Key challenge**: Sign-up flows are intentionally difficult to automate due to bot-prevention intent. Most require a real email inbox for verification, making fully autonomous sign-up only possible if the agent has access to a dedicated mailbox API (e.g., Mailosaur, Mailinator, or a custom inbox).

**Design decision for Tracepass**: The Login Engine will **not** attempt to handle first-time sign-up flows autonomously. If no existing session and no credentials are provided for a domain, the agent will surface a clear error: `AuthenticationRequired: No credentials or session found for domain example.com. Please create an account and provide credentials.`

---

### Type 8: OTP-Primary / Magic Link

**Description**: The site uses a one-time code or magic link as the **first and only** authentication factor. There is no password field at all. The user enters their email address, and a 6-digit code or a login link is sent to that address.

**Examples**: Slack (magic link), Linear, many fintech and internal tooling apps.

**Identifying signals**:
- Email input is present but no password input appears anywhere in the flow.
- A "Send code" or "Send login link" or "Email me a link" button is present.
- After submission, a 6-digit input or a "check your email" message appears.

**Execution path (code)**: Fill email → Click "Send code" → Wait for 6-digit OTP input → Check `TRACEPASS_OTP_<SAFE_DOMAIN>` env var; if set, fill and submit; otherwise raise `OTPPrimaryRequired` and pause for user input.

**Execution path (magic link)**: Fill email → Click "Send link" → Raise `MagicLinkRequired`; the agent cannot access the user's inbox autonomously. Inform user to click the link in their email and re-run after the session is established.

**v1 handling**: This type is handled with early detection. The engine raises `OTPPrimaryRequired` or `MagicLinkRequired` rather than hanging silently.

---

### Type 9: Passkey / Biometric Authentication

**Description**: The site presents a passkey (FIDO2/WebAuthn) prompt as its default authentication method. Passkeys require a hardware authenticator (platform authenticator, security key, Face ID, Touch ID) that exists outside the browser process and cannot be simulated.

**Examples**: GitHub (passkey default), some banking apps, enterprise identity platforms.

**Identifying signals**:
- `navigator.credentials.get()` is called on page load or after email entry (detectable via Playwright's `page.route` or by observing the resulting DOM).
- A button whose text matches `/(use passkey|sign in with passkey|passkey)/i` is present.
- The WebAuthn API prompt appears.

**Execution path**:
1. Detect passkey signal (either method above).
2. **Check for a visible password/OTP fallback link** — a link or button with text matching `/(use.*password|try another way|sign in.*differently|use.*different.*method)/i` in the same view.
3. If a fallback exists → click it and continue with the appropriate standard flow (Type 1, 2, or 8).
4. Only if no fallback is reachable → raise `PasskeyRequired: This site requires a passkey authenticator that cannot be automated. Use a password-based login method if available.`

**Key nuance**: Many real-world sites with passkey UI (GitHub, several banks, consumer apps) still have a "use your password instead" or "try another way" link. Bailing out immediately on passkey detection would incorrectly fail logins that are still automatable through that fallback path.



## 3. System Architecture

The Login Engine is structured as a pipeline of 5 components. The architecture is **Scrapling-native**: stealth browsing, session persistence, and adaptive element relocation are provided by Scrapling and are not re-implemented. The components we build sit on top of Scrapling's primitives.

### 3.1 What Scrapling Provides (Do Not Re-implement)

| Scrapling Feature | What It Replaces in a Raw Playwright Stack |
| :--- | :--- |
| `StealthyFetcher` (Camoufox/Firefox) | Manual browser fingerprint patching, stealth headers, canvas/WebGL spoofing |
| `auto_save` | Custom session serialization and persistence logic |
| `adaptive` relocation | Priority-order CSS selector waterfall for known domains |
| `page_action` callbacks | Raw `async with page.expect_navigation()` / `wait_for_selector()` patterns |

### 3.2 What We Build (The 5 Components)

```
┌──────────────────────────────────────────────────────────┐
│ A. Session Cache Checker                                 │
│                                                          │
│ Input:  domain, ~/.tracepass/sessions/ store             │
│ Output: Valid session (skip login entirely)              │
│         or No session (proceed to B)                     │
│ Built on: Scrapling auto_save + domain hash lookup       │
└──────────┬───────────────────────────────────────────────┘
           │ No valid session
           ▼
┌──────────────────────────────────────────────────────────┐
│ B. Credential Resolver                                   │
│                                                          │
│ Input:  domain                                           │
│ Output: username, password (in process memory only)      │
│         or CredentialNotFound                            │
│ Built on: OS keyring (keyring lib) + AES-256-GCM fallback│
└──────────┬───────────────────────────────────────────────┘
           │ Credentials resolved
           ▼
┌──────────────────────────────────────────────────────────┐
│ C. Login Flow Analyzer + Field Detector                  │
│                                                          │
│ Input:  rendered page DOM                                │
│ Output: LoginFlowType enum (Types 1–9)                   │
│         field selector map (adaptive for known domains,  │
│         discovery waterfall for unknown domains)         │
│ Built on: Scrapling adaptive + custom discovery rules    │
└──────────┬───────────────────────────────────────────────┘
           │ Flow type and fields identified
           ▼
┌──────────────────────────────────────────────────────────┐
│ D. Login Executor (via page_action)                      │
│                                                          │
│ Input:  flow type, field selectors, credentials          │
│ Output: post-login page state, or ExecutionFailure       │
│ Built on: Scrapling StealthyFetcher + page_action        │
│ Note:  stealth (timing, mouse paths, fingerprint         │
│         evasion) is handled by StealthyFetcher.          │
│         page_action provides the multi-step callback     │
│         extension point. We write the race logic inside. │
└──────────┬───────────────────────────────────────────────┘
           │ Execution complete
           ▼
┌──────────────────────────────────────────────────────────┐
│ E. Authentication Verifier                               │
│                                                          │
│ Input:  post-login page state                            │
│ Output: Verified authenticated session                   │
│         written to session store via auto_save           │
│         or LoginFailure                                  │
│ Built on: Per-domain registered verification checks      │
│           + generic fallback heuristic                   │
│ Note:  Scrapling provides session storage. We provide    │
│        the "did login actually succeed?" logic.          │
│        No scraping library gives you this check.         │
└──────────────────────────────────────────────────────────┘
```

### 3.3 Open Research Item: IndexedDB Session Tokens

**Before trusting Scrapling's session support on Firebase-Auth-based SPAs, explicitly verify what `auto_save` / `storage_state()` actually captures.** Playwright's `BrowserContext.storage_state()` natively captures cookies and `localStorage`. Tracepass's Section 5.1 adds a custom `sessionStorage` capture via `page.evaluate()`. However, **IndexedDB** — where Firebase Authentication stores its refresh tokens — is not covered by any of these mechanisms.

A large category of real apps (Firebase, Supabase, AWS Amplify Auth) store their authentication state in IndexedDB, not cookies or `localStorage`. If `auto_save` does not capture IndexedDB, those apps will appear to be logged out on every re-run despite a "saved" session.

**Action required at Step 1 of the build order**: Point `StealthyFetcher` at one or two Firebase-Auth-backed apps and explicitly verify whether the saved session state survives a new `StealthyFetcher` context creation. If it does not, Section 5 needs a custom IndexedDB capture and restore step (via `page.evaluate("async () => { /* IDBKeyRange.only scan */ }")`). Do not assume this works until you have observed it.

---



## 4. Credential Management

### 4.1 How Credentials Are Provided

Credentials must never be embedded in source code or passed through LLM API prompts (the LLM backend is a third-party service and prompts may be logged). Two supported modes:

**Mode A: Process-Injected Environment Variables (Recommended for automation)**

Credentials are supplied to process memory via the `TRACEPASS_CREDS` environment variable (loaded from `.env` via `python-dotenv` or injected by CI secrets managers) using a structured JSON map keyed by domain:

```env
TRACEPASS_CREDS={"example.com": {"username": "user@email.com", "password": "secret"}, "anothersite.com": {"username": "user2", "password": "pass2"}}
```

The Credential Resolver parses this JSON map in memory and looks up the domain of the target URL. Plaintext credential files are prohibited on disk.

**Mode B: Interactive Prompt (Recommended for manual/first-time runs)**

If no credentials exist in process memory for a domain, the agent pauses and prompts the user in the terminal:

```
[Tracepass] Authentication required for: example.com
Enter username/email: _
Enter password (hidden): _
Save credentials for future runs? [y/N]: _
```

If the user chooses to save, credentials are saved securely to the **OS Keyring** via the `keyring` library (Windows Credential Manager, macOS Keychain, Linux Secret Service). In headless or containerized environments where no OS keyring is available, credentials are saved to `~/.tracepass/credentials.enc` encrypted with AES-256-GCM using a PBKDF2-derived key (see Decision 4).

**Mode C: Credential Vault Integration (Future)**

Integration with HashiCorp Vault, AWS Secrets Manager, or similar enterprise secrets systems for team deployments.

### 4.2 Credential Security Constraints

- Credentials are **never** included in Gemini/LLM API prompts.
- Credentials are **never** written to logfiles.
- Credentials are **never** stored in plaintext on disk (only process-injected in memory, or stored via OS keyring / AES-256 encrypted file).
- The LLM **never** sees raw credential strings. The LLM receives only DOM structure and returns abstract selector intent (e.g., `fill(username_field)`). The Python execution layer resolves the credentials from memory/keyring and injects them directly into Playwright's `fill()` call.

### 4.3 Credential Passing Between Sessions

Within a single Tracepass run, once login succeeds, credential values exist only in process memory (as a `LoginContext` dataclass). They are discarded when the process terminates. The session cookie / `storage_state.json` is what persists to disk, not the raw credentials.

---

## 5. Session Lifecycle

### 5.1 Session Storage Format

Playwright's `BrowserContext.storage_state()` method natively exports a JSON file containing:

- All cookies (domain, path, value, expiry, secure, httpOnly flags).
- `localStorage` entries per origin.

For single-page applications (SPAs) that store authentication tokens in `sessionStorage`, Playwright's `storage_state()` does not capture `sessionStorage` natively. Tracepass extends session persistence by executing a custom helper (`page.evaluate("() => JSON.stringify(sessionStorage)")`) during session save, and re-injecting those entries during context restoration.

This file is stored at: `~/.tracepass/sessions/<sha256_of_domain>.json`

The SHA-256 hash is derived from the normalized domain (scheme + host) to avoid filename conflicts and to prevent casual readability of which accounts are stored.


### 5.2 Session Validity Check

Before attempting any login, the Session Cache Checker:

1. Derives the SHA-256 hash from the target URL's normalized domain.
2. Checks if `~/.tracepass/sessions/<sha256_of_domain>.json` exists.
3. If it exists, loads it into a new Playwright `BrowserContext`.
4. Navigates to a known authenticated URL on the domain (e.g., the user profile page or dashboard).
5. Checks whether the page redirects to a login page or an authenticated state.
6. If authenticated: returns the valid context immediately. Login is skipped entirely.
7. If unauthenticated (session expired): deletes the stale session file and proceeds with full login.

**Time cost of session check**: One HTTP request to an authenticated URL. Typically 200–800ms. This is acceptable overhead that saves the entire login sequence on all subsequent runs.

### 5.3 Session Expiry Handling

Some sites expire sessions aggressively (e.g., banking sites after 15 minutes of inactivity, or after a single use). The session validity check handles this. There is no way to predict expiry without attempting to use the session.

### 5.4 Session Invalidation on Password Change

If a login attempt fails on a site where a valid-looking session file exists, the engine:

1. Deletes the stale session file.
2. Re-attempts with full login.
3. If full login also fails, surfaces `LoginFailure: Credentials rejected by server`.

---

## 6. Field Detection Strategy

The Login Flow Analyzer builds a **field selector map** through semantic analysis rather than hardcoded CSS selectors. This ensures the engine works across sites it has never seen before.

### 6.1 Username / Email Field Detection

## 6. Field Detection Strategy

The Login Flow Analyzer operates in two modes depending on whether the domain has been seen before.

### 6.0 Two-Mode Detection

**Adaptive Mode (Known Domain)**: If `adaptive` element records exist for this domain from a previous successful login, Scrapling's `adaptive` feature uses stored multi-signal fingerprints (element text, position, surrounding structure) to relocate the correct fields even if the site's DOM structure has changed. This is the preferred path — it is fast, robust to A/B tests and DOM refactors, and requires no regex matching.

**Discovery Mode (Unknown Domain)**: If no adaptive records exist, the analyzer runs the discovery waterfall below for each field type. Once a successful login is complete, the resolved selectors are persisted via `adaptive` so that subsequent runs on the same domain use Adaptive Mode.

### 6.1 Honeypot Pre-Filter (Runs Before All Other Detection)

Before any candidate input is scored by the discovery waterfall, it must pass the honeypot pre-filter. Honeypot inputs are invisible inputs that anti-bot systems place in forms — real users never see or fill them, but naive scrapers do, triggering bot detection.

**Exclude any input that meets any of the following conditions**:
- Computed CSS `display` is `none`
- Computed CSS `visibility` is `hidden`
- Computed CSS `opacity` is `0`
- Element bounding box has zero width or zero height
- Element is positioned off-screen (e.g., `position: absolute; left < -500px` or `top < -500px`)

Note: `input[type="hidden"]` fields are never candidates for filling and never reach this filter.

### 6.2 Username / Email Field Detection (Discovery Mode)

Priority order (highest to lowest confidence), applied only to inputs that passed the honeypot pre-filter:

1. `input[autocomplete="username"]`
2. `input[autocomplete="email"]`
3. `input[type="email"]`
4. `input[type="text"]` with a `name` attribute matching regex `/(user|email|login|account|phone)/i`
5. `input[type="text"]` with a `placeholder` or `aria-label` matching regex `/(email|username|user name|phone number)/i`
6. `input[type="text"]` that is the first visible text input on the page

### 6.3 Password Field Detection (Discovery Mode)

1. `input[type="password"]` — this is unambiguous. If multiple exist, the first one is the "current password" and a second one is "confirm password" (used in registration flows, which are out of scope).

### 6.4 Submit Button Detection (Discovery Mode)

Priority order:

1. `button[type="submit"]` or `input[type="submit"]` inside a `<form>` containing the password input
2. A `<button>` with inner text matching regex `/(sign in|log in|login|continue|next|submit|go)/i`
3. A `<div role="button">` or `<a>` with matching text
4. The first clickable element within the same container as the password field

### 6.5 "Next" Button Detection (Multi-Step Flows)

Detected when only the username field is visible and no password field is present:

1. A `<button>` with inner text matching `/(next|continue|proceed)/i`
2. `button[type="submit"]` when only one input is present

### 6.6 Modal Trigger Detection

Detected when no login inputs are present in the current DOM:

1. A `<button>` or `<a>` in the navigation area with text matching `/(sign in|log in|login|get started|join)/i`
2. A `<button>` with `aria-haspopup="dialog"`
3. A navigation link whose `href` matches `/(login|signin|auth)/i` but does not navigate away (handled via JavaScript)

---

## 7. Execution Strategy per Login Type

### 7.1 Human-Realistic Input Timing

Scrapling's `StealthyFetcher` handles browser-level stealth (fingerprint patching, canvas/WebGL spoofing, realistic user-agent rotation). For input-level humanization inside `page_action` callbacks:

- Delay per character: random value between 50ms and 150ms (character-by-character via Playwright's `type()` with delay).
- Pause before clicking submit: random value between 300ms and 800ms.
- Mouse movement to submit button uses `locator.hover()` before `click()`.

Do not re-implement browser fingerprint stealth — `StealthyFetcher` already handles it.

### 7.2 Multi-Step Login Execution Flow

**Important**: This flow is implemented as a `page_action` callback passed to `StealthyFetcher`, not as raw sequential Playwright calls. The key correctness requirement is that the race between navigation and DOM mutation must be resolved inside the callback — both outcomes must be handled, not just one.

```python
async def multi_step_page_action(page):
    # Step 1: Fill email with humanized timing
    await fill_humanized(page, username_field_selector, username)

    # Step 2: Race navigation vs. DOM mutation — arm BOTH waiters before the click.
    # Use asyncio.wait with FIRST_COMPLETED to handle whichever fires first.
    nav_waiter = page.wait_for_navigation(timeout=10_000)
    selector_waiter = page.wait_for_selector(
        "input[type='password']", state="visible", timeout=10_000
    )
    await next_button.click()

    done, pending = await asyncio.wait(
        [asyncio.ensure_future(nav_waiter), asyncio.ensure_future(selector_waiter)],
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()  # Cancel the waiter that didn't fire

    # Step 3: If navigation fired, wait for password field to appear on new URL.
    #         If selector fired, password field is already in the DOM — proceed directly.
    await page.wait_for_selector("input[type='password']", state="visible", timeout=5_000)

    # Step 4: Fill password, arm navigation waiter before submit click
    await fill_humanized(page, password_field_selector, password)
    async with page.expect_navigation(timeout=15_000):
        await submit_button.click()

    # Step 5: Hand off to Authentication Verifier (Component E)
```

**Timeout**: 10 seconds for the first transition. If both `nav_waiter` and `selector_waiter` time out, raise `MultiStepTransitionTimeout`.

**Why `asyncio.FIRST_COMPLETED` instead of a static choice**: A site like Google may navigate to a new URL. A site like LinkedIn may inject the password field into the same page without navigating. The race logic must handle both without assuming which will fire. Picking one statically (navigation OR selector-appear) causes silent hangs on sites that take the other path.


### 7.3 Modal Login Execution Flow

```
1.  Navigate to page URL.
2.  Detect absence of login inputs.
3.  Identify modal trigger button using trigger detection strategy.
4.  Click trigger button.
5.  Wait for dialog/modal to appear:
      page.wait_for_selector("[role='dialog'], [aria-modal='true']", timeout=8000)
6.  Scope all subsequent field detection to within the modal container.
7.  Execute standard single-step login within scoped context.
8.  Wait for modal to close and page to update.
9.  Proceed to Verification.
```

### 7.4 OAuth / SSO Execution Flow

```
1.  Navigate to page URL.
2.  Detect SSO provider buttons.
3.  Arm event waiters BEFORE clicking (prevents popup/redirect race conditions):
      a. For same-tab redirect:
         async with page.expect_navigation():
             await sso_button.click()
      b. For popup window:
         async with page.context.expect_event("page") as popup_info:
             await sso_button.click()
         popup_page = await popup_info.value
4.  On the identity provider's login page, execute standard login flow.
5.  Wait for redirect back to original domain.
6.  Close popup handle if applicable.
7.  Proceed to Verification.
```

---

## 8. Edge Cases and Failure Modes

| Edge Case | Detection | Handling Strategy |
| :--- | :--- | :--- |
| **CAPTCHA / reCAPTCHA v2 presented** | `iframe[src*="recaptcha"]` or `div.g-recaptcha` present | Pause; surface `CaptchaRequired` error; emit user prompt for manual solve or CAPTCHA solver API integration |
| **Cloudflare Turnstile** | `iframe[src*="challenges.cloudflare.com"]` present | Rely on Scrapling's Camoufox stealth layer; if it fails, surface `BotDetectionBlocked` error |
| **Two-Factor Authentication (TOTP)** | Input field for 6-digit code appears post-password | Pause; surface `TwoFactorRequired: TOTP code needed`; resume when user provides code |
| **SMS OTP Verification** | "Enter the code sent to your phone" message in DOM | Pause; surface `SMSOTPRequired`; resume when user provides code |
| **Email Verification Required** | "Check your email" or redirect to email-confirm screen | Surface `EmailVerificationRequired: Check inbox for link`; cannot proceed autonomously |
| **Account Locked / Rate Limited** | "Too many attempts" message in DOM | Surface `AccountLocked` error with cooldown message; halt retries immediately |
| **Wrong Credentials** | Error message in DOM after submit (regex: `/(incorrect&#124;invalid&#124;wrong&#124;failed)/i`) | Surface `CredentialRejected` error; do not retry automatically (risk of account lockout) |
| **Login Success but No Redirect** | Page state does not change after submit (SPA auth via XHR) | Wait for `localStorage` or cookie mutation indicating token storage; verify via session check |
| **Password Expired** | "Your password has expired, please reset" screen | Surface `PasswordExpired` error; cannot proceed autonomously |
| **Device Trust / New Device Verification** | "We don't recognize this device" screen | Surface `DeviceTrustRequired` error; inform user out-of-band verification is needed |
| **Geographic Block** | "Service not available in your region" | Surface `GeoRestricted` error; suggest proxy configuration |
| **Session Cookie Rejected by Server** | Session file exists but server returns 401 | Delete stale session; re-attempt full login |
| **No Login Form Found** | No inputs detected on page or any modal | Surface `LoginFormNotFound: Unable to identify login fields on page` |
| **Ambiguous Form (Multiple Forms on Page)** | Multiple `<form>` elements detected | Score each form by number of matching field signals; select highest-confidence form |
| **JavaScript Disabled Detection** | Site shows "Please enable JavaScript" | This should not occur as Scrapling uses a full Playwright browser; log as unexpected error |
| **Infinite Redirect Loop** | Navigation depth exceeds 10 redirects | Raise `NavigationLoopDetected`; abort |
| **Slow Network / Timeout** | Any wait exceeds configured timeout | Raise `PageLoadTimeout`; retry once; then abort |


---

## 9. Worst-Case Scenarios

### Worst Case 1: Complete CAPTCHA Enforcement

A site requires solving a CAPTCHA on every single login attempt, with no session persistence. The agent cannot proceed autonomously.

**Resolution**: The Login Engine surfaces a `CaptchaRequired` error with the CAPTCHA iframe URL. Tracepass can optionally integrate with a CAPTCHA solving API (2captcha, Anti-Captcha) as a configurable plugin. The core engine itself does not embed this dependency.

### Worst Case 2: Aggressive Session Invalidation

A site invalidates the session on every API response (e.g., some banking or government sites with security tokens that rotate per request). Every scraping action requires re-authentication.

**Resolution**: The agent does not attempt to cache sessions for domains that exhibit this behavior (detected by repeated session check failures within a single run). It performs full login before every action for that domain. This is slow and costly but correct.

### Worst Case 3: The Login Page Changes Its Structure Between Visits

A site A/B tests its login page and the DOM structure changes between visits, breaking the cached selector map.

**Resolution**: The Login Flow Analyzer always re-analyzes the DOM on every login attempt. Selectors are never cached between runs. This has a time cost of one additional DOM scan per login (O(n) in DOM node count, typically negligible).

### Worst Case 4: Cascading Authentication (Login to Access Login)

A site requires authentication at multiple levels: a VPN check, then an SSO, then a secondary password for sensitive sections.

**Resolution**: The agent follows each authentication challenge in sequence. Each is treated as an independent login flow detection cycle. Maximum nesting depth is configurable (default: 3). Exceeding this raises `MaxAuthDepthExceeded`.

### Worst Case 5: Dynamic Field Names Generated at Runtime

A site generates randomized `name` and `id` attributes for its form fields on each page load as an anti-scraping measure. Standard attribute-based selectors fail entirely.

**Resolution**: Fall back to positional and semantic detection only: first visible `input[type="text"]`, first visible `input[type="password"]`. This covers the vast majority of such cases. If even these fail, raise `LoginFormNotFound` and flag the domain as requiring manual investigation.

---

## 10. Time and Space Complexity Analysis

### 10.1 Session Cache Check

**Time**: O(1) — file system lookup by hash key + one HTTP request. The HTTP request is the dominant cost, bounded by network latency. Typical: 200ms–800ms.

**Space**: O(s) per domain, where s is the size of `storage_state.json`. In practice this is 10KB–200KB per domain depending on cookie and storage volume.

### 10.2 Login Flow Analysis (DOM Scan)

**Time**: O(n) where n is the number of DOM nodes on the login page. Field detection iterates through candidate selectors using Playwright's query engine, which operates on the pre-built DOM tree. For a typical login page with 500–5000 nodes, this takes under 100ms.

**Space**: O(1) — the analyzer only stores the selector map for the detected fields (a fixed-size dictionary of at most 5 key-value pairs: username, password, submit, next-button, modal-trigger).

### 10.3 Credential Resolver

**Time**: O(d) where d is the number of credentials stored, for the JSON lookup. In practice d is small (< 100 domains) so this is effectively O(1).

**Space**: O(d) for the in-memory credentials map loaded from the environment variable.

### 10.4 Stealth Executor

**Time**: The dominant time cost in the entire pipeline. Each login consists of:
- Page navigation: 500ms–3000ms (network-dependent).
- Human-realistic field fill (username): n_chars × ~100ms average keystroke delay. For a 20-character email: ~2000ms.
- Human-realistic field fill (password): ~1000ms.
- Button click with mouse simulation: ~500ms.
- Post-submit navigation wait: 500ms–5000ms.
- **Total (single-step)**: ~5–12 seconds per login.
- **Total (multi-step, e.g. Google)**: ~10–20 seconds per login.

This is deliberate. The slower execution reduces bot-detection risk. Optimizing for speed here would increase the risk of account bans, which is a worse outcome than a slower login.

**Space**: O(1) — the executor holds only the current page state and field values in memory. No accumulation.

### 10.5 Session Persistence Write

**Time**: O(s) where s is the size of `storage_state.json`. Typically a file write of 10KB–200KB. Sub-millisecond.

**Space**: O(s) on disk per domain.

### 10.6 Overall Pipeline Summary

| Component | Time Complexity | Typical Latency | Space Complexity |
| :--- | :--- | :--- | :--- |
| Session Cache Check | O(1) | 200ms–800ms | O(s) on disk |
| Credential Resolver | O(d) | < 1ms | O(d) in memory |
| Login Flow Analyzer | O(n) DOM nodes | 50ms–200ms | O(1) |
| Stealth Executor | O(k) keystrokes + network | 5s–20s | O(1) |
| Session Persistence | O(s) | < 5ms | O(s) on disk |
| **Total (first login)** | — | **~6s–22s** | O(s) per domain |
| **Total (cached session)** | — | **~200ms–800ms** | — |

The session cache is the single most important performance optimization. A site visited twice in the same session or across runs should never require a full login cycle again until the session expires.

---

## 11. Design Decisions

The following decisions have been finalized by the Tracepass team. These are binding for the v1 implementation and must not be changed without a documented team discussion.

---

### Decision 1: CAPTCHA Solver Integration

**Decision**: CAPTCHA solver support is included in v1 as an **opt-in plugin** via environment variable. It is not a core dependency.

**Rationale**: Scrapling's Camoufox stealth layer resolves the majority of Cloudflare Turnstile and Invisible reCAPTCHA cases without human intervention. A solver API is only needed for explicit reCAPTCHA v2 checkbox challenges. Keeping it opt-in means the default installation stays lightweight with no mandatory paid third-party dependencies.

**Implementation**:
- If `CAPTCHA_SOLVER_API_KEY` is set in `.env`, the engine activates the solver plugin.
- Supported solver backends: `2captcha` (primary), `anticaptcha` (secondary). Configured via `CAPTCHA_SOLVER_BACKEND=2captcha`.
- The API key is read from the environment at runtime. It is never passed to the LLM or written to logs.
- Cost attribution: solver calls are logged to `~/.tracepass/solver_usage.log` with timestamp, domain, and solver type for cost tracking.
- If no solver key is set and a CAPTCHA is encountered, the engine raises `CaptchaRequired` and halts with a clear user-facing message.

---

### Decision 2: 2FA / OTP Resume Mechanism

**Decision**: The resume interface is a **blocking terminal prompt** for v1. An event-based callback interface is planned for v2.

**Rationale**: The primary v1 users are developers running Tracepass locally in a terminal. A terminal prompt is the simplest, zero-dependency solution. A REST API or callback mechanism adds architectural complexity not justified until Tracepass is embedded in larger automated pipelines.

**Implementation**:
- When `TwoFactorRequired` is raised, the executor pauses and prints to `stderr`:
  ```
  [Tracepass] Two-factor authentication required for: example.com
  [Tracepass] Enter the 6-digit TOTP or SMS code: _
  ```
- Timeout: if no code is entered within 120 seconds, raises `TwoFactorTimeout` and aborts.
- For headless and CI environments, a shell-safe environment variable `TRACEPASS_OTP_<SAFE_DOMAIN>` can be pre-set to bypass the interactive prompt entirely.
- **Shell-Safe Domain Normalization**: Non-alphanumeric characters (such as `.` or `-`) in the hostname are replaced with underscores `_` and converted to uppercase.
  - Example for `example.com`: `TRACEPASS_OTP_EXAMPLE_COM=123456`
  - Example for `sub.site-app.org`: `TRACEPASS_OTP_SUB_SITE_APP_ORG=654321`

---

### Decision 3: Session Storage Location

**Decision**: Sessions are stored in a **user-global directory** at `~/.tracepass/sessions/`.

**Rationale**: A global session store means you and your collaborators do not need to re-authenticate for domains already visited, regardless of which clone or branch you are working from. A project-local directory would force re-login on every fresh clone, which is wasteful.

**Implementation**:
- Full path: `~/.tracepass/sessions/<sha256_of_domain>.json`
- The `~/.tracepass/` directory is created automatically on first run.
- `~/.tracepass/` is in `.gitignore` globally to ensure session files are never committed.
- Session files are user-readable only (`chmod 600` on Linux/macOS; restricted ACL on Windows).

---

### Decision 4: Credential Storage

**Decision**: **OS keyring as primary**, with an **AES-256-GCM encrypted JSON file as fallback** for headless or Docker environments where the OS keyring is unavailable.

**Rationale**: The OS keyring (Windows Credential Manager, macOS Keychain, Linux Secret Service) is the most secure option — credentials are OS-encrypted and tied to the user account, never written to disk in plaintext. The encrypted file fallback ensures the engine works in CI and containerized environments where no keyring daemon is running.

**Implementation**:
- Primary: `keyring.set_password("tracepass", domain, json.dumps(creds))`.
- Fallback detection: if `keyring.get_keyring()` returns `keyring.backends.fail.Keyring`, switch to encrypted file.
- Fallback file: `~/.tracepass/credentials.enc`.
- Credentials are **never** logged, passed to the LLM, or written to plaintext files under any circumstances.

**AES-256-GCM Fallback File Format Specification (`~/.tracepass/credentials.enc`)**:
To ensure deterministic key derivation, security against replay attacks, and cross-platform compatibility:
- **Format Version**: `1` (integer)
- **Key Derivation**: PBKDF2-HMAC-SHA-256 with 600,000 iterations and a fresh random 16-byte (128-bit) salt per file write.
- **Encryption**: AES-256-GCM with a fresh random 12-byte (96-bit) nonce per file write and a 16-byte (128-bit) GCM authentication tag.
- **Record Structure (JSON)**:
  ```json
  {
    "version": 1,
    "salt": "<32-character hex-encoded string (16 bytes)>",
    "nonce": "<24-character hex-encoded string (12 bytes)>",
    "tag": "<32-character hex-encoded string (16 bytes)>",
    "ciphertext": "<hex-encoded AES-256-GCM encrypted payload>"
  }
  ```
- **Validation**: Decryption readers must verify `version == 1`, enforce exact byte lengths for salt (16B), nonce (12B), and tag (16B), and verify the GCM tag before processing payload.


---

### Decision 5: Login Failure Retry Policy

**Decision**: Retry behavior is **failure-type-specific**. The conservative default protects against account lockout.

**Rationale**: Indiscriminate retries on failed logins risk locking the user out of their own accounts (most sites lock after 3–5 failures). The policy must distinguish between wrong credentials (never retry) and transient failures like timeouts (one retry is safe).

**Retry Policy**:

| Failure Type | Retry Behavior | Reasoning |
| :--- | :--- | :--- |
| `CredentialRejected` | Never retry. Raise immediately. | Retrying risks account lockout. Credentials must be corrected. |
| `PageLoadTimeout` | Retry once after 3-second delay. | Transient network issue; one retry is safe. |
| `MultiStepTransitionTimeout` | Retry once by reloading from scratch. | Slow JS execution; a clean reload usually resolves it. |
| `CaptchaRequired` | Pause for solver or user. No auto-retry. | Retrying without solving the CAPTCHA always fails. |
| `TwoFactorTimeout` | Abort. Raise immediately. | The user did not respond; repeating will not help. |
| `AccountLocked` | Abort immediately with cooldown info. | Any further request is rejected until lockout expires. |
| `LoginFormNotFound` | Abort immediately. | Retrying the same URL produces the same DOM. |
| `NavigationLoopDetected` | Abort immediately. | A loop will repeat indefinitely. |

---

### Decision 6: Signup and Registration Support

**Decision**: First-time sign-up is **explicitly out of scope for v1**. A formal plugin interface for registration flows is **planned for v2**, gated behind team review.

**Rationale**: Registration flows are significantly more complex than login flows. They require real email inbox access for verification links, often include phone number verification, harder CAPTCHAs, and may trigger fraud detection that permanently bans the originating IP. The risk-to-reward ratio does not justify v1 inclusion.

**v1 Behavior**: If no credentials or session exist for a domain, raises:
```
AuthenticationRequired: No credentials or session found for domain example.com.
An existing account is required. Please create an account manually, then provide
credentials via TRACEPASS_CREDS in .env or via the interactive prompt on next run.
```

**v2 Plugin Interface (Planned)**:
- A `RegistrationPlugin` abstract base class will define: `fill_registration_form(page, user_profile: UserProfile) -> bool`.
- Per-site implementations can be contributed (e.g., `GmailRegistrationPlugin`).
- Requires a `MailboxProvider` dependency for verification emails (e.g., Mailosaur, custom IMAP, or Mailinator).
- Every plugin must be explicitly reviewed and approved by the team before activation, given the legal and ethical implications of automated account creation.

---

## 12. Implementation Checklist

Track progress here as work begins. Mark each item when the corresponding code is merged to `main`. The order below follows the recommended 7-step build sequence.

### Step 1: Observation (Before Writing Any Code)
- [ ] Point `StealthyFetcher` at 2–3 real Type 1 login pages. Observe actual behavior of `auto_save`, `adaptive`, and `page_action` firsthand.
- [ ] **IndexedDB research**: Point `StealthyFetcher` at a Firebase-Auth-backed SPA. Verify whether the saved session survives context recreation. Document the result in Section 5 of this doc before proceeding.

### Step 2: Field Detection Module
- [ ] `core/field_detector.py` — honeypot pre-filter + two-mode detection (adaptive for known domains, discovery waterfall for unknown domains). Covers all 5 field types: username, password, submit, next-button, modal-trigger.
- [ ] `tests/test_field_detector.py` — unit tests against static HTML fixtures for all 5 field types including honeypot cases.

### Step 3: Adaptive Durability Proof
- [ ] Prove that `adaptive` relocation works after deliberately mangling a known site's DOM IDs and classes in a local copy. Document result. Only proceed to Step 4 after this passes.

### Step 4: Multi-Step Handler (Highest Risk)
- [ ] `core/handlers/multi_step.py` — Type 2 handler using `asyncio.FIRST_COMPLETED` race inside `page_action`. Add logging on both branches (navigation fired / selector-appeared) until both have been observed firing correctly.
- [ ] `tests/integration/test_multi_step_login.py` — integration test against a real Google-style split-login flow.

### Step 5: OTP-Primary and Passkey Early Bail-Outs
- [ ] `core/handlers/otp_primary.py` — Type 8: detect OTP-primary and magic link flows; check `TRACEPASS_OTP_<SAFE_DOMAIN>` env var; surface `OTPPrimaryRequired` or `MagicLinkRequired`.
- [ ] `core/handlers/passkey.py` — Type 9: detect passkey via `navigator.credentials.get()` call and button text; check for password/OTP fallback link before raising `PasskeyRequired`.

### Step 6: Session Persistence and Authentication Verifier
- [ ] `core/session_manager.py` — session read, write, validate, invalidate. Built on Scrapling `auto_save`. Includes custom `sessionStorage` capture. Includes IndexedDB capture if Step 1 research showed it is needed.
- [ ] `core/auth_verifier.py` — Component E: per-domain registered verification checks + generic fallback heuristic. This is not provided by any library and must be built.
- [ ] `tests/test_session_manager.py` — session read, write, expiry, and invalidation.

### Step 7: Credential Management and Plugin Interfaces
- [ ] `core/credential_manager.py` — OS keyring (primary) + AES-256-GCM encrypted file fallback with full file format spec from Decision 4.
- [ ] `core/captcha_solver.py` — opt-in CAPTCHA solver plugin (2captcha, anticaptcha backends).
- [ ] `core/otp_handler.py` — blocking terminal prompt + `TRACEPASS_OTP_<SAFE_DOMAIN>` env bypass.
- [ ] `core/retry_policy.py` — failure-type-specific retry logic table.
- [ ] `tests/test_credential_manager.py` — keyring and AES-256-GCM encrypted file fallback behavior.
- [ ] `tests/test_retry_policy.py` — unit test for each failure type's retry behavior.

### Remaining Login Flow Handlers (Can Parallel After Step 4)
- [ ] `core/login_engine.py` — main orchestrator: Session Cache Checker → Credential Resolver → Login Flow Analyzer → Login Executor → Authentication Verifier
- [ ] `core/handlers/single_step.py` — Type 1: Standard single-step form
- [ ] `core/handlers/modal_login.py` — Type 3: Modal and overlay login
- [ ] `core/handlers/iframe_login.py` — Type 4: iFrame and Shadow DOM login
- [ ] `core/handlers/oauth_login.py` — Type 5: OAuth / SSO redirect and popup
- [ ] `tests/integration/test_single_step_login.py` — integration test against local mock login server

### Documentation
- [ ] Update `README.md` — add Authentication section documenting the Login Engine
- [ ] `CONTRIBUTING.md` — guide for adding new login flow handlers and domain-specific auth verifiers

> **Note**: `core/login_executor.py` (stealth execution dispatcher) has been removed from this checklist. Scrapling's `StealthyFetcher` + `page_action` replaces this component entirely. Do not build it.
