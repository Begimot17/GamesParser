import asyncio
import hashlib
import os
import re
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Awaitable, Callable, Optional, Self
from urllib.parse import quote, urljoin, urlparse

import aiofiles
import aiohttp
from bs4 import BeautifulSoup, Tag

from src.bot.retry_handler import retry
from src.common.logger import logger
from src.config.config import RATE_LIMIT_DELAY, settings
from src.services.llm_validator import validate_content, validate_store_links, validate_title


class BaseParser(ABC):
    """Abstract base parser with shared HTTP, config, and enrichment logic."""

    def __init__(self, config_key: str = "", default_url: str = ""):
        # Load parser config from YAML
        self.config: dict = settings.PARSERS_CONFIG.get(config_key, {}) if config_key else {}
        if not self.config and default_url:
            logger.warning("[%s] configuration not found in settings! Using defaults.", config_key)
            self.TARGET_URLS: list[str] = [default_url]
        else:
            raw = self.config.get("target_urls", default_url or "")
            if isinstance(raw, str):
                self.TARGET_URLS = [u.strip() for u in raw.split(",") if u.strip()]
            elif isinstance(raw, list):
                self.TARGET_URLS = raw
            else:
                self.TARGET_URLS = [default_url] if default_url else []

        # HTTP client state
        self.headers = {"User-Agent": settings.USER_AGENT}
        self.last_request_time: float = 0.0
        self.session: Optional[aiohttp.ClientSession] = None
        self.default_base_url: Optional[str] = self.TARGET_URLS[0] if self.TARGET_URLS else None

        # Config-driven settings
        self.REQUEST_TIMEOUT: int = self.config.get("request_timeout", settings.REQUEST_TIMEOUT)
        self.MAX_TEXT_LENGTH: int = self.config.get("max_text_length", settings.MAX_TEXT_LENGTH)
        self.VALID_IMAGE_EXTENSIONS: tuple = tuple(
            self.config.get("valid_image_extensions", [".jpg", ".jpeg", ".png", ".gif", ".webp"])
        )
        self.RATE_LIMIT_DELAY: float = self.config.get("rate_limit_delay", RATE_LIMIT_DELAY)
        self.SELECTORS: dict = self.config.get("selectors", {})
        self.STORE_CONFIG: dict = self.config.get("stores", {})

        # Lazily imported to avoid circular deps at module load time
        self._llm = None
        self._price_service = None
        self._services_initialized = False
        self._is_first_run: bool = False
        # Set by ParserManager: lets a parser skip already-processed posts BEFORE the costly
        # article fetch and price lookups (otherwise every cycle re-fetches every known post).
        self.is_known: Optional[Callable[[str], Awaitable[bool]]] = None

    def _init_services(self) -> None:
        """Lazily initialise LLM and PriceService (avoids import-time circular deps)."""
        if self._services_initialized:
            return
        from src.services.price_service import PriceService
        self._llm = self._create_llm() if settings.ENABLE_LLM else None
        self._price_service = PriceService()
        self._services_initialized = True

    @staticmethod
    def _create_llm():
        if settings.LLM_PROVIDER == "g4f":
            from src.services.llm_g4f import LLMG4F
            return LLMG4F(model_name=settings.LLM_MODEL)
        from src.services.llm_ollama import LLMOllama
        return LLMOllama()

    @property
    def llm(self):
        self._init_services()
        return self._llm

    @llm.setter
    def llm(self, value):
        self._llm = value
        self._services_initialized = True

    @property
    def price_service(self):
        self._init_services()
        return self._price_service

    @price_service.setter
    def price_service(self, value):
        self._price_service = value
        self._services_initialized = True

    # ── Context manager ───────────────────────────────────────────────────

    async def __aenter__(self) -> Self:
        self.session = aiohttp.ClientSession(headers=self.headers)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.session:
            await self.session.close()

    # ── HTTP helpers ──────────────────────────────────────────────────────

    async def _rate_limit(self) -> None:
        current_time = asyncio.get_event_loop().time()
        elapsed = current_time - self.last_request_time
        if elapsed < self.RATE_LIMIT_DELAY:
            await asyncio.sleep(self.RATE_LIMIT_DELAY - elapsed)
        self.last_request_time = asyncio.get_event_loop().time()

    @retry(max_retries=3, base_delay=2, backoff_factor=2)
    async def _fetch_page(self, url: str) -> str:
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession(headers=self.headers)
        async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT)) as response:
            response.raise_for_status()
            html_content = await response.text()
            await self._save_fetched_html(html_content, url)
            return html_content

    # ── Text helpers ──────────────────────────────────────────────────────

    def _clean_text(self, text: str) -> str:
        if not text:
            return ""
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"<script.*?</script>", "", text, flags=re.DOTALL)
        text = re.sub(r"<style.*?</style>", "", text, flags=re.DOTALL)
        return text.strip()

    def _normalize_url(self, url: str, base_url: Optional[str] = None) -> str:
        if not url:
            return ""
        effective_base = base_url if base_url is not None else self.default_base_url
        try:
            if url.startswith("//"):
                url = f"https:{url}"
            elif url.startswith("/"):
                if not effective_base:
                    logger.warning("Relative URL '%s' without base_url", url)
                    return ""
                url = urljoin(effective_base, url)
            elif not urlparse(url).scheme:
                url = f"https://{url}"
            return url
        except Exception as e:
            logger.error("Error normalising URL %s: %s", url, e)
            return ""

    def _clean_store_url(self, url: str, store_name: str) -> str:
        if not url:
            return ""
        store_info = self.STORE_CONFIG.get(store_name, {})
        domain = store_info.get("domain")
        validation_regex = store_info.get("validation_regex")

        if not domain or domain not in url:
            return ""

        url = self._normalize_url(url)
        url = url.split("?")[0].split("#")[0]

        host = (urlparse(url).hostname or "").lower()
        if host != domain and not host.endswith("." + domain):
            return ""  # domain only appeared in the path/query of a foreign host

        if validation_regex and not re.search(validation_regex, url):
            return ""

        if store_name == "itch":
            p = urlparse(url)
            netloc = p.netloc.lower()
            if netloc == "itch.io" or not netloc.endswith(".itch.io"):
                return ""
            if not p.path.strip("/"):
                return ""

        return url

    # ── HTML persistence ──────────────────────────────────────────────────

    @staticmethod
    def _html_filename(url: str) -> str:
        """Filesystem-safe name for a URL; long URLs are truncated with a hash (Windows path limit)."""
        name = quote(url, safe="")
        if len(name) > 150:
            name = f"{name[:120]}_{hashlib.sha1(url.encode()).hexdigest()[:12]}"
        return f"{name}.html"

    def _save_html_on_error(self, html: str, url: str) -> None:
        if not settings.SAVE_HTML:
            return
        os.makedirs(settings.HTML_DIR, exist_ok=True)
        filepath = os.path.join(settings.HTML_DIR, self._html_filename(url))
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html)
        except IOError as e:
            logger.error("Error saving HTML for %s: %s", url, e)

    async def _save_fetched_html(self, html_content: str, url: str) -> None:
        if not settings.SAVE_ALL_FETCHED_HTML:
            return
        os.makedirs(settings.FETCHED_HTML_DIR, exist_ok=True)
        filepath = os.path.join(settings.FETCHED_HTML_DIR, self._html_filename(url))
        try:
            async with aiofiles.open(filepath, "w", encoding="utf-8") as f:
                await f.write(html_content)
        except IOError as e:
            logger.error("Error saving fetched HTML for %s: %s", url, e)

    async def _already_known(self, post_id: str) -> bool:
        """True if the manager says this post was processed already (errors mean 'unknown')."""
        if not self.is_known:
            return False
        try:
            return bool(await self.is_known(post_id))
        except Exception as e:
            logger.warning("[%s] is_known check failed for %s: %s", self.__class__.__name__, post_id, e)
            return False

    # ── Shared enrichment helpers ─────────────────────────────────────────

    async def _build_game_info_raw(self, store_links: dict) -> dict:
        """Fetch and serialize GameInfo for all store_links. Returns empty dict on failure."""
        if not store_links:
            return {}
        try:
            infos = await self.price_service.get_all_info(store_links)
            return {
                store: (
                    info.to_dict() if info and not isinstance(info, list)
                    else [i.to_dict() if i else None for i in info] if isinstance(info, list)
                    else None
                )
                for store, info in infos.items()
            }
        except Exception as e:
            logger.warning("[%s] Failed to fetch game info: %s", self.__class__.__name__, e)
            return {}

    async def _fetch_full_page_text(self, url: str, preloaded_html: Optional[str] = None) -> str:
        """Return cleaned text content of a page for LLM processing (up to 10 000 chars)."""
        try:
            html = preloaded_html if preloaded_html else await self._fetch_page(url)
            if not html:
                return ""
            soup = BeautifulSoup(html, "html.parser")
            for el in soup(["script", "style", "nav", "header", "footer", "aside"]):
                el.decompose()
            content_selector = self.SELECTORS.get("content", "")
            main = (
                soup.select_one(content_selector) if content_selector
                else soup.select_one("article, .story, .post-content, main")
            )
            text = main.get_text(" ", strip=True) if main else soup.get_text(" ", strip=True)
            return text[:10000]
        except Exception as e:
            logger.error("Error fetching page text for %s: %s", url, e, exc_info=True)
            return ""

    async def _update_post_with_llm_data(
        self,
        title: str,
        content: str,
        images: list,
        link: str,
        store_links: dict,
        preloaded_html: Optional[str] = None,
    ) -> tuple[str, str, list, dict]:
        """Enrich post fields using the configured LLM. Returns updated (title, content, images, store_links)."""
        page_text = await self._fetch_full_page_text(link, preloaded_html=preloaded_html)
        if page_text:
            llm_data = await self.llm.extract_article_info(page_text, link)
            logger.info("[%s] LLM extracted data for %s: %s", self.__class__.__name__, link, llm_data)
            title = validate_title(llm_data.get("title"), title)
            content = validate_content(llm_data.get("content"), content, page_text)
            validated = validate_store_links(llm_data.get("store_links"), page_text, store_links)
            if validated:
                store_links = {**validated, **store_links}  # parsed links win over LLM ones
            if llm_data.get("images"):
                images.extend(llm_data["images"])
        return title, content, images, store_links

    # ── Default streaming / fetching ──────────────────────────────────────

    async def _process_url(self, target_url: str) -> AsyncGenerator:
        """Fetch a page, parse all articles, yield Post objects. Override for custom behaviour."""
        html = ""
        name = self.__class__.__name__
        try:
            await self._rate_limit()
            logger.info("[%s] Processing page: %s", name, target_url)
            html = await self._fetch_page(target_url)
            logger.info("[%s] Got response, length: %d", name, len(html))

            soup = BeautifulSoup(html, "html.parser")
            articles = soup.select(self.SELECTORS["articles"])
            logger.info("[%s] Found %d articles on page", name, len(articles))

            for article in articles:
                try:
                    post = await self._parse_article(article)
                    if post:
                        logger.info("[%s] Yielding post %s", name, post.id)
                        yield post
                except Exception as e:
                    logger.error("[%s] Error processing article: %s", name, e, exc_info=True)
        except Exception as e:
            logger.error("[%s] Unexpected error in _process_url for %s: %s", name, target_url, e, exc_info=True)
            if html:
                self._save_html_on_error(html, target_url)

    async def fetch_posts(self, url: Optional[str] = None) -> list:
        name = self.__class__.__name__
        logger.info("[%s] Starting fetch_posts...", name)
        all_posts = []
        pages = self.config.get("initial_pages", 1) if self._is_first_run else 1
        urls = [url] if url else self._build_page_urls(pages)
        for target_url in urls:
            async for post in self._process_url(target_url):
                all_posts.append(post)
        logger.info("[%s] fetch_posts completed. Total posts: %d", name, len(all_posts))
        return all_posts

    async def stream_posts(self) -> AsyncGenerator:
        name = self.__class__.__name__
        logger.info("[%s] Starting stream_posts...", name)
        pages = self.config.get("initial_pages", 1) if self._is_first_run else 1
        for target_url in self._build_page_urls(pages):
            async for post in self._process_url(target_url):
                yield post
        logger.info("[%s] stream_posts completed", name)

    # ── Abstract interface ────────────────────────────────────────────────

    @abstractmethod
    def _build_page_urls(self, pages: int) -> list[str]:
        """Return list of page URLs for pagination (page 1 = base URL, then incrementally)."""

    @abstractmethod
    async def _parse_article(self, article_html: Tag, **kwargs) -> Optional[object]:
        """Parse a single article Tag and return a Post, or None to skip."""
