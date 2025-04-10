import pytest
from bs4 import BeautifulSoup

from src.parser.parser import Parser


@pytest.fixture
def parser():
    return Parser(
        base_url="https://example.com",
        request_delay=0.1,
        max_retries=1,
        retry_delay=0.1,
    )


@pytest.fixture
def sample_html():
    return """
    <html>
        <body>
            <article class="post-card" data-post-id="123">
                <h2 class="post-card__title">Test Post</h2>
                <a class="post-card__link" href="/test-post">Link</a>
                <time datetime="2023-01-01T12:00:00Z">2023-01-01</time>
                <img class="post-card__image" src="/test-image.jpg">
                <a class="store-link" href="https://store.steampowered.com">Steam</a>
                <a class="store-link" href="https://itch.io">itch.io</a>
            </article>
        </body>
    </html>
    """


@pytest.mark.asyncio
async def test_parse_article(parser, sample_html):
    soup = BeautifulSoup(sample_html, "html.parser")
    article = soup.find("article")
    post = await parser._parse_article(article)

    assert post is not None
    assert post.id == 123
    assert post.title == "Test Post"
    assert post.link == "https://example.com/test-post"
    assert post.published_at is not None
    assert len(post.images) == 1
    assert post.images[0] == "https://example.com/test-image.jpg"
    assert post.stores is not None
    assert "Steam" in post.stores.model_dump()
    assert "itch.io" in post.stores.model_dump()


@pytest.mark.asyncio
async def test_parse_article_missing_data(parser):
    html = """
    <article class="post-card" data-post-id="123">
        <h2 class="post-card__title"></h2>
    </article>
    """
    soup = BeautifulSoup(html, "html.parser")
    article = soup.find("article")
    post = await parser._parse_article(article)

    assert post is None


@pytest.mark.asyncio
async def test_process_page(parser, sample_html):
    posts = await parser._process_page(sample_html)
    assert len(posts) == 1
    assert posts[0].id == 123


@pytest.mark.asyncio
async def test_process_page_empty(parser):
    posts = await parser._process_page("")
    assert len(posts) == 0


@pytest.mark.asyncio
async def test_process_page_invalid_html(parser):
    posts = await parser._process_page("<invalid>html</invalid>")
    assert len(posts) == 0


def test_normalize_url(parser):
    # Absolute URL
    assert (
        parser._normalize_url("https://example.com/test") == "https://example.com/test"
    )

    # Relative URL
    assert parser._normalize_url("/test") == "https://example.com/test"

    # Empty URL
    assert parser._normalize_url("") == ""

    # Invalid URL
    assert parser._normalize_url("invalid") == "https://example.com/invalid"
