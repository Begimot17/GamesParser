"""Sanity checks for small-LLM output: accept a field only if the source text backs it up."""
import re
from urllib.parse import urlparse

STORE_DOMAINS = {
    "steam": ("store.steampowered.com",),
    "epicgames": ("store.epicgames.com", "epicgames.com"),
    "gog": ("gog.com", "www.gog.com"),
    "itch": ("itch.io",),
}
MAX_TITLE_LEN = 200
MIN_CONTENT_RATIO = 0.3  # of the original content length
MIN_WORD_SUPPORT = 0.8  # share of LLM content words that must occur in the page text

_WORD = re.compile(r"\w{4,}", re.UNICODE)


def _words(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text or "")}


def _store_matches(store: str, url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in STORE_DOMAINS.get(store, ()))


def validate_store_links(links: dict, page_text: str, known_links: dict) -> dict:
    """Keep links that point to the matching store and are present in the page (or already known)."""
    known = {str(u) for v in (known_links or {}).values() for u in (v if isinstance(v, list) else [v])}
    valid = {}
    for store, url in (links or {}).items():
        url = str(url).strip()
        if _store_matches(store, url) and (url in page_text or url in known):
            valid[store] = url
    return valid


def validate_title(llm_title: str, original: str) -> str:
    """Return the LLM title if sane, else the original."""
    if not llm_title or len(llm_title) > MAX_TITLE_LEN:
        return original
    if original and not (_words(llm_title) & _words(original)):
        return original
    return llm_title


def validate_content(llm_content: str, original: str, page_text: str) -> str:
    """Return the LLM content if it is not a truncation and is made of words from the page, else the original."""
    if not llm_content:
        return original
    if original and len(llm_content) < MIN_CONTENT_RATIO * len(original):
        return original
    words = _words(llm_content)
    if words and len(words & _words(page_text)) / len(words) < MIN_WORD_SUPPORT:
        return original
    return llm_content
