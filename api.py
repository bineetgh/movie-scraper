#!/usr/bin/env python3
"""
Movie Scraper API - REST endpoints to find free movies in India.

Run with: uvicorn api:app --reload
"""

import random
import time
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from models.movie import Movie
from scrapers.justwatch import JustWatchScraper
from scrapers.fallback import InternetArchiveScraper


app = FastAPI(
    title="Free Movies India API",
    description="Find free movies available to watch in India",
    version="1.0.0",
)

# Serve static files
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Enable CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Cache Layer ---
class MovieCache:
    """Simple in-memory cache for movie data."""

    def __init__(self, ttl_seconds: int = 3600):  # 1 hour default
        self.ttl = ttl_seconds
        self._movies: List[Movie] = []
        self._last_fetch: float = 0
        self._is_fetching: bool = False

    def is_stale(self) -> bool:
        return time.time() - self._last_fetch > self.ttl

    def get_movies(self) -> List[Movie]:
        return self._movies

    def set_movies(self, movies: List[Movie]):
        self._movies = movies
        self._last_fetch = time.time()

    def is_empty(self) -> bool:
        return len(self._movies) == 0


# Global cache instance
cache = MovieCache(ttl_seconds=3600)  # Cache for 1 hour


def fetch_and_cache_movies(limit: int = 500, include_archive: bool = True) -> List[Movie]:
    """Fetch movies from sources and update cache."""
    if cache._is_fetching:
        return cache.get_movies()

    cache._is_fetching = True
    try:
        all_movies = []

        # Fetch from JustWatch India
        justwatch = JustWatchScraper()
        jw_movies = justwatch.fetch_movies(limit=limit)
        all_movies.extend(jw_movies)

        # Fetch from Internet Archive
        if include_archive:
            archive = InternetArchiveScraper()
            ia_movies = archive.fetch_movies(limit=100)
            all_movies.extend(ia_movies)

        cache.set_movies(all_movies)
        return all_movies
    finally:
        cache._is_fetching = False


def get_cached_movies() -> List[Movie]:
    """Get movies from cache, fetching if needed."""
    if cache.is_empty() or cache.is_stale():
        return fetch_and_cache_movies()
    return cache.get_movies()


# --- API Endpoints ---

@app.get("/")
def root():
    """Serve the web frontend."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {
        "message": "Free Movies India API",
        "endpoints": {
            "/movies": "Get all free movies",
            "/movies/search": "Search movies by title",
            "/movies/random": "Get random movie recommendations",
            "/movies/top": "Get top-rated movies by IMDb score",
            "/movies/services": "List available streaming services",
            "/refresh": "Force refresh movie cache",
        }
    }


@app.get("/api")
def api_info():
    """API info - returns available endpoints."""
    return {
        "message": "Free Movies India API",
        "endpoints": {
            "/movies": "Get all free movies",
            "/movies/search": "Search movies by title",
            "/movies/random": "Get random movie recommendations",
            "/movies/top": "Get top-rated movies by IMDb score",
            "/movies/services": "List available streaming services",
            "/refresh": "Force refresh movie cache",
        }
    }


@app.get("/movies", response_model=List[Dict])
def get_movies(
    limit: int = Query(50, ge=1, le=500, description="Number of movies to return"),
    service: Optional[str] = Query(None, description="Filter by streaming service"),
    genre: Optional[str] = Query(None, description="Filter by genre"),
):
    """Get all available free movies."""
    movies = get_cached_movies()

    # Filter by service
    if service:
        service_lower = service.lower()
        movies = [m for m in movies if any(service_lower in s.lower() for s in m.streaming_services)]

    # Filter by genre
    if genre:
        genre_lower = genre.lower()
        movies = [m for m in movies if any(genre_lower in g.lower() for g in m.genres)]

    # Limit results
    movies = movies[:limit]

    return [m.to_dict() for m in movies]


@app.get("/movies/search", response_model=List[Dict])
def search_movies(
    q: str = Query(..., min_length=1, description="Search query"),
    include_archive: bool = Query(True, description="Include Internet Archive results"),
):
    """Search for movies by title."""
    results = []

    # Search JustWatch
    justwatch = JustWatchScraper()
    jw_results = justwatch.search(q)
    results.extend(jw_results)

    # Search Internet Archive
    if include_archive:
        archive = InternetArchiveScraper()
        ia_results = archive.search(q)
        results.extend(ia_results)

    if not results:
        return []

    return [m.to_dict() for m in results]


@app.get("/movies/random", response_model=List[Dict])
def get_random_movies(
    count: int = Query(5, ge=1, le=20, description="Number of random movies"),
    service: Optional[str] = Query(None, description="Filter by streaming service"),
):
    """Get random movie recommendations."""
    movies = get_cached_movies()

    if not movies:
        raise HTTPException(status_code=503, detail="No movies available. Try /refresh first.")

    # Filter by service if specified
    if service:
        service_lower = service.lower()
        movies = [m for m in movies if any(service_lower in s.lower() for s in m.streaming_services)]

    if not movies:
        raise HTTPException(status_code=404, detail=f"No movies found for service: {service}")

    # Get random sample
    count = min(count, len(movies))
    random_movies = random.sample(movies, count)

    return [m.to_dict() for m in random_movies]


@app.get("/movies/top", response_model=List[Dict])
def get_top_movies(
    limit: int = Query(20, ge=1, le=100, description="Number of top movies to return"),
    min_rating: float = Query(0.0, ge=0.0, le=10.0, description="Minimum IMDb rating"),
    service: Optional[str] = Query(None, description="Filter by streaming service"),
):
    """Get top-rated movies sorted by IMDb score."""
    movies = get_cached_movies()

    # Filter movies with ratings
    rated_movies = [m for m in movies if m.rating is not None and m.rating >= min_rating]

    # Filter by service if specified
    if service:
        service_lower = service.lower()
        rated_movies = [m for m in rated_movies if any(service_lower in s.lower() for s in m.streaming_services)]

    # Sort by rating (descending)
    rated_movies.sort(key=lambda m: m.rating or 0, reverse=True)

    # Limit results
    top_movies = rated_movies[:limit]

    if not top_movies:
        raise HTTPException(status_code=404, detail="No rated movies found matching criteria")

    return [m.to_dict() for m in top_movies]


@app.get("/movies/services")
def get_streaming_services():
    """Get list of all available streaming services."""
    movies = get_cached_movies()

    services: Dict[str, int] = {}
    for movie in movies:
        for service in movie.streaming_services:
            services[service] = services.get(service, 0) + 1

    # Sort by count
    sorted_services = sorted(services.items(), key=lambda x: x[1], reverse=True)

    return {
        "services": [{"name": name, "movie_count": count} for name, count in sorted_services],
        "total_movies": len(movies),
    }


@app.get("/movies/{movie_title}")
def get_movie_by_title(movie_title: str):
    """Get a specific movie by title (partial match)."""
    movies = get_cached_movies()

    title_lower = movie_title.lower()
    matches = [m for m in movies if title_lower in m.title.lower()]

    if not matches:
        raise HTTPException(status_code=404, detail=f"Movie not found: {movie_title}")

    return [m.to_dict() for m in matches]


@app.post("/refresh")
def refresh_cache(
    limit: int = Query(500, ge=100, le=1000, description="Number of movies to fetch"),
):
    """Force refresh the movie cache."""
    movies = fetch_and_cache_movies(limit=limit, include_archive=True)
    return {
        "message": "Cache refreshed successfully",
        "total_movies": len(movies),
        "cache_ttl_seconds": cache.ttl,
    }


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "cache_size": len(cache.get_movies()),
        "cache_stale": cache.is_stale(),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
