"""Tracepass Main CLI Entrypoint.

Runs the Tracepass Master Autonomous Login Engine on any target website URL.
"""

import argparse
import asyncio
import getpass
import logging
import sys
from urllib.parse import urlparse

from scrapling.fetchers import StealthyFetcher

from core.login_engine import LoginEngine

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s [%(name)s]: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("tracepass")


async def run_tracepass(
    target_url: str,
    username: str | None = None,
    password: str | None = None,
    explicit_creds: bool = False,
) -> None:
    """Executes the complete Tracepass autonomous login pipeline on target_url."""
    clean_url = target_url.strip()
    if not clean_url.startswith("http://") and not clean_url.startswith("https://"):
        clean_url = f"https://{clean_url}"

    parsed = urlparse(clean_url)
    domain = parsed.netloc.split(":")[0]

    print("\n=======================================================")
    print(" 🚀 TRACEPASS AUTONOMOUS LOGIN ENGINE")
    print(f" Target Site : {domain}")
    print(f" Target URL  : {clean_url}")
    print("=======================================================\n")

    engine = LoginEngine()

    # If credentials were explicitly provided, inject them — overrides .env / keyring.
    # This ensures deliberately wrong creds are tested, not silently bypassed.
    if username:
        engine.inject_credentials(domain, username, password or "")

    fetcher = StealthyFetcher()

    login_success = False

    async def _stealth_page_action(page):
        nonlocal login_success
        logger.info("Executing Tracepass LoginEngine pipeline on stealth browser...")
        login_success = await engine.authenticate(
            page,
            clean_url,
            skip_session_cache=explicit_creds,  # bypass cache when user typed credentials
        )
        return login_success

    try:
        result = await fetcher.async_fetch(
            clean_url,
            page_action=_stealth_page_action,
            timeout=90000,
        )

        print("\n=======================================================")
        print(" 📌 EXECUTION RESULTS")
        print("=======================================================")
        if login_success:
            print(" Status       : SUCCESS ✅")
        else:
            print(" Status       : FAILED ❌ (Login pipeline did not complete)")
        print(f" Final URL    : {result.url}")
        print(f" HTTP Code    : {result.status}")
        print(f" Saved Cookies: {len(result.cookies)} session cookies stored")
        print("=======================================================\n")

    except Exception as e:
        print("\n=======================================================")
        print(" ❌ EXECUTION FAILED")
        print("=======================================================")
        print(f" Error: {e}")
        print("=======================================================\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Tracepass Autonomous Login Engine CLI")
    parser.add_argument(
        "url",
        nargs="?",
        help="Target login URL (e.g. https://discord.com/login)",
    )
    parser.add_argument("-u", "--username", help="Username or email for target site")
    parser.add_argument("-p", "--password", help="Password for target site")

    args = parser.parse_args()

    target_url = args.url
    if not target_url:
        target_url = input(
            "Enter target login URL (e.g. https://discord.com/login): "
        ).strip()
        if not target_url:
            print("❌ Target URL is required.")
            sys.exit(1)

    username = args.username
    password = args.password

    # If not passed via flags, ask interactively
    if not username:
        username = (
            input("Enter Username / Email (or press Enter to use stored/env creds): ").strip()
            or None
        )

    # If username was explicitly provided, password is required
    # (empty password = intentional test of wrong creds, not a fallback signal)
    if username and not password:
        password = getpass.getpass("Enter Password (hidden): ").strip()
        if not password:
            print("⚠️  No password entered — using stored/env credentials for this domain instead.")
            username = None  # treat as "use stored creds" if both are blank

    # explicit_creds=True tells the engine to skip session cache and test these credentials directly
    asyncio.run(run_tracepass(target_url, username, password, explicit_creds=bool(username)))


if __name__ == "__main__":
    main()
