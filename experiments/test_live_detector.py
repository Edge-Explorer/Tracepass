import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncio
from scrapling.fetchers import StealthyFetcher
from core.field_detector import FieldDetector


async def main():
    target_url = "https://the-internet.herokuapp.com/login"
    username = "tomsmith"
    password = "SuperSecretPassword!"

    print("==========================================")
    print(" 1. Detecting Login Fields on Target URL")
    print("==========================================")
    fetcher = StealthyFetcher()

    # Step 1: Detect fields using our FieldDetector
    detect_res = await fetcher.async_fetch(target_url, wait_selector="input")
    fields = FieldDetector.detect_fields(detect_res)
    print(f"Detected fields: {fields}")

    # Step 2: Define the page_action callback that types and clicks
    async def perform_login(page):
        print("\n[Browser Action]: Typing username with human delay...")
        await page.locator(fields["username"]).press_sequentially(
            username, delay=100
        )

        print("[Browser Action]: Typing password with human delay...")
        await page.locator(fields["password"]).press_sequentially(
            password, delay=100
        )

        print("[Browser Action]: Clicking submit button...")
        await page.locator(fields["submit"]).hover()
        await page.locator(fields["submit"]).click()

        # Wait for page to navigate / update
        await page.wait_for_load_state("networkidle")

    print("\n==========================================")
    print(" 2. Executing Automated Stealth Login")
    print("==========================================")

    # Step 3: Fetch with page_action executed inside the browser!
    login_result = await fetcher.async_fetch(
        target_url,
        page_action=perform_login,
    )

    print(f"\nFinal URL: {login_result.url}")
    print(f"Status Code: {login_result.status}")

    # Check if login succeeded (Look for the success flash message)
    flash_message = login_result.css("#flash, .flash")
    if flash_message:
        print(f"\n🎉 Server Response Message: {flash_message[0].text.strip()}")

    # Inspect the saved cookies from the session
    print(f"\nAuthenticated Cookies captured:")
    for cookie in login_result.cookies:
        print(f"  - {cookie}")


if __name__ == "__main__":
    asyncio.run(main())