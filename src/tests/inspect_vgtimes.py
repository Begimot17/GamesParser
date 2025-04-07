import requests
from bs4 import BeautifulSoup
import json

def inspect_vgtimes():
    url = "https://vgtimes.ru/free/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Try to find the content div
        content_div = soup.find('div', id='dle-content')
        if content_div:
            print("Found #dle-content")
            
            # Look for articles within content
            articles = content_div.select("div[class*='news']")
            print(f"\nFound {len(articles)} articles")
            
            if articles:
                # Analyze the first few articles in detail
                for i, article in enumerate(articles[:3]):
                    print(f"\n=== Article {i+1} ===")
                    print("Classes:", article.get('class', []))
                    
                    # Look for title elements with different approaches
                    print("\nPossible title elements:")
                    
                    # Direct text in links
                    links = article.find_all('a')
                    for link in links:
                        print(f"\nLink text: {link.get_text(strip=True)}")
                        print(f"Link href: {link.get('href', '')}")
                        print(f"Link classes: {link.get('class', [])}")
                    
                    # Look for specific elements that might contain titles
                    title_candidates = [
                        article.find('h2'),
                        article.find('h3'),
                        article.find('h4'),
                        article.find('div', class_='title'),
                        article.find('a', class_='title'),
                        article.find('div', class_='news-name'),
                        article.find('div', class_='item-name'),
                    ]
                    
                    for elem in title_candidates:
                        if elem:
                            print(f"\nFound potential title element: {elem.name}")
                            print(f"Classes: {elem.get('class', [])}")
                            print(f"Text: {elem.get_text(strip=True)}")
                    
                    # Print the full HTML structure for manual inspection
                    print("\nFull article HTML:")
                    print(article.prettify())
                    print("\n" + "="*50)
            
        else:
            print("Could not find #dle-content")
            print("\nPage structure:")
            print(soup.prettify()[:1000])
        
    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    inspect_vgtimes() 