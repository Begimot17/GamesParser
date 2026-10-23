"""Tests for LLM output validation."""
import unittest

from src.services.llm_validator import validate_content, validate_store_links, validate_title


ORIG = "Epic Games раздаёт Neon Drifter бесплатно"
PAGE = "Epic Games раздаёт Neon Drifter бесплатно. https://store.epicgames.com/ru/p/neon-drifter Комментарии (12)"


class TestStoreLinks(unittest.TestCase):
    def test_keeps_link_present_on_page_for_right_store(self):
        links = {"epicgames": "https://store.epicgames.com/ru/p/neon-drifter"}
        self.assertEqual(validate_store_links(links, PAGE, {}), links)

    def test_drops_hallucinated_link(self):
        links = {"steam": "https://store.steampowered.com/app/999/"}
        self.assertEqual(validate_store_links(links, PAGE, {}), {})

    def test_drops_link_under_wrong_store(self):
        links = {"steam": "https://store.epicgames.com/ru/p/neon-drifter"}
        self.assertEqual(validate_store_links(links, PAGE, {}), {})

    def test_drops_lookalike_domain(self):
        url = "https://store.steampowered.com.evil.io/app/1/"
        self.assertEqual(validate_store_links({"steam": url}, url, {}), {})

    def test_accepts_link_known_from_parser(self):
        url = "https://store.steampowered.com/app/1/"
        self.assertEqual(validate_store_links({"steam": url}, "", {"steam": [url]}), {"steam": url})


class TestTitle(unittest.TestCase):
    def test_accepts_related_title(self):
        self.assertEqual(validate_title("Neon Drifter бесплатно", "Раздача Neon Drifter"), "Neon Drifter бесплатно")

    def test_rejects_unrelated_title(self):
        self.assertEqual(validate_title("Совсем другое", "Раздача Neon Drifter"), "Раздача Neon Drifter")

    def test_rejects_empty_and_overlong(self):
        self.assertEqual(validate_title(None, "Orig"), "Orig")
        self.assertEqual(validate_title("x" * 300, "Orig"), "Orig")


class TestContent(unittest.TestCase):
    def test_accepts_cleaned_content(self):
        self.assertEqual(validate_content(ORIG, ORIG + " Комментарии", PAGE), ORIG)

    def test_rejects_truncated_content(self):
        self.assertEqual(validate_content("Neon", ORIG * 5, PAGE), ORIG * 5)

    def test_rejects_invented_content(self):
        invented = "Игра получила множество наград критиков и восторженные отзывы игроков по всему миру"
        self.assertEqual(validate_content(invented, "orig", PAGE), "orig")


if __name__ == "__main__":
    unittest.main()
