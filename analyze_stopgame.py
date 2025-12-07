
import asyncio
import aiohttp
from bs4 import BeautifulSoup

async def analyze_stopgame():
    url = "https://stopgame.ru/news"
    print(f"--- Analyzing StopGame ({url}) ---")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(url) as response:
            html = await response.text()
            soup = BeautifulSoup(html, "html.parser")
            
            # Find all links that look like article titles
            # They usually point to /newsdata/ or /show/
            candidate_links = soup.select("a[href*='/newsdata/'], a[href*='/show/']")
            print(f"Found {len(candidate_links)} candidate links")
            
            for i, link in enumerate(candidate_links[:5]):
                print(f"\nLink {i}:")
                print(f"  Href: {link.get('href')}")
                print(f"  Classes: {link.get('class')}")
                print(f"  Text: {link.get_text(strip=True)}")
                
                # Check parent to find container
                parent = link.parent
                print(f"  Parent Classes: {parent.get('class')}")
                
            # Check for date candidates
            # Subagent said date is text node after category link
            # Let's look for "timestamp" or similar classes just in case
            timestamps = soup.select("[class*='timestamp'], [class*='date'], [class*='time']")
            print(f"\nFound {len(timestamps)} elements with date-like classes")
            for ts in timestamps[:5]:
                 print(f"  Class: {ts.get('class')}, Text: {ts.get_text(strip=True)}")

if __name__ == "__main__":
    asyncio.run(analyze_stopgame())
