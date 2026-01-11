"""In-memory caching layer using cachetools TTLCache."""

import asyncio
from typing import List, Optional, Dict, Tuple

from cachetools import TTLCache

from models.movie import Movie


class MovieCacheManager:
    """Manages all in-memory caches for movie data."""

    def __init__(self):
        # Movie with related cache: 200 items, 10 min TTL
        self._movie_related_cache: TTLCache = TTLCache(maxsize=200, ttl=600)
        self._movie_related_lock = asyncio.Lock()

        # Top rated cache: 10 items (different limits), 10 min TTL
        self._top_rated_cache: TTLCache = TTLCache(maxsize=10, ttl=600)
        self._top_rated_lock = asyncio.Lock()

        # Browse results cache: 100 items, 5 min TTL
        self._browse_cache: TTLCache = TTLCache(maxsize=100, ttl=300)
        self._browse_lock = asyncio.Lock()

        # Search results cache: 50 items, 5 min TTL
        self._search_cache: TTLCache = TTLCache(maxsize=50, ttl=300)
        self._search_lock = asyncio.Lock()

    # --- Movie with Related ---
    async def get_movie_with_related(
        self, slug: str
    ) -> Optional[Tuple[Movie, List[Movie]]]:
        """Get cached movie and related movies."""
        async with self._movie_related_lock:
            return self._movie_related_cache.get(slug)

    async def set_movie_with_related(
        self, slug: str, movie: Movie, related: List[Movie]
    ) -> None:
        """Cache movie and related movies."""
        async with self._movie_related_lock:
            self._movie_related_cache[slug] = (movie, related)

    # --- Top Rated ---
    async def get_top_rated(self, limit: int) -> Optional[List[Movie]]:
        """Get cached top rated movies."""
        key = f"top:{limit}"
        async with self._top_rated_lock:
            return self._top_rated_cache.get(key)

    async def set_top_rated(self, limit: int, movies: List[Movie]) -> None:
        """Cache top rated movies."""
        key = f"top:{limit}"
        async with self._top_rated_lock:
            self._top_rated_cache[key] = movies

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
        return f"{genre or ''}:{service or ''}:{availability or ''}:{min_rating or 0}:{page}"

    async def get_browse(
        self,
        genre: Optional[str],
        service: Optional[str],
        availability: Optional[str],
        min_rating: Optional[float],
        page: int,
    ) -> Optional[Tuple[List[Movie], int]]:
        """Get cached browse results (movies, total_count)."""
        key = self._browse_key(genre, service, availability, min_rating, page)
        async with self._browse_lock:
            return self._browse_cache.get(key)

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
        key = self._browse_key(genre, service, availability, min_rating, page)
        async with self._browse_lock:
            self._browse_cache[key] = (movies, total)

    # --- Search Results ---
    async def get_search(self, query: str) -> Optional[List[Movie]]:
        """Get cached search results."""
        key = query.lower().strip()
        async with self._search_lock:
            return self._search_cache.get(key)

    async def set_search(self, query: str, results: List[Movie]) -> None:
        """Cache search results."""
        key = query.lower().strip()
        async with self._search_lock:
            self._search_cache[key] = results

    # --- Cache Invalidation ---
    async def invalidate_all(self) -> None:
        """Clear all caches - called after refresh."""
        async with self._movie_related_lock:
            self._movie_related_cache.clear()
        async with self._top_rated_lock:
            self._top_rated_cache.clear()
        async with self._browse_lock:
            self._browse_cache.clear()
        async with self._search_lock:
            self._search_cache.clear()

    def get_stats(self) -> Dict[str, Dict[str, int]]:
        """Get cache statistics for monitoring."""
        return {
            "movie_related": {
                "size": len(self._movie_related_cache),
                "maxsize": self._movie_related_cache.maxsize,
            },
            "top_rated": {
                "size": len(self._top_rated_cache),
                "maxsize": self._top_rated_cache.maxsize,
            },
            "browse": {
                "size": len(self._browse_cache),
                "maxsize": self._browse_cache.maxsize,
            },
            "search": {
                "size": len(self._search_cache),
                "maxsize": self._search_cache.maxsize,
            },
        }


# Global instance
memory_cache = MovieCacheManager()
