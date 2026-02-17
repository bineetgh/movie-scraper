"""MongoDB connection management using Motor (async driver)."""

import os
import logging
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, TEXT
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

logger = logging.getLogger(__name__)

_client: Optional[AsyncIOMotorClient] = None
_database: Optional[AsyncIOMotorDatabase] = None


async def get_database() -> Optional[AsyncIOMotorDatabase]:
    """Get the MongoDB database instance, initializing connection if needed."""
    global _client, _database

    if _database is not None:
        return _database

    mongodb_uri = os.getenv("MONGODB_URI")
    if not mongodb_uri:
        logger.warning("MONGODB_URI not set, MongoDB features disabled")
        return None

    try:
        _client = AsyncIOMotorClient(
            mongodb_uri,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            maxPoolSize=10,
            minPoolSize=2,
            maxIdleTimeMS=30000,
            retryWrites=True,
        )
        # Verify connection
        await _client.admin.command("ping")
        _database = _client.watchlazy
        logger.info("Connected to MongoDB Atlas")
        return _database
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        _client = None
        _database = None
        return None


async def close_connection():
    """Close the MongoDB connection."""
    global _client, _database
    if _client is not None:
        _client.close()
        _client = None
        _database = None
        logger.info("MongoDB connection closed")


async def init_indexes(db: AsyncIOMotorDatabase):
    """Create indexes for optimal query performance."""
    movies = db.movies

    # Single field indexes
    await movies.create_index("slug", unique=True)
    await movies.create_index([("rating", DESCENDING)])
    await movies.create_index([("year", DESCENDING)])
    await movies.create_index([("popularity", DESCENDING)])
    await movies.create_index("genres")
    await movies.create_index("streaming_providers")
    await movies.create_index("availability_types")
    await movies.create_index("original_language")

    # Compound indexes for common queries
    await movies.create_index([("rating", DESCENDING), ("year", DESCENDING)])
    await movies.create_index([("genres", ASCENDING), ("rating", DESCENDING)])
    await movies.create_index([("original_language", ASCENDING), ("rating", DESCENDING)])

    # Text search index
    await movies.create_index(
        [
            ("title", TEXT),
            ("synopsis", TEXT),
            ("director", TEXT),
            ("cast", TEXT),
        ],
        weights={
            "title": 10,
            "director": 5,
            "cast": 3,
            "synopsis": 1,
        },
        name="text_search_index",
    )

    # TV Shows indexes
    tvshows = db.tvshows

    await tvshows.create_index("slug", unique=True)
    await tvshows.create_index([("rating", DESCENDING)])
    await tvshows.create_index([("year", DESCENDING)])
    await tvshows.create_index([("popularity", DESCENDING)])
    await tvshows.create_index("genres")
    await tvshows.create_index("streaming_providers")
    await tvshows.create_index("availability_types")
    await tvshows.create_index("status")

    # Compound indexes
    await tvshows.create_index([("rating", DESCENDING), ("year", DESCENDING)])
    await tvshows.create_index([("genres", ASCENDING), ("rating", DESCENDING)])

    # Text search index for TV shows
    await tvshows.create_index(
        [
            ("title", TEXT),
            ("synopsis", TEXT),
            ("creator", TEXT),
            ("cast", TEXT),
        ],
        weights={
            "title": 10,
            "creator": 5,
            "cast": 3,
            "synopsis": 1,
        },
        name="tvshow_text_search_index",
    )

    logger.info("MongoDB indexes created")


async def check_connection() -> bool:
    """Check if MongoDB connection is healthy."""
    global _client
    if _client is None:
        return False
    try:
        await _client.admin.command("ping")
        return True
    except Exception:
        return False
