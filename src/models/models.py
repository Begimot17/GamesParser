from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, field_validator, HttpUrl


class StoreLinks(BaseModel):
    steam: Optional[str] = None
    epic: Optional[str] = None
    gog: Optional[str] = None
    humble_bundle: Optional[str] = None
    itch_io: Optional[str] = None


class PostMetadata(BaseModel):
    author: Optional[str] = None
    date: Optional[str] = None
    tags: List[str] = []

    @field_validator("author")
    @classmethod
    def clean_author(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v else None

    @field_validator("date")
    @classmethod
    def clean_date(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v else None

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, v: List[str]) -> List[str]:
        """Очистка тегов от пустых значений."""
        return [tag for tag in v if tag.strip()]


class Post(BaseModel):
    id: str
    title: str
    link: str
    text: str
    images: List[str] = []
    rating: str
    stores: Dict[str, str] = {}
    created_at: datetime = datetime.now()
    metadata: PostMetadata

    @field_validator("title")
    @classmethod
    def clean_title(cls, v: str) -> str:
        """Очистка заголовка от лишних пробелов."""
        return v.strip() if v else ""

    @field_validator("text")
    @classmethod
    def clean_text(cls, v: str) -> str:
        return v.strip()

    @field_validator("rating")
    @classmethod
    def clean_rating(cls, v: str) -> str:
        return v.strip() if v else "N/A"

    @field_validator("stores")
    @classmethod
    def clean_stores(cls, v: Dict[str, str]) -> Dict[str, str]:
        return {k: v for k, v in v.items() if k and v}

    @field_validator("images")
    @classmethod
    def clean_images(cls, v: List[str]) -> List[str]:
        return list(set(v))  # Удаляем дубликаты


class ProcessedPost(BaseModel):
    id: str
    title: str
    link: str
    processed_at: datetime

    @field_validator("id")
    @classmethod
    def clean_id(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("ID cannot be empty")
        return v.strip()

    @field_validator("title")
    @classmethod
    def clean_title(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Title cannot be empty")
        return v.strip() 