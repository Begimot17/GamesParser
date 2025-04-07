from datetime import datetime

from sqlalchemy import Column, DateTime, String
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from src.config.config import Config

Base = declarative_base()


class ProcessedPost(Base):
    __tablename__ = "processed_posts"

    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    link = Column(String, nullable=False)
    processed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<ProcessedPost(id='{self.id}', title='{self.title}')>"


class Database:
    def __init__(self):
        # Используем aiosqlite вместо обычного sqlite
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{Config.DB_PATH}", echo=False
        )
        self.async_session = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def _create_tables(self) -> None:
        """Create database tables if they don't exist"""
        try:
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        except SQLAlchemyError as e:
            raise RuntimeError(f"Failed to create database tables: {e}")

    async def initialize(self) -> None:
        """Initialize the database"""
        await self._create_tables()

    def get_session(self) -> AsyncSession:
        """Get a new database session"""
        return self.async_session()

    async def close(self) -> None:
        """Close the database connection"""
        await self.engine.dispose()


# Global database instance
db = Database() 