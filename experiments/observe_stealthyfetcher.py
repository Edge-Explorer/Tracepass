import asyncio
from scrapling.fetchers import StealthyFetcher


async def test_classic_type1():
    print("\n==========================================")
    print(" 1. Testing Classic Type 1 Single-Step Form")
    print("==========================================")
    fetcher = StealthyFetcher()
    result = await fetcher.async_fetch(
        "https://the-internet.herokuapp.com/login",
        network_idle=True,
    )

    print(f"Status: {result.status}")
    inputs = result.css("input")
    print(f"Total inputs: {len(inputs)}")
    for inp in inputs:
        print(f" - Input: name='{inp.attrib.get('name')}', type='{inp.attrib.get('type')}', id='{inp.attrib.get('id')}'")

    passwords = result.css("input[type='password']")
    if passwords:
        pw_el = passwords[0]
        print(f"Password field: {pw_el.attrib}")
        print(f"Generated CSS Selector: {pw_el.generate_css_selector}")

    submits = result.css("button[type='submit']")
    if submits:
        sub_el = submits[0]
        print(f"Submit button text: '{sub_el.text.strip()}' | attrs={sub_el.attrib}")
        print(f"Generated CSS Selector: {sub_el.generate_css_selector}")


async def test_reddit_custom_elements():
    print("\n==========================================")
    print(" 2. Inspecting Reddit Custom Web Components")
    print("==========================================")
    fetcher = StealthyFetcher()
    result = await fetcher.async_fetch(
        "https://www.reddit.com/login/",
        network_idle=True,
    )

    print(f"Status: {result.status}")
    custom_inputs = result.css("faceplate-text-input, reddit-input, auth-flow, shreddit-app")
    print(f"Custom components found: {len(custom_inputs)}")
    for comp in custom_inputs[:5]:
        print(f" - Tag: <{comp.tag}> attrs={comp.attrib}")


async def test_discord():
    print("\n==========================================")
    print(" 3. Testing Discord Login (React SPA + Anti-Bot)")
    print("==========================================")
    fetcher = StealthyFetcher()

    print("Fetching Discord login page (waiting for React hydration)...")
    result = await fetcher.async_fetch(
        "https://discord.com/login",
        # Wait up to 15 seconds for Discord's React inputs to mount in DOM
        wait_selector="input[name='email'], input[type='text'], input",
        timeout=15000,
    )

    print(f"Status: {result.status}")

    # Inspect page title
    titles = result.css("title")
    print(f"Page Title: {titles[0].text.strip() if titles else 'No Title'}")

    # Inspect all inputs found in Discord's React DOM
    inputs = result.css("input")
    print(f"\nTotal inputs found: {len(inputs)}")
    for inp in inputs:
        print(f" - Input: name='{inp.attrib.get('name')}', type='{inp.attrib.get('type')}', aria-label='{inp.attrib.get('aria-label')}'")

    # Look for the password field
    passwords = result.css("input[type='password']")
    if passwords:
        pw_el = passwords[0]
        print(f"\nPassword field detected: {pw_el.attrib}")
        print(f"Generated CSS Selector: {pw_el.generate_css_selector}")
    else:
        print("\nPassword field: None detected")

    # Look for submit / login buttons
    buttons = result.css("button[type='submit'], button")
    print(f"\nButtons found: {len(buttons)}")
    for btn in buttons[:5]:
        print(f" - Button: text='{btn.text.strip()}' | type='{btn.attrib.get('type')}' | selector='{btn.generate_css_selector}'")

async def main():
    await test_classic_type1()
    await test_reddit_custom_elements()
    await test_discord()


asyncio.run(main())