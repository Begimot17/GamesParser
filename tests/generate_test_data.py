import json
import os
from pathlib import Path
from typing import Dict, List

from src.parser.parser import Parser
from bs4 import BeautifulSoup
from src.models.models import Post

def generate_test_data() -> None:
    """Generate test data from HTML articles."""
    parser = Parser()
    test_data: Dict[str, Dict] = {}
    
    # Get all HTML files from the html_articles directory
    html_dir = Path("html_articles")
    if not html_dir.exists():
        print("html_articles directory not found")
        return
        
    for html_file in html_dir.glob("*.html"):
        try:
            # Read HTML content
            with open(html_file, "r", encoding="utf-8") as f:
                html_content = f.read()
                
            # Parse the article
            soup = BeautifulSoup(html_content, "html.parser")
            article = soup.find("article")
            if not article:
                print(f"No article found in {html_file}")
                continue
                
            # Parse the post
            post = parser._parse_article(article)
            if not post:
                print(f"Failed to parse article in {html_file}")
                continue
                
            # Convert post to dict
            post_dict = {
                "id": post.id,
                "title": post.title,
                "link": post.link,
                "text": post.text,
                "rating": post.rating,
                "images": post.images,
                "stores": post.stores,
                "metadata": {
                    "author": post.metadata.author,
                    "date": post.metadata.date,
                    "tags": post.metadata.tags
                }
            }
            
            # Add to test data
            test_data[html_file.stem] = post_dict
            print(f"Processed {html_file.stem}: {len(post.images)} images found")
            for img in post.images:
                print(f"  - {img}")
            
        except Exception as e:
            print(f"Error processing {html_file}: {str(e)}")
            
    # Save test data in the tests directory
    output_file = Path("tests") / "expected.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(test_data, f, ensure_ascii=False, indent=2)
        
    print(f"Generated test data for {len(test_data)} articles")

if __name__ == "__main__":
    generate_test_data() 