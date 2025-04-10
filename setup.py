from setuptools import find_namespace_packages, setup

setup(
    name="games_parser",
    version="0.1",
    package_dir={"": "src"},
    packages=find_namespace_packages(where="src", include=["*"]),
    python_requires=">=3.11",
    install_requires=[
        "aiohttp>=3.9.0",
        "beautifulsoup4>=4.12.0",
        "python-telegram-bot>=20.7",
        "pydantic>=2.5.0",
        "python-dotenv>=1.0.0",
        "aiosqlite>=0.19.0",
        "aiofiles>=23.2.1",
        "pytest>=7.4.0",
        "ruff>=0.1.9",
    ],
)
