import asyncio
import logging

import aiohttp
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


async def save_and_analyze_page():
    url = "https://vgtimes.ru/free/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(url) as response:
            html = await response.text()

            # Сохраняем HTML в файл
            with open("page.html", "w", encoding="utf-8") as f:
                f.write(html)
            logger.info("Saved HTML to page.html")

            # Анализируем структуру
            soup = BeautifulSoup(html, "html.parser")

            # Ищем основной контейнер
            content_div = soup.find("div", id="dle-content")
            if not content_div:
                logger.error("Could not find #dle-content")
                return

            # Ищем все ссылки на статьи
            article_links = content_div.find_all(
                "a", href=lambda x: x and "/free/" in x
            )
            logger.info(f"\nFound {len(article_links)} article links:")
            for link in article_links[:5]:  # показываем первые 5 ссылок
                logger.info(f"\nLink: {link.get('href')}")
                logger.info(f"Text: {link.get_text(strip=True)}")
                logger.info(f"Classes: {link.get('class', [])}")
                logger.info(
                    f"Parent: <{link.parent.name}> with classes {link.parent.get('class', [])}"
                )
                logger.info("Full element structure:")
                logger.info(link.prettify())


if __name__ == "__main__":
    asyncio.run(save_and_analyze_page())
