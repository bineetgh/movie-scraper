"""Cache package for movie data."""

import os
import logging
from typing import Union

from cache.memory_cache import memory_cache, MovieCacheManager
from cache.redis_cache import RedisCacheManager

logger = logging.getLogger(__name__)

# Cache manager instance - will be set at startup
_cache_manager: Union[MovieCacheManager, RedisCacheManager, None] = None


async def init_cache() -> Union[MovieCacheManager, RedisCacheManager]:
    """Initialize cache manager based on environment.

    If REDIS_URL is set, attempts Redis connection.
    Falls back to in-memory cache if Redis is unavailable.
    """
    global _cache_manager

    redis_url = os.getenv("REDIS_URL")

    if redis_url:
        redis_cache = RedisCacheManager()
        if await redis_cache.connect(redis_url):
            _cache_manager = redis_cache
            logger.info("Using Redis cache backend")
            return redis_cache
        logger.warning("Redis connection failed, falling back to memory cache")

    _cache_manager = memory_cache
    logger.info("Using in-memory cache backend")
    return memory_cache


async def close_cache() -> None:
    """Close cache connections."""
    global _cache_manager
    if isinstance(_cache_manager, RedisCacheManager):
        await _cache_manager.close()
    _cache_manager = None


def get_cache() -> Union[MovieCacheManager, RedisCacheManager]:
    """Get the active cache manager."""
    if _cache_manager is None:
        return memory_cache
    return _cache_manager


def get_cache_backend_name() -> str:
    """Get the name of the active cache backend."""
    if isinstance(_cache_manager, RedisCacheManager) and _cache_manager.is_connected():
        return "redis"
    return "memory"


__all__ = [
    "memory_cache",
    "MovieCacheManager",
    "RedisCacheManager",
    "init_cache",
    "close_cache",
    "get_cache",
    "get_cache_backend_name",
]
