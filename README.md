# GamesParser

Асинхронный парсер игровых новостей с автоматической отправкой в Telegram-канал.

## Источники

| Источник | URL | Что парсит |
|----------|-----|------------|
| Pikabu | `pikabu.ru/community/steam` | Посты сообщества Steam |
| VGTimes | `vgtimes.ru/free/` | Новости о бесплатных играх |
| StopGame | `stopgame.ru/news` | Игровые новости |

## Архитектура

```
main.py (NewsMonitor)
├── ParserManager
│   ├── PikabuParser
│   ├── VGTimesParser
│   └── StopGameParser
├── SQLiteStorage (общий, shared)
└── TelegramNewsBot
    ├── MessageFormatter
    └── RetryHandler
```

- Все парсеры используют **один** `SQLiteStorage` (передаётся через конструктор)
- Парсинг потоковый (`stream_posts`) — посты отправляются сразу после обнаружения
- HTML-страницы опционально сохраняются в `fetched_html/` для отладки

## Настройка

Создайте файл `.env` в корне проекта:

| Переменная | Обязательная | Описание |
|-----------|:---:|---------|
| `TELEGRAM_BOT_TOKEN` | ✅ | Токен бота от @BotFather |
| `TELEGRAM_CHANNEL_ID` | ✅ | ID или @username канала |
| `DB_PATH` | — | Путь к БД (по умолчанию `news_bot.db`) |
| `TEST_DB_PATH` | — | Путь к тестовой БД (по умолчанию `test_news_bot.db`) |
| `TEST_CHANNEL_ID` | — | Канал для тестов |
| `CHECK_INTERVAL` | — | Интервал проверки в сек (по умолчанию `300`) |
| `MAX_POSTS_PER_CHECK` | — | Макс. постов за цикл (по умолчанию `5`) |
| `SAVE_ALL_FETCHED_HTML` | — | Сохранять HTML для отладки (`True`/`False`) |
| `ENABLE_LLM` | — | Обогащение данных через LLM (`False`) |
| `DEBUG` | — | Режим отладки (`False`) |

Пример `.env`:
```env
TELEGRAM_BOT_TOKEN=1234567890:ABCDEFabcdef...
TELEGRAM_CHANNEL_ID=@my_games_channel
DB_PATH=news_bot.db
TEST_DB_PATH=test_news_bot.db
SAVE_ALL_FETCHED_HTML=True
```

## Установка и запуск

```bash
# Установить зависимости через Poetry
poetry install

# Запустить
poetry run python main.py
```

Или через pip:
```bash
pip install -r requirements.txt
python main.py
```

## Запуск тестов

```bash
poetry run python -m pytest tests/ -v
```

## Формат сообщений

```
🎮 Название игры

<i>Источник: Pikabu</i>

Текст статьи до 600 символов...

📅 09.03.2026 14:30 | ⭐ 150 | 👁 45K
🎮 Steam | 🟣 Epic Games
#тег1 #тег2_с_кириллицей
```

## Добавление нового парсера

1. Создайте `src/parsers/my_parser.py`, унаследовав от `BaseParser`
2. Реализуйте методы `fetch_posts()` и `stream_posts()`
3. Добавьте конфигурацию в `src/config/parsers.yml`
4. Добавьте парсер в список `self.parsers` в `main.py`, передав `storage=self.storage`
5. Напишите тесты в `tests/test_my_parser.py`
