"""Singleton metaclass for GamesParser project."""


class Singleton(type):
    """Metaclass for creating singleton classes."""

    _instances: dict = {}

    def __call__(cls, *args, **kwargs):
        """Return the singleton instance of the class."""
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]
