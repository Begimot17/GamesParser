"""
Helper module for generating descriptions.
"""


def generate_description(text: str, max_length: int = 200) -> str:
    """
    Generate a shortened description from the given text.

    Args:
        text (str): The input text to generate description from
        max_length (int): Maximum length of the description

    Returns:
        str: The generated description
    """
    if not text:
        return ""

    # Remove extra whitespace
    text = " ".join(text.split())

    if len(text) <= max_length:
        return text

    # Try to cut at the last sentence
    last_sentence = text[:max_length].rfind(".")
    if last_sentence > 0:
        return text[: last_sentence + 1]

    # If no sentence found, cut at the last word
    last_word = text[:max_length].rfind(" ")
    if last_word > 0:
        return text[:last_word] + "..."

    return text[:max_length] + "..."
