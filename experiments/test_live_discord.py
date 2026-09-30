import asyncio
import getpass
import logging
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.login_engine import LoginEngine
from scrapling.fetchers import StealthyFetcher

logging.basicConfig(level=logging.INFO)


async def main():
    print("==========================================")
    print(" Running Live System Test with LoginEngine")
    print(" Target: Discord (https://discord.com/login)")
    print("==========================================")

    target_url = "https://discord.com/login"
    domain = "discord.com"

    username = input("Enter Discord Email / Phone: ").strip()
    password = getpass.getpass("Enter Discord Password (hidden): ").strip()

    if not username or not password:
        print("❌ Username and password cannot be empty.")
        return

    engine = LoginEngine()
    engine.inject_credentials(domain, username, password)

    fetcher = StealthyFetcher()

    async def perform_autonomous_login(page):
        print("\n[Engine Pipeline]: Triggering LoginEngine.authenticate()...")
        success = await engine.authenticate(page, target_url)
        print(f"[Engine Pipeline]: Login result = {success}")

    print("\n[1] Launching stealth browser to Discord login page...")
    result = await fetcher.async_fetch(
        target_url,
        page_action=perform_autonomous_login,
        wait_selector="input[name='email'], input",
        timeout=30000,
    )

    print("\n==========================================")
    print(" Discord Live Test Completed!")
    print("==========================================")
    print(f"Final URL: {result.url}")
    print(f"Status Code: {result.status}")
    print(f"Captured Cookies Count: {len(result.cookies)}")


if __name__ == "__main__":
    asyncio.run(main())
