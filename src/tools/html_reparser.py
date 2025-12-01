import asyncio
import os
from pathlib import Path
from typing import Type

from src.common.logger import logger
from src.config.config import Config
from src.parsers.pikabu_parser import PikabuParser
from src.parsers.vgtimes_parser import VGTimesParser
from src.parsers.stopgame_parser import StopGameParser
from src.parsers.utils.base_parser import BaseParser
from src.models.models import Post


class HtmlReparser:
    """
    A tool to re-parse saved HTML files using current parser configurations.
    Useful for debugging and updating selectors.
    """

    def __init__(self):
        self.html_dir = Path(Config.HTML_DIR)
        self.parsers = {
            "pikabu": PikabuParser,
            "vgtimes": VGTimesParser,
            "stopgame": StopGameParser,
        }
        if not self.html_dir.exists():
            logger.warning(f"HTML directory not found: {self.html_dir}. Please ensure SAVE_HTML is enabled and parsers have run.")

    async def reparse_file(self, parser_name: str, filename: str) -> Optional[Post]:
        """
        Reparses a single HTML file using the specified parser.

        Args:
            parser_name: The name of the parser to use (e.g., "pikabu").
            filename: The name of the HTML file to reparse.

        Returns:
            The parsed Post object if successful, None otherwise.
        """
        parser_class = self.parsers.get(parser_name)
        if not parser_class:
            logger.error(f"Unknown parser: {parser_name}")
            return None

        filepath = self.html_dir / filename
        if not filepath.is_file():
            logger.error(f"HTML file not found: {filepath}")
            return None

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                html_content = f.read()
        except IOError as e:
            logger.error(f"Error reading HTML file {filepath}: {e}")
            return None

        # Instantiate the parser and process the HTML
        async with parser_class() as parser:
            # Find the article tag within the HTML
            soup = BeautifulSoup(html_content, "html.parser")
            article_tag = soup.select_one(parser.SELECTORS["articles"])
            
            if not article_tag:
                logger.error(f"Could not find article tag using selector '{parser.SELECTORS['articles']}' in {filename}")
                return None
            
            # Temporarily disable storage processing check for re-parsing
            original_is_processed = parser.storage.is_processed
            parser.storage.is_processed = lambda x: False

            try:
                post = await parser._parse_article(article_tag, preloaded_html=html_content)
                if post:
                    logger.info(f"Successfully re-parsed {filename} with {parser_name}. Post ID: {post.id}")
                else:
                    logger.warning(f"Reparsing {filename} with {parser_name} yielded no post.")
                return post
            except Exception as e:
                logger.error(f"Error during re-parsing {filename} with {parser_name}: {e}", exc_info=True)
                return None
            finally:
                parser.storage.is_processed = original_is_processed # Restore original method

    async def list_saved_html_files(self) -> list[str]:
        """Lists all saved HTML files."""
        if not self.html_dir.exists():
            return []
        return [f.name for f in self.html_dir.iterdir() if f.is_file() and f.suffix == ".html"]

    async def run_reparser(self):
        """Interactive mode for re-parsing."""
        print("\n--- HTML Reparser Tool ---")
        files = await self.list_saved_html_files()
        if not files:
            print(f"No HTML files found in {self.html_dir}. Please ensure SAVE_HTML is enabled and parsers have run. Exiting.")
            return

        print("Available HTML files:")
        for i, file in enumerate(files):
            print(f"{i+1}. {file}")

        while True:
            try:
                file_choice = input("Enter the number of the file to re-parse (or 'q' to quit): ")
                if file_choice.lower() == 'q':
                    break
                file_index = int(file_choice) - 1
                if 0 <= file_index < len(files):
                    selected_file = files[file_index]
                    break
                else:
                    print("Invalid file number. Please try again.")
            except ValueError:
                print("Invalid input. Please enter a number or 'q'.")
        
        if file_choice.lower() == 'q':
            return

        print("\nAvailable Parsers:")
        for i, parser_name in enumerate(self.parsers.keys()):
            print(f"{i+1}. {parser_name}")
        
        while True:
            try:
                parser_choice = input("Enter the number of the parser to use (or 'q' to quit): ")
                if parser_choice.lower() == 'q':
                    return
                parser_index = int(parser_choice) - 1
                parser_names = list(self.parsers.keys())
                if 0 <= parser_index < len(parser_names):
                    selected_parser = parser_names[parser_index]
                    break
                else:
                    print("Invalid parser number. Please try again.")
            except ValueError:
                print("Invalid input. Please enter a number or 'q'.")

        print(f"\nReparsing '{selected_file}' using '{selected_parser}'...")
        parsed_post = await self.reparse_file(selected_parser, selected_file)

        if parsed_post:
            print("\n--- Reparsing Result ---")
            print(f"ID: {parsed_post.id}")
            print(f"Title: {parsed_post.title}")
            print(f"Link: {parsed_post.link}")
            print(f"Content (truncated): {parsed_post.content[:200]}...")
            print(f"Images: {parsed_post.metadata.images}")
            print(f"Store Links: {parsed_post.metadata.store_links}")
            print(f"Date: {parsed_post.metadata.date}")
        else:
            print("\nReparsing failed or yielded no post.")

if __name__ == "__main__":
    asyncio.run(HtmlReparser().run_reparser())
