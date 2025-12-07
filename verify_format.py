
import logging
import asyncio
from datetime import datetime
from src.bot.message_formatter import MessageFormatter
from src.models.models import Post, PostMetadata

# Configure logging to stdout
logging.basicConfig(level=logging.INFO)

def verify_format():
    formatter = MessageFormatter()
    
    # Create a sample post with all new fields
    metadata = PostMetadata(
        rating=95,
        store_links={"steam": "https://store.steampowered.com/app/123", "epicgames": "https://epicgames.com/p/game"},
        images=["http://example.com/img.jpg"],
        date=datetime.now(),
        tags=["Free", "Steam", "Indie Game"],
        views="1.5k"
    )
    
    post = Post(
        id="123",
        title="Super Cool Game is Free!",
        link="https://example.com/game",
        content="This is a great game. You should grab it while it's free. It has amazing graphics and gameplay. " * 10, # Long content
        metadata=metadata
    )
    
    print("\n--- Formatted Message Preview ---")
    formatted_msg = formatter.format_message(post)
    print(formatted_msg)
    print("---------------------------------\n")

    # Check for HTML tags
    if "<b>" in formatted_msg and "href" in formatted_msg:
        print("SUCCESS: HTML tags present.")
    else:
        print("FAILURE: HTML tags missing.")

    # Check for new fields
    if "👁 1.5k" in formatted_msg:
        print("SUCCESS: Views present.")
    else:
        print("FAILURE: Views missing.")
        
    if "#Free #Steam #IndieGame" in formatted_msg:
        print("SUCCESS: Tags present and formatted.")
    else:
        print("FAILURE: Tags missing or malformed.")

if __name__ == "__main__":
    verify_format()
