import asyncio

import pytest
from bs4 import BeautifulSoup

from src.parser.vgtimes_parser import VGTimesParser


@pytest.fixture
def parser():
    return VGTimesParser()


@pytest.fixture
def sample_article_html():
    return """
    <div class="news_list_footer">
        <a class="scomm" href="https://vgtimes.ru/free/123799-v-steam-stal-vremenno-besplatnym-avtobattler-mechabellum.html">
            Бесплатная игра в Steam
        </a>
        <div class="rrating">
            <div class="text">42</div>
        </div>
        <img rel="mainimage" src="https://example.com/image1.jpg">
        <img rel="mainimage" src="https://example.com/image2.jpg">
        <span class="post_date">5 апреля 2025, 23:22</span>
        <a class="l_ks" target="_blank" href="https://store.steampowered.com/app/123">Steam Link</a>
    </div>
    """


@pytest.fixture
def sample_page_html():
    return """
    <div id="dle-content">
        <div class="news_list_footer">
            <a class="scomm" href="https://vgtimes.ru/free/123799-game1.html">Game 1</a>
            <div class="rrating"><div class="text">42</div></div>
            <img rel="mainimage" src="https://example.com/game1.jpg">
            <span class="post_date">5 апреля 2025, 23:22</span>
        </div>
        <div class="news_list_footer">
            <a class="scomm" href="https://vgtimes.ru/free/123800-game2.html">Game 2</a>
            <div class="rrating"><div class="text">24</div></div>
            <img rel="mainimage" src="https://example.com/game2.jpg">
            <span class="post_date">6 апреля 2025, 12:00</span>
        </div>
    </div>
    """


def test_clean_text():
    """Test text cleaning functionality."""
    parser = VGTimesParser()
    test_cases = [
        ("  Hello  World  ", "Hello World"),
        ("Hello\nWorld", "Hello World"),
        ("<script>alert('test')</script>Hello", "Hello"),
        ("<style>body {color: red}</style>Hello", "Hello"),
        ("", ""),
        (None, ""),
    ]

    for text, expected in test_cases:
        result = parser._clean_text(text)
        assert result == expected, f"Text cleaning failed for '{text}'"


def test_clean_store_url():
    """Test store URL cleaning functionality."""
    parser = VGTimesParser()
    test_cases = [
        (
            "https://store.steampowered.com/app/123?utm_source=test",
            "https://store.steampowered.com/app/123",
        ),
        ("http://epicgames.com#test", "http://epicgames.com"),
        ("gog.com", "https://gog.com"),
        ("", "https://"),
    ]

    for url, expected in test_cases:
        result = parser._clean_store_url(url)
        assert result == expected, f"Store URL cleaning failed for '{url}'"


def test_extract_store_links():
    """Test store links extraction functionality."""
    parser = VGTimesParser()
    test_cases = [
        (
            "Check out [Steam](https://store.steampowered.com/app/123)",
            {"Steam": "https://store.steampowered.com/app/123"},
        ),
        (
            "Check out [Epic Games](https://epicgames.com) and [GOG](https://gog.com)",
            {"Epic Games": "https://epicgames.com", "GOG": "https://gog.com"},
        ),
        ("No store links here", {}),
    ]

    for text, expected in test_cases:
        result = parser._extract_store_links(text)
        assert result == expected, f"Store links extraction failed for '{text}'"


def test_parse_date():
    """Test date parsing functionality."""
    parser = VGTimesParser()
    test_cases = [
        ("5 апреля 2025, 23:22", "2025-04-05T23:22:00"),
        ("15 декабря 2023, 12:00", "2023-12-15T12:00:00"),
        ("invalid date", ""),
    ]

    for date_str, expected in test_cases:
        result = parser._parse_date(date_str)
        assert result == expected, f"Date parsing failed for '{date_str}'"


def test_extract_post_id():
    """Test post ID extraction functionality."""
    parser = VGTimesParser()
    test_cases = [
        (
            "https://vgtimes.ru/free/123799-v-steam-stal-vremenno-besplatnym-avtobattler-mechabellum.html",
            "123799",
        ),
        ("https://vgtimes.ru/free/456789-test-post.html", "456789"),
        ("invalid-url", ""),
    ]

    for url, expected in test_cases:
        result = parser._extract_post_id(url)
        assert result == expected, f"Post ID extraction failed for '{url}'"


def test_parse_article(parser, sample_article_html):
    """Test parsing a single article."""
    soup = BeautifulSoup(sample_article_html, "html.parser")
    article = soup.find("div", class_="news_list_footer")

    post = parser._parse_article(article)
    assert post is not None, "Failed to parse article"
    assert post.id == "123799", "Wrong post ID"
    assert "Бесплатная игра" in post.title, "Wrong title"
    assert post.metadata.rating == "42", "Wrong rating"
    assert len(post.metadata.images) == 2, "Wrong number of images"
    assert all(img.endswith(".jpg") for img in post.metadata.images), (
        "Invalid image URLs"
    )


def test_process_page(parser, sample_page_html):
    """Test processing a full page of articles."""
    posts = parser._process_page(sample_page_html)

    assert len(posts) == 2, "Wrong number of posts parsed"

    # Check first post
    assert posts[0].id == "123799", "Wrong ID for first post"
    assert posts[0].title == "Game 1", "Wrong title for first post"
    assert posts[0].metadata.rating == "42", "Wrong rating for first post"

    # Check second post
    assert posts[1].id == "123800", "Wrong ID for second post"
    assert posts[1].title == "Game 2", "Wrong title for second post"
    assert posts[1].metadata.rating == "24", "Wrong rating for second post"


@pytest.mark.asyncio
async def test_rate_limit():
    """Test rate limiting functionality."""
    parser = VGTimesParser()
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
    assert time_diff >= parser.RATE_LIMIT_DELAY, (
        f"Rate limit delay not enforced. Expected >= {parser.RATE_LIMIT_DELAY}, got {time_diff}"
    )


@pytest.mark.asyncio
async def test_fetch_page():
    """Test page fetching functionality."""
    parser = VGTimesParser()
    # Test with a valid URL
    url = "https://vgtimes.ru/free/"
    content = await parser._fetch_page(url)
    assert content is not None
    assert len(content) > 0

    # Test with an invalid URL that should trigger all retries
    url = "https://invalid-url-that-does-not-exist-123456789.com"
    with pytest.raises(Exception):
        await parser._fetch_page(url)

    # Test with a URL that returns non-200 status
    url = "https://httpstat.us/404"
    with pytest.raises(Exception):
        await parser._fetch_page(url)


def test_is_store_url():
    """Test store URL detection functionality."""
    parser = VGTimesParser()
    test_cases = [
        ("https://store.steampowered.com/app/123", True),
        ("https://epicgames.com/store", True),
        ("https://gog.com/game", True),
        ("https://example.com", False),
        ("", False),
    ]

    for url, expected in test_cases:
        result = parser._is_store_url(url)
        assert result == expected, f"Store URL detection failed for '{url}'"


if __name__ == "__main__":
    pytest.main([__file__])
