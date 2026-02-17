"""TV Show repository for MongoDB operations."""

import logging
from typing import List, Optional, Dict, Any, Tuple

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import DESCENDING, UpdateOne

from models.tvshow import TVShow

logger = logging.getLogger(__name__)


class TVShowRepository:
    """Repository for TV show database operations."""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.shows = db.tvshows

    async def get_by_slug(self, slug: str) -> Optional[TVShow]:
        """Get a TV show by its slug."""
        doc = await self.shows.find_one({"_id": slug})
        return TVShow.from_document(doc) if doc else None

    async def get_all(
        self,
        genre: Optional[str] = None,
        service: Optional[str] = None,
        availability: Optional[str] = None,
        min_rating: Optional[float] = None,
        status: Optional[str] = None,
        letter: Optional[str] = None,
        sort_by: str = "rating",
        skip: int = 0,
        limit: int = 24,
    ) -> List[TVShow]:
        """Get TV shows with optional filters and pagination."""
        query: Dict[str, Any] = {}

        if genre:
            query["genres"] = genre
        if service:
            query["streaming_providers"] = service
        if availability:
            query["availability_types"] = availability
        if min_rating:
            query["rating"] = {"$gte": min_rating}
        if status:
            query["status"] = status
        if letter:
            if letter == "0-9":
                query["title"] = {"$regex": "^[0-9]"}
            else:
                query["title"] = {"$regex": f"^{letter}", "$options": "i"}

        # Sort options
        sort_field = {
            "rating": [("rating", DESCENDING), ("vote_count", DESCENDING)],
            "year": [("year", DESCENDING)],
            "popularity": [("popularity", DESCENDING)],
            "title": [("title", 1)],
        }.get(sort_by, [("rating", DESCENDING)])

        cursor = self.shows.find(query).sort(sort_field).skip(skip).limit(limit)
        docs = await cursor.to_list(length=limit)
        return [TVShow.from_document(doc) for doc in docs]

    async def count(
        self,
        genre: Optional[str] = None,
        service: Optional[str] = None,
        availability: Optional[str] = None,
        min_rating: Optional[float] = None,
        status: Optional[str] = None,
        letter: Optional[str] = None,
    ) -> int:
        """Count TV shows matching filters."""
        query: Dict[str, Any] = {}

        if genre:
            query["genres"] = genre
        if service:
            query["streaming_providers"] = service
        if availability:
            query["availability_types"] = availability
        if min_rating:
            query["rating"] = {"$gte": min_rating}
        if status:
            query["status"] = status
        if letter:
            if letter == "0-9":
                query["title"] = {"$regex": "^[0-9]"}
            else:
                query["title"] = {"$regex": f"^{letter}", "$options": "i"}

        return await self.shows.count_documents(query)

    async def search(self, query: str, limit: int = 20) -> List[TVShow]:
        """Full-text search for TV shows."""
        if not query or len(query) < 2:
            return []

        cursor = self.shows.find(
            {"$text": {"$search": query}},
            {"score": {"$meta": "textScore"}},
        ).sort([("score", {"$meta": "textScore"})]).limit(limit)

        docs = await cursor.to_list(length=limit)
        return [TVShow.from_document(doc) for doc in docs]

    async def get_top_rated(self, limit: int = 24) -> List[TVShow]:
        """Get top-rated TV shows."""
        cursor = self.shows.find(
            {"rating": {"$exists": True, "$ne": None}}
        ).sort([("rating", DESCENDING), ("vote_count", DESCENDING)]).limit(limit)

        docs = await cursor.to_list(length=limit)
        return [TVShow.from_document(doc) for doc in docs]

    async def get_random(self, limit: int = 10) -> List[TVShow]:
        """Get random TV shows using aggregation."""
        pipeline = [{"$sample": {"size": limit}}]
        cursor = self.shows.aggregate(pipeline)
        docs = await cursor.to_list(length=limit)
        return [TVShow.from_document(doc) for doc in docs]

    async def get_related(
        self, show: TVShow, limit: int = 6, exclude_slug: Optional[str] = None
    ) -> List[TVShow]:
        """Get related TV shows based on genres."""
        if not show.genres:
            return await self.get_random(limit)

        query: Dict[str, Any] = {
            "genres": {"$in": show.genres},
        }
        if exclude_slug:
            query["_id"] = {"$ne": exclude_slug}

        cursor = self.shows.find(query).sort([
            ("rating", DESCENDING)
        ]).limit(limit)

        docs = await cursor.to_list(length=limit)
        return [TVShow.from_document(doc) for doc in docs]

    async def get_service_counts(self) -> Dict[str, int]:
        """Get count of shows per streaming service."""
        pipeline = [
            {"$unwind": "$streaming_providers"},
            {"$group": {"_id": "$streaming_providers", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]
        cursor = self.shows.aggregate(pipeline)
        results = await cursor.to_list(length=100)
        return {doc["_id"]: doc["count"] for doc in results}

    async def get_genre_counts(self) -> Dict[str, int]:
        """Get count of shows per genre."""
        pipeline = [
            {"$unwind": "$genres"},
            {"$group": {"_id": "$genres", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]
        cursor = self.shows.aggregate(pipeline)
        results = await cursor.to_list(length=100)
        return {doc["_id"]: doc["count"] for doc in results}

    async def get_all_genres(self) -> List[str]:
        """Get list of all unique genres."""
        genres = await self.shows.distinct("genres")
        return sorted([g for g in genres if g])

    async def get_all_services(self) -> List[str]:
        """Get list of all unique streaming services."""
        services = await self.shows.distinct("streaming_providers")
        return sorted([s for s in services if s])

    async def upsert_shows(self, shows: List[TVShow]) -> int:
        """Bulk upsert TV shows. Returns number of modified documents."""
        if not shows:
            return 0

        operations = [
            UpdateOne(
                {"_id": show.slug},
                {"$set": show.to_document()},
                upsert=True,
            )
            for show in shows
        ]

        result = await self.shows.bulk_write(operations)
        logger.info(
            f"Upserted {result.upserted_count} new, modified {result.modified_count} TV shows"
        )
        return result.upserted_count + result.modified_count

    async def get_total_count(self) -> int:
        """Get total number of TV shows in database."""
        return await self.shows.count_documents({})
