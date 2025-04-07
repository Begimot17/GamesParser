from setuptools import setup, find_namespace_packages

setup(
    name="games_parser",
    version="0.1",
    package_dir={"": "src"},
    packages=find_namespace_packages(where="src", include=["*"]),
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