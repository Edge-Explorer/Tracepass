from scrapling.fetchers import StealthyFetcher

url = "https://file-examples.com/"
print(f"🚀 Launching browser and navigating to {url}")

# headless=False lets you see the browser window open
page = StealthyFetcher.fetch(url, headless=False,solve_cloudflare=True)

# Extract and print the page title
print("✅ Successfully loaded!")
print("📄 Page Title:", page.xpath('//title/text()').get())

