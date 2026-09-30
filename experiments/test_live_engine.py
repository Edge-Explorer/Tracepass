import asyncio
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
    print(" Target: https://the-internet.herokuapp.com/login")
    print("==========================================")

    target_url = "https://the-internet.herokuapp.com/login"
    domain = "the-internet.herokuapp.com"

    engine = LoginEngine()
    # Inject test credentials into in-memory store for target site
    engine.inject_credentials(domain, "tomsmith", "SuperSecretPassword!")

    fetcher = StealthyFetcher()

    async def perform_autonomous_login(page):
        print("\n[Engine Pipeline]: Triggering LoginEngine.authenticate()...")
        success = await engine.authenticate(page, target_url)
        print(f"[Engine Pipeline]: Login result = {success}")

    print("\n[1] Fetching target page with StealthyFetcher & LoginEngine...")
    result = await fetcher.async_fetch(
        target_url,
        page_action=perform_autonomous_login,
        timeout=25000,
    )

    print("\n==========================================")
    print(" Live Test Completed!")
    print("==========================================")
    print(f"Final URL: {result.url}")
    print(f"Status Code: {result.status}")
    print(f"Captured Cookies Count: {len(result.cookies)}")


if __name__ == "__main__":
    asyncio.run(main())
