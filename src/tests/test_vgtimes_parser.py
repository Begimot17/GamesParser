import asyncio
import logging
from unittest import TestCase, main
from unittest.mock import MagicMock, patch

from bs4 import BeautifulSoup

from src.models.models import Post
from src.parser.vgtimes_parser import VGTimesParser

# Настройка логирования для тестов
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class TestVGTimesParser(TestCase):
    def setUp(self):
        """Подготовка тестового окружения"""
        self.parser = VGTimesParser()
        self.test_html = """
        <div id="dle-content">
            <div class="news_list_footer">
                <h2><a class="title" href="/free/123456-test-article.html">Test Article Title</a></h2>
                <div class="rrating"><div class="text">4.5</div></div>
                <span class="post_date">5 апреля 2025, 23:22</span>
                <img rel="mainimage" src="https://example.com/image.jpg">
            </div>
            <div class="news_list_footer">
                <h2><a class="title" href="/free/123457-another-article.html">Another Article</a></h2>
                <div class="rrating"><div class="text">3.8</div></div>
                <span class="post_date">6 апреля 2025, 10:15</span>
                <img rel="mainimage" src="https://example.com/another.jpg">
            </div>
        </div>
        """

    def test_parse_article(self):
        """Тест парсинга отдельной статьи"""
        soup = BeautifulSoup(self.test_html, "html.parser")
        article = soup.select_one("div.news_list_footer")

        post = self.parser._parse_article(article)

        self.assertIsNotNone(post)
        self.assertEqual(post.id, "123456")
        self.assertEqual(post.title, "Test Article Title")
        self.assertEqual(post.link, "/free/123456-test-article.html")
        self.assertEqual(post.metadata.rating, "4.5")
        self.assertEqual(len(post.metadata.images), 1)
        self.assertEqual(post.metadata.images[0], "https://example.com/image.jpg")

    def test_process_page(self):
        """Тест обработки целой страницы"""
        posts = self.parser._process_page(self.test_html)

        self.assertEqual(len(posts), 2)
        self.assertIsInstance(posts[0], Post)
        self.assertIsInstance(posts[1], Post)

        # Проверяем первую статью
        self.assertEqual(posts[0].id, "123456")
        self.assertEqual(posts[0].title, "Test Article Title")

        # Проверяем вторую статью
        self.assertEqual(posts[1].id, "123457")
        self.assertEqual(posts[1].title, "Another Article")

    @patch("aiohttp.ClientSession.get")
    async def test_fetch_posts(self, mock_get):
        """Тест получения постов с моком HTTP запроса"""
        # Настраиваем мок для HTTP запроса
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.text = MagicMock(return_value=self.test_html)
        mock_get.return_value.__aenter__.return_value = mock_response

        async with self.parser as parser:
            posts = await parser.fetch_posts()

            self.assertEqual(len(posts), 2)
            self.assertIsInstance(posts[0], Post)
            self.assertIsInstance(posts[1], Post)

    def test_clean_text(self):
        """Тест очистки текста"""
        dirty_text = "  Test   Text  \n  With  \t  Spaces  "
        cleaned_text = self.parser._clean_text(dirty_text)

        self.assertEqual(cleaned_text, "Test Text With Spaces")

    def test_extract_post_id(self):
        """Тест извлечения ID поста из URL"""
        test_cases = [
            ("/free/123456-test-article.html", "123456"),
            ("https://vgtimes.ru/free/789012-another-test.html", "789012"),
            ("invalid-url", ""),
            ("", ""),
        ]

        for url, expected_id in test_cases:
            with self.subTest(url=url):
                post_id = self.parser._extract_post_id(url)
                self.assertEqual(post_id, expected_id)

    def test_parse_date(self):
        """Тест парсинга даты"""
        test_cases = [
            ("5 апреля 2025, 23:22", "2025-04-05T23:22:00"),
            ("15 марта 2025, 10:15", "2025-03-15T10:15:00"),
            ("invalid date", ""),
            ("", ""),
        ]

        for date_str, expected_iso in test_cases:
            with self.subTest(date_str=date_str):
                parsed_date = self.parser._parse_date(date_str)
                if expected_iso:
                    self.assertEqual(parsed_date, expected_iso)
                else:
                    self.assertEqual(parsed_date, "")

    def test_fetch_posts_multiple_urls(self):
        """Test fetching posts from multiple URLs."""
        parser = VGTimesParser()
        assert len(parser.TARGET_URLS) == 2
        assert "https://vgtimes.ru/free/" in parser.TARGET_URLS
        assert "https://vgtimes.ru/gaming-news/" in parser.TARGET_URLS

    def test_fetch_posts_single_url(self):
        """Test fetching posts from a single URL."""
        parser = VGTimesParser()
        test_url = "https://vgtimes.ru/free/"
        posts = asyncio.run(parser.fetch_posts(test_url))
        assert isinstance(posts, list)


if __name__ == "__main__":
    main()
