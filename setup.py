from setuptools import setup, find_packages

setup(
    name="games_parser",
    version="0.1",
    packages=find_packages(),
    install_requires=[
        "aiohttp",
        "beautifulsoup4",
        "python-telegram-bot",
        "pydantic",
        "python-dotenv",
        "aiosqlite",
        "aiofiles",
        "pytest",
    ],
) 