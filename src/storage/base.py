from abc import ABC, abstractmethod


class Storage(ABC):
    """Abstract base class for storage implementations."""

    @abstractmethod
    def mark_as_processed(self, post_id: str) -> None:
        """Marks a post as processed."""
        pass

    @abstractmethod
    def is_processed(self, post_id: str) -> bool:
        """Checks if a post has been processed."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Closes the storage connection."""
        pass
