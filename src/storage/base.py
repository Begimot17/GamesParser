from abc import ABC, abstractmethod


class Storage(ABC):
    """Abstract base class for storage implementations."""

    @abstractmethod
    async def mark_as_processed(self, post_id: str) -> None:
        """Marks a post as processed."""

    @abstractmethod
    async def is_processed(self, post_id: str) -> bool:
        """Checks if a post has been processed."""

    @abstractmethod
    async def close(self) -> None:
        """Closes the storage connection."""
