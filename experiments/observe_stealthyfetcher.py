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

    # Inspect all inputs
    inputs = result.css("input")
    print(f"Total inputs: {len(inputs)}")
    for inp in inputs:
        print(f" - Input: name='{inp.attrib.get('name')}', type='{inp.attrib.get('type')}', id='{inp.attrib.get('id')}'")

    # Access password element (generate_css_selector is a property, no '()')
    passwords = result.css("input[type='password']")
    if passwords:
        pw_el = passwords[0]
        print(f"Password field: {pw_el.attrib}")
        print(f"Generated CSS Selector: {pw_el.generate_css_selector}")
    else:
        print("Password field: None")

    # Access submit button
    submits = result.css("button[type='submit']")
    if submits:
        sub_el = submits[0]
        print(f"Submit button text: '{sub_el.text.strip()}' | attrs={sub_el.attrib}")
        print(f"Generated CSS Selector: {sub_el.generate_css_selector}")
    else:
        print("Submit button: None")


async def test_reddit_custom_elements():
    print("\n==========================================")
    print(" 2. Inspecting Reddit Custom Web Components")
    print("==========================================")
    fetcher = StealthyFetcher()
    result = await fetcher.async_fetch(
        "https://www.reddit.com/login/",
        network_idle=True,
    )

    # Search for custom web components / custom elements
    custom_inputs = result.css("faceplate-text-input, reddit-input, auth-flow, shreddit-app")
    print(f"Custom components found: {len(custom_inputs)}")
    for comp in custom_inputs[:5]:
        print(f" - Tag: <{comp.tag}> attrs={comp.attrib}")


async def main():
    await test_classic_type1()
    await test_reddit_custom_elements()


asyncio.run(main())