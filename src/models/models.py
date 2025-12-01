"""Data models for GamesParser project."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, HttpUrl, field_validator


class PostMetadata(BaseModel):
    """Мета-данные поста."""

    rating: Optional[int] = None
    store_links: dict = {}
    images: list = []
    date: Optional[datetime] = None

    @field_validator("rating", mode="before")
    @classmethod
    def clean_rating(cls, v: str) -> Optional[int]:
        """Очистка и преобразование рейтинга в число."""
        if isinstance(v, int):
            return v
        if isinstance(v, str):
            v = v.strip().replace("-", "")
            if v.isdigit():
                return int(v)
        return None

    @field_validator("store_links")
    @classmethod
    def clean_store_links(cls, v: dict) -> dict:
        """Очистка ссылок на магазины."""
        return {k: v for k, v in v.items() if k and v}

    @field_validator("images")
    @classmethod
    def clean_images(cls, v: list) -> list:
        """Очистка списка изображений."""
        return list(set(v))  # Удаляем дубликаты


class Post(BaseModel):
    """Модель поста."""

    id: str
    title: str
    link: HttpUrl
    content: str
    metadata: PostMetadata

    @field_validator("id")
    @classmethod
    def clean_id(cls, v: str) -> str:
        """Очистка id."""
        if not v.strip():
            raise ValueError("ID cannot be empty")
        return v.strip()

    @field_validator("title")
    @classmethod
    def clean_title(cls, v: str) -> str:
        """Очистка заголовка."""
        if not v.strip():
            raise ValueError("Title cannot be empty")
        return v.strip()

    @field_validator("content")
    @classmethod
    def clean_content(cls, v: str) -> str:
        """Очистка контента."""
        return v.strip() if v else ""
