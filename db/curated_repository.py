"""Repository for curated lists operations."""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime

from motor.motor_asyncio import AsyncIOMotorDatabase

from models.curated_list import CuratedList
from models.movie import Movie

logger = logging.getLogger(__name__)


class CuratedListRepository:
    """Repository for curated list database operations."""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.lists = db.curated_lists
        self.movies = db.movies

    async def get_all(self, active_only: bool = True) -> List[CuratedList]:
        """Get all curated lists."""
        query = {"is_active": True} if active_only else {}
        cursor = self.lists.find(query).sort("display_order", 1)
        docs = await cursor.to_list(length=100)
        return [CuratedList.from_document(doc) for doc in docs]

    async def get_by_slug(self, slug: str) -> Optional[CuratedList]:
        """Get a curated list by slug."""
        doc = await self.lists.find_one({"_id": slug})
        return CuratedList.from_document(doc) if doc else None

    async def create(self, curated_list: CuratedList) -> bool:
        """Create a new curated list."""
        try:
            await self.lists.insert_one(curated_list.to_document())
            return True
        except Exception as e:
            logger.error(f"Failed to create curated list: {e}")
            return False

    async def update(self, curated_list: CuratedList) -> bool:
        """Update an existing curated list."""
        try:
            result = await self.lists.replace_one(
                {"_id": curated_list.slug},
                curated_list.to_document()
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Failed to update curated list: {e}")
            return False

    async def delete(self, slug: str) -> bool:
        """Delete a curated list."""
        try:
            result = await self.lists.delete_one({"_id": slug})
            return result.deleted_count > 0
        except Exception as e:
            logger.error(f"Failed to delete curated list: {e}")
            return False

    async def add_movie(self, list_slug: str, movie_slug: str) -> bool:
        """Add a movie to a curated list."""
        try:
            result = await self.lists.update_one(
                {"_id": list_slug},
                {
                    "$addToSet": {"movie_slugs": movie_slug},
                    "$set": {"updated_at": datetime.utcnow()}
                }
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Failed to add movie to list: {e}")
            return False

    async def remove_movie(self, list_slug: str, movie_slug: str) -> bool:
        """Remove a movie from a curated list."""
        try:
            result = await self.lists.update_one(
                {"_id": list_slug},
                {
                    "$pull": {"movie_slugs": movie_slug},
                    "$set": {"updated_at": datetime.utcnow()}
                }
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Failed to remove movie from list: {e}")
            return False

    async def get_movies_for_list(self, list_slug: str, limit: int = 20) -> List[Movie]:
        """Get movies for a curated list."""
        curated_list = await self.get_by_slug(list_slug)
        if not curated_list or not curated_list.movie_slugs:
            return []

        # Preserve order from curated list
        cursor = self.movies.find({"_id": {"$in": curated_list.movie_slugs}})
        docs = await cursor.to_list(length=limit)

        # Create a map for quick lookup
        movie_map = {doc["_id"]: Movie.from_document(doc) for doc in docs}

        # Return in the order specified in the curated list
        return [movie_map[slug] for slug in curated_list.movie_slugs[:limit] if slug in movie_map]

    async def reorder_movies(self, list_slug: str, movie_slugs: List[str]) -> bool:
        """Reorder movies in a curated list."""
        try:
            result = await self.lists.update_one(
                {"_id": list_slug},
                {
                    "$set": {
                        "movie_slugs": movie_slugs,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Failed to reorder movies: {e}")
            return False
