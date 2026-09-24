import sys
from pathlib import Path

# Add project root to sys.path so Python finds 'core'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncio
from scrapling.fetchers import StealthyFetcher
from core.field_detector import FieldDetector


async def test_site(name: str, url: str, wait_sel: str = "input"):
    print(f"\n==========================================")
    print(f" Live Test: {name}")
    print(f" URL: {url}")
    print(f"==========================================")
    fetcher = StealthyFetcher()

    print("Fetching page with Camoufox...")
    result = await fetcher.async_fetch(url, wait_selector=wait_sel, timeout=15000)

    # Run our new FieldDetector
    detected = FieldDetector.detect_fields(result)

    print("\n[Detected Field Selector Map]:")
    for field_name, selector in detected.items():
        print(f"  - {field_name.ljust(15)} : {selector}")


async def main():
    # 1. Classic Form
    await test_site("Classic Type 1", "https://the-internet.herokuapp.com/login")

    # 2. Reddit Web Components
    await test_site("Reddit", "https://www.reddit.com/login/", wait_sel="shreddit-app")

    # 3. Discord React SPA
    await test_site("Discord", "https://discord.com/login", wait_sel="input[name='email'], input")

    # 4. LinkedIn Enterprise Auth
    await test_site("LinkedIn", "https://www.linkedin.com/login", wait_sel="input[type='password'], input")


if __name__ == "__main__":
    asyncio.run(main())