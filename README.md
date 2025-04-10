# Games Parser

A Python-based project for parsing and managing game-related content, featuring a Telegram bot interface and web scraping capabilities.

## Features

- Telegram bot integration for interactive content delivery
- Web scraping functionality using BeautifulSoup4
- Asynchronous operations with aiohttp and aiofiles
- SQLite database support with SQLAlchemy
- Environment variable management with python-dotenv
- Comprehensive testing setup with pytest
- Code quality enforcement with ruff

## Requirements

- Python 3.11 or higher
- Dependencies listed in `requirements.txt`

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd GamesParser
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
# On Windows
venv\Scripts\activate
# On Unix or MacOS
source venv/bin/activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables:
   - Copy `env.example` to `.env`
   - Fill in the required environment variables

## Usage

1. Start the bot:
```bash
# On Windows
run.bat
# On Unix or MacOS
python src/main.py
```

## Project Structure

```
GamesParser/
├── src/                    # Source code
├── tests/                  # Test files
├── html_articles/          # Scraped articles
├── .env                    # Environment variables
├── env.example            # Example environment variables
├── requirements.txt       # Project dependencies
├── setup.py              # Package configuration
└── run.bat               # Windows startup script
```

## Development

- Run tests:
```bash
pytest
```

- Check code quality:
```bash
ruff check .
```

## License

[Add your license information here]

## Contributing

[Add contribution guidelines here] 