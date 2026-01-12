"""Movie repository for MongoDB operations."""

import logging
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import DESCENDING, UpdateOne

from models.movie import Movie

logger = logging.getLogger(__name__)


class MovieRepository:
    """Repository for movie database operations."""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.movies = db.movies
        self.metadata = db.metadata

    async def get_by_slug(self, slug: str) -> Optional[Movie]:
        """Get a movie by its slug."""
        doc = await self.movies.find_one({"_id": slug})
        return Movie.from_document(doc) if doc else None

    async def get_all(
        self,
        genre: Optional[str] = None,
        service: Optional[str] = None,
        availability: Optional[str] = None,
        min_rating: Optional[float] = None,
        letter: Optional[str] = None,
        sort_by: str = "rating",
        skip: int = 0,
        limit: int = 24,
    ) -> List[Movie]:
        """Get movies with optional filters and pagination."""
        query: Dict[str, Any] = {}

        if genre:
            query["genres"] = genre
        if service:
            query["streaming_providers"] = service
        if availability:
            query["availability_types"] = availability
        if min_rating:
            query["rating"] = {"$gte": min_rating}
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

        cursor = self.movies.find(query).sort(sort_field).skip(skip).limit(limit)
        docs = await cursor.to_list(length=limit)
        return [Movie.from_document(doc) for doc in docs]

    async def count(
        self,
        genre: Optional[str] = None,
        service: Optional[str] = None,
        availability: Optional[str] = None,
        min_rating: Optional[float] = None,
        letter: Optional[str] = None,
    ) -> int:
        """Count movies matching filters."""
        query: Dict[str, Any] = {}

        if genre:
            query["genres"] = genre
        if service:
            query["streaming_providers"] = service
        if availability:
            query["availability_types"] = availability
        if min_rating:
            query["rating"] = {"$gte": min_rating}
        if letter:
            if letter == "0-9":
                query["title"] = {"$regex": "^[0-9]"}
            else:
                query["title"] = {"$regex": f"^{letter}", "$options": "i"}

        return await self.movies.count_documents(query)

    async def search(self, query: str, limit: int = 20) -> List[Movie]:
        """Full-text search for movies."""
        if not query or len(query) < 2:
            return []

        cursor = self.movies.find(
            {"$text": {"$search": query}},
            {"score": {"$meta": "textScore"}},
        ).sort([("score", {"$meta": "textScore"})]).limit(limit)

        docs = await cursor.to_list(length=limit)
        return [Movie.from_document(doc) for doc in docs]

    async def get_top_rated(self, limit: int = 24) -> List[Movie]:
        """Get top-rated movies."""
        cursor = self.movies.find(
            {"rating": {"$exists": True, "$ne": None}}
        ).sort([("rating", DESCENDING), ("vote_count", DESCENDING)]).limit(limit)

        docs = await cursor.to_list(length=limit)
        return [Movie.from_document(doc) for doc in docs]

    async def get_random(self, limit: int = 10) -> List[Movie]:
        """Get random movies using aggregation."""
        pipeline = [{"$sample": {"size": limit}}]
        cursor = self.movies.aggregate(pipeline)
        docs = await cursor.to_list(length=limit)
        return [Movie.from_document(doc) for doc in docs]

    async def get_related(
        self, movie: Movie, limit: int = 6, exclude_slug: Optional[str] = None
    ) -> List[Movie]:
        """Get related movies based on genres."""
        if not movie.genres:
            return await self.get_random(limit)

        query: Dict[str, Any] = {
            "genres": {"$in": movie.genres},
        }
        if exclude_slug:
            query["_id"] = {"$ne": exclude_slug}

        cursor = self.movies.find(query).sort([
            ("rating", DESCENDING)
        ]).limit(limit)

        docs = await cursor.to_list(length=limit)
        return [Movie.from_document(doc) for doc in docs]

    async def get_movie_with_related(
        self, slug: str, related_limit: int = 6
    ) -> Tuple[Optional[Movie], List[Movie]]:
        """Get a movie and its related movies in optimized queries."""
        movie = await self.get_by_slug(slug)
        if not movie:
            return None, []

        if not movie.genres:
            related = await self.get_random(related_limit)
        else:
            # Get related movies by genre, excluding current movie
            cursor = self.movies.find({
                "genres": {"$in": movie.genres},
                "_id": {"$ne": slug},
            }).sort([("rating", DESCENDING)]).limit(related_limit)
            docs = await cursor.to_list(length=related_limit)
            related = [Movie.from_document(doc) for doc in docs]

        return movie, related

    async def get_service_counts(self) -> Dict[str, int]:
        """Get count of movies per streaming service."""
        pipeline = [
            {"$unwind": "$streaming_providers"},
            {"$group": {"_id": "$streaming_providers", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]
        cursor = self.movies.aggregate(pipeline)
        results = await cursor.to_list(length=100)
        return {doc["_id"]: doc["count"] for doc in results}

    async def get_genre_counts(self) -> Dict[str, int]:
        """Get count of movies per genre."""
        pipeline = [
            {"$unwind": "$genres"},
            {"$group": {"_id": "$genres", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]
        cursor = self.movies.aggregate(pipeline)
        results = await cursor.to_list(length=100)
        return {doc["_id"]: doc["count"] for doc in results}

    async def get_all_genres(self) -> List[str]:
        """Get list of all unique genres."""
        genres = await self.movies.distinct("genres")
        return sorted([g for g in genres if g])

    async def get_all_services(self) -> List[str]:
        """Get list of all unique streaming services."""
        services = await self.movies.distinct("streaming_providers")
        return sorted([s for s in services if s])

    async def upsert_movies(self, movies: List[Movie]) -> int:
        """Bulk upsert movies. Returns number of modified documents."""
        if not movies:
            return 0

        operations = [
            UpdateOne(
                {"_id": movie.slug},
                {"$set": movie.to_document()},
                upsert=True,
            )
            for movie in movies
        ]

        result = await self.movies.bulk_write(operations)
        logger.info(
            f"Upserted {result.upserted_count} new, modified {result.modified_count} movies"
        )
        return result.upserted_count + result.modified_count

    async def get_last_refresh(self) -> Optional[datetime]:
        """Get timestamp of last cache refresh."""
        doc = await self.metadata.find_one({"_id": "refresh_info"})
        return doc.get("last_refresh") if doc else None

    async def set_last_refresh(self, timestamp: Optional[datetime] = None):
        """Set timestamp of last cache refresh."""
        await self.metadata.update_one(
            {"_id": "refresh_info"},
            {"$set": {"last_refresh": timestamp or datetime.utcnow()}},
            upsert=True,
        )

    async def is_cache_stale(self, ttl_seconds: int = 21600) -> bool:
        """Check if cache is stale based on TTL."""
        last_refresh = await self.get_last_refresh()
        if not last_refresh:
            return True

        elapsed = (datetime.utcnow() - last_refresh).total_seconds()
        return elapsed > ttl_seconds

    async def get_total_count(self) -> int:
        """Get total number of movies in database."""
        return await self.movies.count_documents({})
