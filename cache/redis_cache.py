"""Redis caching layer with same interface as memory cache."""

import json
import logging
from typing import List, Optional, Tuple

from models.movie import Movie

logger = logging.getLogger(__name__)

# TTL values in seconds
MOVIE_RELATED_TTL = 600  # 10 min
TOP_RATED_TTL = 600  # 10 min
BROWSE_TTL = 300  # 5 min
SEARCH_TTL = 300  # 5 min


class RedisCacheManager:
    """Redis-backed cache with same interface as MovieCacheManager."""

    def __init__(self):
        self._redis = None
        self._connected = False

    async def connect(self, redis_url: str) -> bool:
        """Connect to Redis. Returns True if successful."""
        try:
            import redis.asyncio as redis_async

            self._redis = redis_async.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            # Test connection
            await self._redis.ping()
            self._connected = True
            logger.info("Connected to Redis cache")
            return True
        except ImportError:
            logger.warning("redis package not installed")
            return False
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}")
            self._connected = False
            return False

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis is not None:
            await self._redis.close()
            self._connected = False

    def is_connected(self) -> bool:
        """Check if Redis is connected."""
        return self._connected

    # --- Serialization helpers ---
    @staticmethod
    def _serialize_movie(movie: Movie) -> str:
        """Serialize Movie to JSON string."""
        return movie.to_json()

    @staticmethod
    def _deserialize_movie(data: str) -> Optional[Movie]:
        """Deserialize JSON string to Movie."""
        if not data:
            return None
        try:
            return Movie.from_json(data)
        except Exception:
            return None

    @staticmethod
    def _serialize_movies(movies: List[Movie]) -> str:
        """Serialize list of Movies to JSON string."""
        return json.dumps([json.loads(m.to_json()) for m in movies])

    @staticmethod
    def _deserialize_movies(data: str) -> List[Movie]:
        """Deserialize JSON string to list of Movies."""
        if not data:
            return []
        try:
            movies_data = json.loads(data)
            return [Movie.from_json(json.dumps(m)) for m in movies_data]
        except Exception:
            return []

    # --- Movie with Related ---
    async def get_movie_with_related(
        self, slug: str
    ) -> Optional[Tuple[Movie, List[Movie]]]:
        """Get cached movie and related movies."""
        if not self._connected:
            return None
        try:
            key = f"movie_related:{slug}"
            data = await self._redis.get(key)
            if not data:
                return None
            parsed = json.loads(data)
            movie = Movie.from_json(json.dumps(parsed["movie"]))
            related = [Movie.from_json(json.dumps(m)) for m in parsed["related"]]
            return (movie, related)
        except Exception as e:
            logger.debug(f"Redis get_movie_with_related error: {e}")
            return None

    async def set_movie_with_related(
        self, slug: str, movie: Movie, related: List[Movie]
    ) -> None:
        """Cache movie and related movies."""
        if not self._connected:
            return
        try:
            key = f"movie_related:{slug}"
            data = json.dumps({
                "movie": json.loads(movie.to_json()),
                "related": [json.loads(m.to_json()) for m in related],
            })
            await self._redis.setex(key, MOVIE_RELATED_TTL, data)
        except Exception as e:
            logger.debug(f"Redis set_movie_with_related error: {e}")

    # --- Top Rated ---
    async def get_top_rated(self, limit: int) -> Optional[List[Movie]]:
        """Get cached top rated movies."""
        if not self._connected:
            return None
        try:
            key = f"top_rated:{limit}"
            data = await self._redis.get(key)
            if not data:
                return None
            return self._deserialize_movies(data)
        except Exception as e:
            logger.debug(f"Redis get_top_rated error: {e}")
            return None

    async def set_top_rated(self, limit: int, movies: List[Movie]) -> None:
        """Cache top rated movies."""
        if not self._connected:
            return
        try:
            key = f"top_rated:{limit}"
            await self._redis.setex(key, TOP_RATED_TTL, self._serialize_movies(movies))
        except Exception as e:
            logger.debug(f"Redis set_top_rated error: {e}")

    # --- Browse Results ---
    @staticmethod
    def _browse_key(
        genre: Optional[str],
        service: Optional[str],
        availability: Optional[str],
        min_rating: Optional[float],
        page: int,
    ) -> str:
        """Generate cache key for browse query."""
        return f"browse:{genre or ''}:{service or ''}:{availability or ''}:{min_rating or 0}:{page}"

    async def get_browse(
        self,
        genre: Optional[str],
        service: Optional[str],
        availability: Optional[str],
        min_rating: Optional[float],
        page: int,
    ) -> Optional[Tuple[List[Movie], int]]:
        """Get cached browse results (movies, total_count)."""
        if not self._connected:
            return None
        try:
            key = self._browse_key(genre, service, availability, min_rating, page)
            data = await self._redis.get(key)
            if not data:
                return None
            parsed = json.loads(data)
            movies = [Movie.from_json(json.dumps(m)) for m in parsed["movies"]]
            return (movies, parsed["total"])
        except Exception as e:
            logger.debug(f"Redis get_browse error: {e}")
            return None

    async def set_browse(
        self,
        genre: Optional[str],
        service: Optional[str],
        availability: Optional[str],
        min_rating: Optional[float],
        page: int,
        movies: List[Movie],
        total: int,
    ) -> None:
        """Cache browse results."""
        if not self._connected:
            return
        try:
            key = self._browse_key(genre, service, availability, min_rating, page)
            data = json.dumps({
                "movies": [json.loads(m.to_json()) for m in movies],
                "total": total,
            })
            await self._redis.setex(key, BROWSE_TTL, data)
        except Exception as e:
            logger.debug(f"Redis set_browse error: {e}")

    # --- Search Results ---
    async def get_search(self, query: str) -> Optional[List[Movie]]:
        """Get cached search results."""
        if not self._connected:
            return None
        try:
            key = f"search:{query.lower().strip()}"
            data = await self._redis.get(key)
            if not data:
                return None
            return self._deserialize_movies(data)
        except Exception as e:
            logger.debug(f"Redis get_search error: {e}")
            return None

    async def set_search(self, query: str, results: List[Movie]) -> None:
        """Cache search results."""
        if not self._connected:
            return
        try:
            key = f"search:{query.lower().strip()}"
            await self._redis.setex(key, SEARCH_TTL, self._serialize_movies(results))
        except Exception as e:
            logger.debug(f"Redis set_search error: {e}")

    # --- Cache Invalidation ---
    async def invalidate_all(self) -> None:
        """Clear all caches - called after refresh."""
        if not self._connected:
            return
        try:
            # Delete all keys with our prefixes
            for pattern in ["movie_related:*", "top_rated:*", "browse:*", "search:*"]:
                cursor = 0
                while True:
                    cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)
                    if keys:
                        await self._redis.delete(*keys)
                    if cursor == 0:
                        break
        except Exception as e:
            logger.debug(f"Redis invalidate_all error: {e}")

    async def get_stats(self) -> dict:
        """Get cache statistics for monitoring."""
        if not self._connected:
            return {"connected": False}
        try:
            info = await self._redis.info("keyspace")
            db_info = info.get("db0", {})
            return {
                "connected": True,
                "keys": db_info.get("keys", 0) if isinstance(db_info, dict) else 0,
            }
        except Exception as e:
            logger.debug(f"Redis get_stats error: {e}")
            return {"connected": False, "error": str(e)}
