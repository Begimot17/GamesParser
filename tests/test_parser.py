import json
from pathlib import Path
from typing import Dict

import pytest
from bs4 import BeautifulSoup

from src.parser.parser import Parser
from src.models.models import Post

# Load expected test data
def load_expected_data() -> Dict:
    expected_file = Path(__file__).parent / "expected.json"
    with open(expected_file, "r", encoding="utf-8") as f:
        return json.load(f)

@pytest.fixture
def parser():
    return Parser()

@pytest.fixture
def expected_data():
    return load_expected_data()

def test_parse_article(parser, expected_data):
    """Test parsing individual articles."""
    html_dir = Path("html_articles")
    if not html_dir.exists():
        pytest.skip("html_articles directory not found")
        
    for html_file in html_dir.glob("*.html"):
        # Skip if no expected data for this file
        if html_file.stem not in expected_data:
            continue
            
        # Read HTML content
        with open(html_file, "r", encoding="utf-8") as f:
            html_content = f.read()
            
        # Parse the article
        soup = BeautifulSoup(html_content, "html.parser")
        article = soup.find("article")
        assert article is not None, f"No article found in {html_file}"
        
        # Parse the post
        post = parser._parse_article(article)
        assert post is not None, f"Failed to parse article in {html_file}"
        
        # Get expected data
        expected = expected_data[html_file.stem]
        
        # Compare fields
        assert post.id == expected["id"], f"ID mismatch in {html_file}"
        assert post.title == expected["title"], f"Title mismatch in {html_file}"
        assert post.link == expected["link"], f"Link mismatch in {html_file}"
        assert post.text == expected["text"], f"Text mismatch in {html_file}"
        assert post.rating == expected["rating"], f"Rating mismatch in {html_file}"
        assert set(post.images) == set(expected["images"]), f"Images mismatch in {html_file}"
        assert post.stores == expected["stores"], f"Stores mismatch in {html_file}"
        
        # Compare metadata
        assert post.metadata.author == expected["metadata"]["author"], f"Author mismatch in {html_file}"
        assert post.metadata.date == expected["metadata"]["date"], f"Date mismatch in {html_file}"
        assert post.metadata.tags == expected["metadata"]["tags"], f"Tags mismatch in {html_file}"

def test_normalize_url(parser):
    """Test URL normalization."""
    test_cases = [
        ("https://example.com", "https://example.com"),
        ("//example.com", "https://example.com"),
        ("/path", "https://pikabu.ru/path"),
        ("example.com", "https://example.com"),
        ("", ""),
        (None, ""),
    ]
    
    for url, expected in test_cases:
        result = parser._normalize_url(url)
        assert result == expected, f"URL normalization failed for {url}"

def test_clean_text(parser):
    """Test text cleaning."""
    test_cases = [
        ("  Hello  World  ", "Hello World"),
        ("Hello\nWorld", "Hello World"),
        ("Hello  \n  World", "Hello World"),
        ("", ""),
        (None, ""),
    ]
    
    for text, expected in test_cases:
        result = parser._clean_text(text)
        assert result == expected, f"Text cleaning failed for '{text}'"

def test_rate_limit(parser):
    """Test rate limiting."""
    import asyncio
    
    async def test():
        # Reset the last request time to ensure consistent testing
        parser.last_request_time = 0
        
        # First call should not delay
        start_time = asyncio.get_event_loop().time()
        await parser._rate_limit()
        first_call_time = asyncio.get_event_loop().time()
        
        # Second call should delay
        await parser._rate_limit()
        second_call_time = asyncio.get_event_loop().time()
        
        # Check that the second call had the required delay
        time_diff = second_call_time - first_call_time
        assert time_diff >= parser.RATE_LIMIT_DELAY, f"Rate limit delay not enforced. Expected >= {parser.RATE_LIMIT_DELAY}, got {time_diff}"
        
    asyncio.run(test())

def test_parse_and_print_messages(parser):
    """Test parsing and printing messages without sending to Telegram."""
    import asyncio
    
    async def test():
        async with parser as p:
            # Получаем посты
            posts = await p.fetch_posts()
            
            # Выводим информацию о каждом посте
            for post in posts:
                print("\n" + "="*50)
                print(f"ID: {post.id}")
                print(f"Title: {post.title}")
                print(f"Link: {post.link}")
                print(f"Content: {post.content[:200]}...")  # Первые 200 символов
                print(f"Date: {post.date}")
                print(f"Rating: {post.metadata.rating}")
                print("Store Links:")
                for store, link in post.metadata.store_links.items():
                    print(f"  {store}: {link}")
                print("Images:")
                for img in post.metadata.images:
                    print(f"  {img}")
                print("="*50)
            
            return len(posts)
    
    # Запускаем тест
    num_posts = asyncio.run(test())
    assert num_posts > 0, "No posts were parsed"

if __name__ == "__main__":
    pytest.main([__file__]) 