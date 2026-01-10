#!/usr/bin/env python3
"""
Movie Scraper API - REST endpoints to find free movies in India.

Run with: uvicorn api:app --reload
"""

import json
import os
import random
import time
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import Response


def load_env_file():
    """Load environment variables from .env file if it exists."""
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())


# Load .env file
load_env_file()

from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Configuration from environment
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "21600"))  # Default: 6 hours

from models.movie import Movie
from scrapers.justwatch import JustWatchScraper
from scrapers.fallback import InternetArchiveScraper
from utils.slug import generate_movie_slug, parse_movie_slug


app = FastAPI(
    title="Free Movies India API",
    description="Find free movies available to watch in India",
    version="1.0.0",
)

# Serve static files
STATIC_DIR = Path(__file__).parent / "static"
CACHE_DIR = Path(__file__).parent / "cache"
CACHE_FILE = CACHE_DIR / "movies.json"
TEMPLATES_DIR = Path(__file__).parent / "templates"

# Base URL for canonical URLs (set via environment variable in production)
BASE_URL = os.getenv("BASE_URL", "https://watchlazy.com")

# Jinja2 templates for SSR
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

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


# --- Cache Layer with File Persistence ---
class MovieCache:
    """Cache with in-memory + file persistence."""

    def __init__(self, ttl_seconds: int = 21600):  # 6 hours default
        self.ttl = ttl_seconds
        self._movies: List[Movie] = []
        self._last_fetch: float = 0
        self._is_fetching: bool = False
        self._load_from_file()

    def _load_from_file(self):
        """Load cache from JSON file on startup."""
        try:
            if CACHE_FILE.exists():
                file_age = time.time() - os.path.getmtime(CACHE_FILE)
                if file_age < self.ttl:
                    with open(CACHE_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self._movies = [Movie.from_dict(m) for m in data.get("movies", [])]
                    self._last_fetch = data.get("timestamp", time.time() - file_age)
                    print(f"Loaded {len(self._movies)} movies from cache file (age: {file_age/3600:.1f}h)")
                else:
                    print(f"Cache file is stale ({file_age/3600:.1f}h old), will refresh")
        except Exception as e:
            print(f"Error loading cache file: {e}")

    def save_to_file(self):
        """Save cache to JSON file."""
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                "timestamp": self._last_fetch,
                "movies": [m.to_dict() for m in self._movies]
            }
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            print(f"Saved {len(self._movies)} movies to cache file")
        except Exception as e:
            print(f"Error saving cache file: {e}")

    def is_stale(self) -> bool:
        return time.time() - self._last_fetch > self.ttl

    def get_movies(self) -> List[Movie]:
        return self._movies

    def set_movies(self, movies: List[Movie]):
        self._movies = movies
        self._last_fetch = time.time()
        self.save_to_file()

    def is_empty(self) -> bool:
        return len(self._movies) == 0


# Global cache instance
cache = MovieCache(ttl_seconds=CACHE_TTL_SECONDS)


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


def search_cached_movies(query: str, movies: List[Movie]) -> List[Movie]:
    """
    Search cached movies with relevance scoring.

    Scoring:
    - Exact title match: 100
    - Partial title match: 50
    - Word in title: 25
    - Director match: 20
    - Cast match: 15
    - Genre match: 5
    - Synopsis match: 3
    """
    if not query or not movies:
        return []

    query_lower = query.lower().strip()
    query_parts = query_lower.split()
    scored_results = []

    for movie in movies:
        score = 0.0

        # Title matching (highest weight)
        title_lower = movie.title.lower()
        if title_lower == query_lower:
            score += 100  # Exact title match
        elif query_lower in title_lower:
            score += 50  # Partial title match
        elif any(part in title_lower for part in query_parts if len(part) > 2):
            score += 25  # Word match in title

        # Director matching
        if movie.director:
            director_lower = movie.director.lower()
            if query_lower in director_lower:
                score += 20
            elif any(part in director_lower for part in query_parts if len(part) > 2):
                score += 10

        # Cast matching
        for actor in (movie.cast or []):
            actor_lower = actor.lower()
            if query_lower in actor_lower:
                score += 15
                break  # Only count once
            elif any(part in actor_lower for part in query_parts if len(part) > 2):
                score += 8
                break

        # Genre matching (lower weight)
        for genre in (movie.genres or []):
            if query_lower in genre.lower():
                score += 5
                break

        # Synopsis matching (lowest weight)
        if movie.synopsis and query_lower in movie.synopsis.lower():
            score += 3

        if score > 0:
            scored_results.append((movie, score))

    # Sort by score descending
    scored_results.sort(key=lambda x: x[1], reverse=True)

    return [m for m, s in scored_results]


# --- Helper Functions for SSR ---

def find_movie_by_slug(movies: List[Movie], slug: str) -> Optional[Movie]:
    """Find a movie by its URL slug."""
    slug_title, slug_year = parse_movie_slug(slug)

    for movie in movies:
        if movie.slug == slug:
            return movie
        # Fallback: match by title portion if exact slug fails
        if generate_movie_slug(movie.title) == slug_title:
            if slug_year is None or movie.year == slug_year:
                return movie
    return None


def get_related_movies(movies: List[Movie], target: Movie, limit: int = 6) -> List[Movie]:
    """Get related movies based on genre similarity."""
    target_genres = set(target.genres)
    scored = []

    for movie in movies:
        if movie.slug == target.slug:
            continue
        overlap = len(target_genres & set(movie.genres))
        if overlap > 0:
            scored.append((movie, overlap, movie.rating or 0))

    # Sort by genre overlap, then rating
    scored.sort(key=lambda x: (x[1], x[2]), reverse=True)
    return [m for m, _, _ in scored[:limit]]


def get_all_genres(movies: List[Movie]) -> List[str]:
    """Get sorted list of all unique genres."""
    genres = set()
    for movie in movies:
        genres.update(movie.genres)
    return sorted(genres)


def get_all_services(movies: List[Movie]) -> List[str]:
    """Get sorted list of all unique streaming services."""
    services = set()
    for movie in movies:
        services.update(movie.streaming_services)
    return sorted(services)


def deduplicate_movies(cache_results: List[Movie], online_results: List[Movie]) -> List[Movie]:
    """
    Deduplicate movies from cache and online sources.
    Uses title + year as unique key, prefers cache versions (more complete data).
    """
    seen = {}

    # Add cache results first (they're already ranked by relevance)
    for movie in cache_results:
        key = (movie.title.lower().strip(), movie.year)
        if key not in seen:
            seen[key] = movie

    # Add online results if not duplicate
    for movie in online_results:
        key = (movie.title.lower().strip(), movie.year)
        if key not in seen:
            seen[key] = movie

    return list(seen.values())


# --- SSR Routes ---

@app.get("/")
def home(request: Request):
    """SSR home page with top-rated movies."""
    movies = get_cached_movies()

    # Get top-rated movies
    top_movies = sorted(
        [m for m in movies if m.rating],
        key=lambda m: m.rating or 0,
        reverse=True
    )[:24]

    return templates.TemplateResponse("index.html", {
        "request": request,
        "movies": top_movies,
        "base_url": BASE_URL,
        "page_title": "Watchlazy - Free Movies, Zero Effort",
        "page_description": "Discover and watch free movies on JioHotstar, MX Player, Zee5, Plex and more. No subscriptions needed.",
        "canonical_path": "/",
        "active_tab": "home",
    })


@app.get("/movie/{slug}")
def movie_detail(request: Request, slug: str):
    """SSR individual movie page."""
    movies = get_cached_movies()
    movie = find_movie_by_slug(movies, slug)

    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found")

    # Get related movies
    related = get_related_movies(movies, movie, limit=6)

    return templates.TemplateResponse("movie_detail.html", {
        "request": request,
        "movie": movie,
        "related_movies": related,
        "base_url": BASE_URL,
        "page_title": f"{movie.title} ({movie.year}) - Watch Free on Watchlazy" if movie.year else f"{movie.title} - Watch Free on Watchlazy",
        "page_description": movie.synopsis[:160] if movie.synopsis else f"Watch {movie.title} for free on streaming platforms.",
        "canonical_path": movie.canonical_url,
        "og_type": "video.movie",
        "og_image": movie.poster_url,
        "active_tab": None,
    })


@app.get("/browse")
def browse(
    request: Request,
    genre: Optional[str] = Query(None),
    service: Optional[str] = Query(None),
    min_rating: float = Query(0, ge=0, le=10),
    page: int = Query(1, ge=1),
):
    """SSR browse page with filters and pagination."""
    movies = get_cached_movies()
    per_page = 24

    # Apply filters
    filtered = movies
    if genre:
        filtered = [m for m in filtered if genre in m.genres]
    if service:
        filtered = [m for m in filtered if service in m.streaming_services]
    if min_rating > 0:
        filtered = [m for m in filtered if m.rating and m.rating >= min_rating]

    # Sort by rating
    filtered = sorted(filtered, key=lambda m: m.rating or 0, reverse=True)

    # Pagination
    total = len(filtered)
    total_pages = (total + per_page - 1) // per_page
    start = (page - 1) * per_page
    end = start + per_page
    paginated = filtered[start:end]

    # Build page description
    desc_parts = ["Browse free movies"]
    if genre:
        desc_parts = [f"Browse free {genre} movies"]
    if service:
        desc_parts.append(f"on {service}")
    page_desc = " ".join(desc_parts) + " on Watchlazy."

    return templates.TemplateResponse("browse.html", {
        "request": request,
        "movies": paginated,
        "genres": get_all_genres(movies),
        "services": get_all_services(movies),
        "current_genre": genre,
        "current_service": service,
        "min_rating": min_rating,
        "page": page,
        "total_pages": total_pages,
        "total_movies": total,
        "base_url": BASE_URL,
        "page_title": f"Browse {'Genre: ' + genre if genre else 'All'} Free Movies - Watchlazy",
        "page_description": page_desc,
        "canonical_path": "/browse",
        "active_tab": "browse",
    })


@app.get("/search")
def search_page(request: Request, q: str = Query("")):
    """SSR search results page."""
    movies = get_cached_movies()
    results = search_cached_movies(q, movies) if q else []

    return templates.TemplateResponse("search_results.html", {
        "request": request,
        "query": q,
        "results": results[:50],  # Limit to 50 results
        "base_url": BASE_URL,
        "page_title": f"Search: {q} - Watchlazy" if q else "Search Movies - Watchlazy",
        "page_description": f"Search results for '{q}' on Watchlazy." if q else "Search for free movies on Watchlazy.",
        "canonical_path": f"/search?q={q}" if q else "/search",
        "active_tab": None,
    })


@app.get("/for-me")
def for_me_page(request: Request):
    """SSR personalized recommendations page."""
    movies = get_cached_movies()

    # Prepare movies data for JavaScript (client-side recommendation engine)
    movies_data = [
        {
            "slug": m.slug,
            "title": m.title,
            "year": m.year,
            "genres": m.genres,
            "rating": m.rating,
            "synopsis": m.synopsis[:200] if m.synopsis else "",
            "poster_url": m.poster_url,
            "streaming_services": m.streaming_services,
        }
        for m in movies
    ]

    import json
    movies_json = json.dumps(movies_data)

    return templates.TemplateResponse("for_me.html", {
        "request": request,
        "movies_json": movies_json,
        "base_url": BASE_URL,
        "page_title": "For Me - Personalized Recommendations - Watchlazy",
        "page_description": "Get personalized movie recommendations based on your watch history and preferences.",
        "canonical_path": "/for-me",
        "active_tab": "for-me",
    })


@app.get("/sitemap.xml")
def sitemap():
    """Generate dynamic XML sitemap for SEO."""
    from datetime import datetime
    movies = get_cached_movies()
    today = datetime.now().strftime("%Y-%m-%d")

    xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_content += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'

    # Static pages
    static_pages = [
        ("/", "1.0", "daily"),
        ("/browse", "0.9", "daily"),
        ("/for-me", "0.8", "daily"),
    ]

    for path, priority, freq in static_pages:
        xml_content += f"""  <url>
    <loc>{BASE_URL}{path}</loc>
    <lastmod>{today}</lastmod>
    <changefreq>{freq}</changefreq>
    <priority>{priority}</priority>
  </url>\n"""

    # Movie pages
    for movie in movies:
        xml_content += f"""  <url>
    <loc>{BASE_URL}{movie.canonical_url}</loc>
    <lastmod>{today}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>\n"""

    xml_content += '</urlset>'

    return Response(content=xml_content, media_type="application/xml")


@app.get("/robots.txt")
def robots():
    """Serve robots.txt with sitemap reference."""
    content = f"""User-agent: *
Allow: /

Sitemap: {BASE_URL}/sitemap.xml

# Disallow API endpoints for crawlers
Disallow: /movies
Disallow: /refresh
Disallow: /health
Disallow: /api
"""
    return Response(content=content, media_type="text/plain")


# --- API Endpoints ---

@app.get("/api")
def api_root():
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


@app.get("/movies/search")
def search_movies(
    q: str = Query(..., min_length=1, description="Search query"),
    include_archive: bool = Query(True, description="Include Internet Archive results"),
    force_online: bool = Query(False, description="Force external API search"),
    cache_min_results: int = Query(5, ge=0, le=20, description="Minimum cache results before online search"),
):
    """
    Search for movies with cache-first strategy.

    Returns results from cache first. Falls back to external APIs
    if cache results are below the minimum threshold.
    """
    cached_movies = cache.get_movies()
    cache_results = []
    online_results = []
    source = "cache"

    # Step 1: Always search cache first (unless force_online)
    if not force_online and cached_movies:
        cache_results = search_cached_movies(q, cached_movies)

    # Step 2: Determine if we need online search
    needs_online = force_online or len(cache_results) < cache_min_results

    # Step 3: Search external APIs if needed
    if needs_online:
        source = "mixed" if cache_results else "online"

        # JustWatch search
        justwatch = JustWatchScraper()
        jw_results = justwatch.search(q)
        online_results.extend(jw_results)

        # Internet Archive search
        if include_archive:
            archive = InternetArchiveScraper()
            ia_results = archive.search(q)
            online_results.extend(ia_results)

    # Step 4: Deduplicate and merge results
    if online_results:
        all_results = deduplicate_movies(cache_results, online_results)
    else:
        all_results = cache_results
        source = "cache"

    return {
        "results": [m.to_dict() for m in all_results],
        "source": source,
        "cache_count": len(cache_results),
        "online_count": len(online_results),
        "total": len(all_results),
    }


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
