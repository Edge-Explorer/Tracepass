import asyncio
import getpass
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.field_detector import FieldDetector
from scrapling.fetchers import StealthyFetcher


async def run_login_flow(site_name: str, target_url: str, wait_sel: str = "input"):
    print(f"\n==========================================")
    print(f" Target: {site_name}")
    print(f" URL: {target_url}")
    print(f"==========================================")

    username = input(f"Enter {site_name} Username/Email: ").strip()
    password = getpass.getpass(f"Enter {site_name} Password (hidden): ").strip()

    if not username or not password:
        print("❌ Username or password cannot be empty.")
        return

    fetcher = StealthyFetcher()

    print("\n[1] Detecting login fields with FieldDetector...")
    detect_res = await fetcher.async_fetch(target_url, wait_selector=wait_sel, timeout=15000)
    fields = FieldDetector.detect_fields(detect_res)
    print(f"Found fields: {fields}")

    if not fields["username"] or not fields["password"]:
        print("❌ Could not detect both username and password fields on this page.")
        return

    # Callback executed inside the stealth browser
    async def perform_login(page):
        print("\n[Browser Action]: Typing username with human delay...")
        # For Web Components (like Reddit) or standard inputs
        await page.locator(fields["username"]).click()
        await page.locator(fields["username"]).press_sequentially(username, delay=90)

        print("[Browser Action]: Typing password with human delay...")
        await page.locator(fields["password"]).click()
        await page.locator(fields["password"]).press_sequentially(password, delay=100)

        print("[Browser Action]: Clicking submit button...")
        if fields["submit"]:
            await page.locator(fields["submit"]).hover()
            await page.locator(fields["submit"]).click()
        else:
            # Fallback: Press 'Enter' key in password field
            await page.locator(fields["password"]).press("Enter")

        # Wait up to 10 seconds for the server to respond
        print("[Browser Action]: Waiting for server response / redirect...")
        await page.wait_for_timeout(6000)

    print("\n[2] Executing automated stealth login...")
    login_result = await fetcher.async_fetch(
        target_url,
        page_action=perform_login,
        wait_selector=wait_sel,
        timeout=25000,
    )

    print(f"\n==========================================")
    print(f" Results for {site_name}")
    print(f"==========================================")
    print(f"Final URL: {login_result.url}")
    print(f"Status Code: {login_result.status}")

    # Inspect cookies captured from the session
    print(f"\nCaptured Cookies ({len(login_result.cookies)} found):")
    for cookie in login_result.cookies[:5]:
        print(f"  - {cookie.get('name')}: domain={cookie.get('domain')}")


async def main():
    print("Select a site to test automated login:")
    print("1. Classic Herokuapp (Type 1 - Demo)")
    print("2. Discord (React SPA + Anti-Bot)")
    print("3. Reddit (Web Components)")

    choice = input("\nEnter choice (1, 2, or 3): ").strip()

    if choice == "1":
        await run_login_flow("Herokuapp", "https://the-internet.herokuapp.com/login")
    elif choice == "2":
        await run_login_flow("Discord", "https://discord.com/login", wait_sel="input[name='email'], input")
    elif choice == "3":
        await run_login_flow("Reddit", "https://www.reddit.com/login/", wait_sel="shreddit-app")
    else:
        print("Invalid choice.")


if __name__ == "__main__":
    asyncio.run(main())