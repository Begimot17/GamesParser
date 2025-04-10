import os
import tempfile
from datetime import datetime, timedelta

import pytest

from src.models.models import Post, StoreLinks
from src.storage.storage import PostStorage


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        return tmp.name


@pytest.fixture
def storage(temp_db):
    storage = PostStorage(temp_db)
    yield storage
    os.unlink(temp_db)


@pytest.fixture
def sample_post():
    return Post(
        id=123,
        title="Test Post",
        link="https://example.com/test",
        published_at=datetime.now(),
        images=["https://example.com/image.jpg"],
        stores=StoreLinks(Steam="https://store.steampowered.com"),
    )


def test_save_and_load_post(storage, sample_post):
    # Save post
    storage.save_post(sample_post)

    # Load post
    loaded_post = storage.get_post(sample_post.id)

    assert loaded_post is not None
    assert loaded_post.id == sample_post.id
    assert loaded_post.title == sample_post.title
    assert loaded_post.link == sample_post.link
    assert loaded_post.images == sample_post.images
    assert loaded_post.stores.model_dump() == sample_post.stores.model_dump()


def test_mark_as_processed(storage, sample_post):
    storage.save_post(sample_post)
    storage.mark_as_processed(sample_post.id)

    assert storage.is_processed(sample_post.id)


def test_cleanup_old_posts(storage, sample_post):
    # Save post and mark as processed
    storage.save_post(sample_post)
    storage.mark_as_processed(sample_post.id)

    # Create an old processed post
    old_post = Post(
        id=456,
        title="Old Post",
        link="https://example.com/old",
        published_at=datetime.now() - timedelta(days=2),
        images=[],
        stores=None,
    )
    storage.save_post(old_post)
    storage.mark_as_processed(old_post.id)

    # Cleanup posts older than 1 day
    storage.cleanup_old_posts(hours=24)

    assert storage.is_processed(sample_post.id)
    assert not storage.is_processed(old_post.id)


def test_get_all_posts(storage, sample_post):
    storage.save_post(sample_post)
    posts = storage.get_all_posts()

    assert len(posts) == 1
    assert posts[0].id == sample_post.id


def test_save_data_persistence(storage, sample_post, temp_db):
    # Save post in first storage instance
    storage.save_post(sample_post)

    # Create new storage instance with same DB file
    new_storage = PostStorage(temp_db)

    # Load post from new storage
    loaded_post = new_storage.get_post(sample_post.id)

    assert loaded_post is not None
    assert loaded_post.id == sample_post.id


def test_invalid_db_file():
    with pytest.raises(Exception):
        PostStorage("/invalid/path/to/db.json")


def test_corrupted_db_file(temp_db):
    # Write invalid JSON to the file
    with open(temp_db, "w") as f:
        f.write('{"invalid": json}')

    # Try to create storage with corrupted file
    storage = PostStorage(temp_db)

    # Storage should initialize with empty data
    assert len(storage.get_all_posts()) == 0
