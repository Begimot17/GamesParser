
import asyncio
import aiohttp
from bs4 import BeautifulSoup

async def fetch_and_analyze(url, name, selectors):
    print(f"\n--- Analyzing {name} ({url}) ---")
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url) as response:
                html = await response.text()
                soup = BeautifulSoup(html, "html.parser")
                
                print(f"Status: {response.status}")
                if "articles" in selectors:
                    articles = soup.select(selectors["articles"])
                    print(f"Found {len(articles)} articles with selector '{selectors['articles']}'")
                    
                    if articles:
                        first = articles[0]
                        # Analyze Title
                        title = first.select_one(selectors.get("title", ""))
                        print(f"Title: {title.get_text(strip=True) if title else 'NOT FOUND'}")
                        
                        # Analyze Link
                        link = first.select_one(selectors.get("link", ""))
                        print(f"Link: {link['href'] if link and link.has_attr('href') else 'NOT FOUND'}")
                        
                        # Analyze Date
                        date = first.select_one(selectors.get("date", ""))
                        print(f"Date: {date.get_text(strip=True) if date else 'NOT FOUND'}")
                        
                        # Check for potential new fields
                        print("Potential new data points in first article:")
                        # Look for tags
                        tags = first.select("a[href*='tag'], .tag, .tags")
                        if tags:
                            print(f"  Tags found: {[t.get_text(strip=True) for t in tags[:3]]}")
                        
                        # Look for views/comments
                        stats = first.select("[class*='count'], [class*='stat'], .views, .comments")
                        if stats:
                            print(f"  Stats candidates: {[s.get_text(strip=True) for s in stats[:3]]}")
                            
    except Exception as e:
        print(f"Error analyzing {name}: {e}")

async def main():
    # Corrected selectors from parsers.yml
    configs = [
        (
            "https://vgtimes.ru/free/", 
            "VGTimes",
            {
                "articles": "ul.list-items > li",
                "title": "div.item-name.type0 a:first-child",
                "link": "div.item-name.type0 a:first-child",
                "date": "span.post_date" # This might be on inner page, but checking list page first
            }
        ),
        (
            "https://pikabu.ru/community/steam",
            "Pikabu",
            {
                "articles": "article[data-story-id]",
                "title": "a.story__title-link",
                "link": "a.story__title-link",
                "date": "time.story__datetime"
            }
        ),
        (
            "https://stopgame.ru/news",
            "StopGame",
            {
                "articles": ".article-item",
                "title": ".article-title a",
                "link": ".article-title a",
                "date": ".article-info .timestamp"
            }
        )
    ]
    
    for url, name, selectors in configs:
        await fetch_and_analyze(url, name, selectors)

if __name__ == "__main__":
    asyncio.run(main())
