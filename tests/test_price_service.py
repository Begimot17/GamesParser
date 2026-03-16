"""Tests for PriceService."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.price_service import GameInfo, PriceService


STEAM_SUCCESS_RESPONSE = {
    "123": {
        "success": True,
        "data": {
            "name": "Test Game",
            "is_free": False,
            "price_overview": {
                "final_formatted": "199 ₴",
                "initial_formatted": "299 ₴",
                "discount_percent": 33,
            },
            "genres": [{"description": "Action"}, {"description": "RPG"}],
            "metacritic": {"score": 85},
            "developers": ["Test Dev Studio"],
            "review_score_desc": "Дуже позитивні",
        },
    },
}

EGS_FREE_PROMO_RESPONSE = {
    "data": {
        "Catalog": {
            "searchStore": {
                "elements": [
                    {
                        "productSlug": "free-game-slug",
                        "urlSlug": "free-game-slug",
                        "price": {
                            "totalPrice": {
                                "discountPrice": 0,
                                "originalPrice": 0,
                                "fmtPrice": {
                                    "originalPrice": "0",
                                    "discountPrice": "0",
                                },
                            },
                        },
                        "tags": [{"groupName": "genre", "name": "Adventure"}],
                        "developerDisplayName": "Indie Dev",
                    },
                ],
            },
        },
    },
}


class TestSteamInfo(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.service = PriceService()

    def _make_mock_session(self, json_data):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=json_data)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        return mock_session

    async def test_get_steam_info_success(self):
        """Steam API возвращает корректные данные."""
        mock_session = self._make_mock_session(STEAM_SUCCESS_RESPONSE)

        with patch("src.services.price_service.aiohttp.ClientSession", return_value=mock_session):
            info = await self.service.get_steam_info("https://store.steampowered.com/app/123/TestGame/")

        self.assertIsNotNone(info)
        self.assertEqual(info.name, "Test Game")
        self.assertEqual(info.price, "199 ₴")
        self.assertEqual(info.original_price, "299 ₴")
        self.assertEqual(info.discount_pct, 33)
        self.assertIn("Action", info.genre)
        self.assertEqual(info.metacritic, 85)
        self.assertEqual(info.developer, "Test Dev Studio")
        self.assertFalse(info.is_free)
        self.assertEqual(info.review_score, "Дуже позитивні")

    async def test_get_steam_info_not_found(self):
        """app_id не найден → None."""
        mock_session = self._make_mock_session({"999": {"success": False}})

        with patch("src.services.price_service.aiohttp.ClientSession", return_value=mock_session):
            info = await self.service.get_steam_info("https://store.steampowered.com/app/999/")

        self.assertIsNone(info)

    async def test_get_steam_info_invalid_url(self):
        """URL без app_id → None без HTTP-запроса."""
        info = await self.service.get_steam_info("https://store.steampowered.com/about/")
        self.assertIsNone(info)


class TestEGSInfo(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.service = PriceService()

    async def test_get_egs_info_invalid_url(self):
        """URL без /p/ slug → None без HTTP-запроса."""
        info = await self.service.get_egs_info("https://store.epicgames.com/ru/free-games")
        self.assertIsNone(info)

    async def test_get_egs_info_free_game(self):
        """EGS free game промо возвращает бесплатную игру."""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=EGS_FREE_PROMO_RESPONSE)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("src.services.price_service.aiohttp.ClientSession", return_value=mock_session):
            info = await self.service.get_egs_info("https://store.epicgames.com/p/free-game-slug")

        self.assertIsNotNone(info)
        self.assertTrue(info.is_free)
        self.assertEqual(info.genre, "Adventure")
        self.assertEqual(info.developer, "Indie Dev")


GOG_FREE_RESPONSE = {
    "products": [
        {
            "slug": "some-free-game",
            "title": "Some Free Game",
            "price": {"amount": "0"},
            "genres": ["Action", "RPG"],
            "developer": "GOG Dev",
        }
    ]
}


class TestGOGInfo(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.service = PriceService()

    def _make_mock_session(self, json_data):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=json_data)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        return mock_session

    async def test_get_gog_info_free_game(self):
        """GOG free game найден → GameInfo с is_free=True."""
        mock_session = self._make_mock_session(GOG_FREE_RESPONSE)
        with patch("src.services.price_service.aiohttp.ClientSession", return_value=mock_session):
            info = await self.service.get_gog_info("https://www.gog.com/game/some-free-game")

        self.assertIsNotNone(info)
        self.assertTrue(info.is_free)
        self.assertEqual(info.name, "Some Free Game")
        self.assertEqual(info.developer, "GOG Dev")

    async def test_get_gog_info_slug_not_found(self):
        """Игра не в списке бесплатных → None."""
        mock_session = self._make_mock_session(GOG_FREE_RESPONSE)
        with patch("src.services.price_service.aiohttp.ClientSession", return_value=mock_session):
            info = await self.service.get_gog_info("https://www.gog.com/game/unknown-game")

        self.assertIsNone(info)

    async def test_get_gog_info_bad_url(self):
        """URL без /game/ slug → None без HTTP-запроса."""
        info = await self.service.get_gog_info("https://www.gog.com/en/games")
        self.assertIsNone(info)

    async def test_gog_cache_reused(self):
        """Второй вызов использует TTL-кэш, не делая HTTP-запрос."""
        mock_session = self._make_mock_session(GOG_FREE_RESPONSE)
        with patch("src.services.price_service.aiohttp.ClientSession", return_value=mock_session):
            await self.service.get_gog_info("https://www.gog.com/game/some-free-game")
            await self.service.get_gog_info("https://www.gog.com/game/some-free-game")

        # With TTL cache, session.get should only be called once
        self.assertEqual(mock_session.get.call_count, 1)


class TestGetAllInfo(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.service = PriceService()

    async def test_get_all_info_concurrent(self):
        """get_all_info запускает запросы для нескольких ссылок параллельно."""
        steam_info = GameInfo(name="Steam Game", is_free=False)
        self.service.get_steam_info = AsyncMock(return_value=steam_info)
        self.service.get_egs_info = AsyncMock(return_value=None)

        store_links = {
            "steam": "https://store.steampowered.com/app/100/",
            "epicgames": "https://store.epicgames.com/p/some-game",
        }

        result = await self.service.get_all_info(store_links)

        self.assertEqual(result["steam"], steam_info)
        self.assertIsNone(result["epicgames"])
        self.service.get_steam_info.assert_called_once()
        self.service.get_egs_info.assert_called_once()

    async def test_get_all_info_bundle(self):
        """get_all_info обрабатывает несколько URL для одного магазина."""
        info1 = GameInfo(name="Game 1", is_free=True)
        info2 = GameInfo(name="Game 2", is_free=False)
        self.service.get_steam_info = AsyncMock(side_effect=[info1, info2])

        store_links = {
            "steam": [
                "https://store.steampowered.com/app/1/",
                "https://store.steampowered.com/app/2/",
            ],
        }

        result = await self.service.get_all_info(store_links)

        self.assertIsInstance(result["steam"], list)
        self.assertEqual(result["steam"][0], info1)
        self.assertEqual(result["steam"][1], info2)


if __name__ == "__main__":
    unittest.main()
