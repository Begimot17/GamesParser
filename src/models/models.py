"""Data models for GamesParser project."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator


class PostMetadata(BaseModel):
    """Мета-данные поста."""

    rating: str = "0"
    store_links: dict = {}
    images: list = []
    date: Optional[datetime] = None

    @field_validator("rating")
    @classmethod
    def clean_rating(cls, v: str) -> str:
        """Очистка рейтинга."""
        return v.strip() if v else "0"

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
    link: str
    content: str
    date: Optional[datetime] = None
    metadata: PostMetadata
    created_at: Optional[datetime] = None

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

    @field_validator("link")
    @classmethod
    def clean_link(cls, v: str) -> str:
        """Очистка ссылки."""
        if not v.strip():
            raise ValueError("Link cannot be empty")
        return v.strip()

    @field_validator("content")
    @classmethod
    def clean_content(cls, v: str) -> str:
        """Очистка контента."""
        return v.strip() if v else ""


class ProcessedPost(BaseModel):
    """Модель обработанного поста."""

    id: str
    title: str
    link: str
    processed_at: datetime

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
