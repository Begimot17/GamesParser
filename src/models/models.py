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
    rating: str = "0"
    store_links: Dict[str, str] = {}
    images: List[str] = []
    date: Optional[datetime] = None

    @field_validator("rating")
    @classmethod
    def clean_rating(cls, v: str) -> str:
        return v.strip() if v else "0"

    @field_validator("store_links")
    @classmethod
    def clean_store_links(cls, v: Dict[str, str]) -> Dict[str, str]:
        return {k: v for k, v in v.items() if k and v}

    @field_validator("images")
    @classmethod
    def clean_images(cls, v: List[str]) -> List[str]:
        return list(set(v))  # Удаляем дубликаты


class Post(BaseModel):
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
        if not v.strip():
            raise ValueError("ID cannot be empty")
        return v.strip()

    @field_validator("title")
    @classmethod
    def clean_title(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Title cannot be empty")
        return v.strip()

    @field_validator("link")
    @classmethod
    def clean_link(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Link cannot be empty")
        return v.strip()

    @field_validator("content")
    @classmethod
    def clean_content(cls, v: str) -> str:
        return v.strip() if v else ""


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