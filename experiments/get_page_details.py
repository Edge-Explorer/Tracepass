from scrapling.fetchers import StealthySession
from urllib.parse import urljoin

url = "https://file-examples.com/"
print("🚀 Fetching homepage...")

with StealthySession(headless=False,solve_cloudflare=True) as session:
    page = session.fetch(url) # Switching back to headless for speed

    print("\n🔍 Searching for category links...")
    # Get all links on the page
    all_links = page.css('a::attr(href)').getall()
    requried_links = {}
    print(all_links)
    for link in all_links:
        if link.__contains__('audio'):
            requried_links['audio'] = link
        elif link.__contains__('video'):
            requried_links['video'] = link
        elif link.__contains__('document'):
            requried_links['document'] = link
        elif link.__contains__('image'):
            requried_links['image'] = link
        else:
            continue
    print("\n✅ Found category links:")
    print(requried_links)

    if 'audio' in requried_links:
        audio_Session = session.fetch(requried_links['audio'])
        audio_links = audio_Session.css("a::attr(href)").getall()
        relevant_links  = [link for link in audio_links if link.__contains__('download/')]
        print('relevant audio links : ', relevant_links)

        