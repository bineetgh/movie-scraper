#!/usr/bin/env python3
"""
Movie Scraper API - REST endpoints to find free movies in India.

Run with: uvicorn api:app --reload
"""

import asyncio
import json
import logging
import os
import random
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from fastapi import FastAPI, Query, HTTPException, Request, Depends, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import Response, RedirectResponse
from fastapi.security import APIKeyHeader

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory cache for genres/services (refreshed periodically)
_genres_cache: List[str] = []
_services_cache: List[str] = []
_cache_timestamp: float = 0
METADATA_CACHE_TTL = 300  # 5 minutes


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
from models.offer import StreamingOffer
from scrapers.justwatch import JustWatchScraper
from scrapers.fallback import InternetArchiveScraper
from scrapers.tmdb import TMDBClient
from utils.slug import generate_movie_slug, parse_movie_slug
from db.mongodb import get_database, close_connection, init_indexes, check_connection
from db.movie_repository import MovieRepository
from db.curated_repository import CuratedListRepository
from models.curated_list import CuratedList
from cache import init_cache, close_cache, get_cache, get_cache_backend_name

# Admin configuration
ADMIN_ACCESS_KEY = os.getenv("ADMIN_ACCESS_KEY", "")
admin_header = APIKeyHeader(name="X-Admin-Key", auto_error=False)

# Global repository instances (set during startup)
movie_repo: Optional[MovieRepository] = None
curated_repo: Optional[CuratedListRepository] = None


def verify_admin_key(request: Request) -> bool:
    """Verify admin access key from query param or cookie."""
    key = request.query_params.get("key") or request.cookies.get("admin_key")
    return key == ADMIN_ACCESS_KEY and ADMIN_ACCESS_KEY != ""


async def get_curated_lists_for_menu() -> List[CuratedList]:
    """Get active curated lists for navigation menu."""
    if curated_repo is not None:
        try:
            return await curated_repo.get_all(active_only=True)
        except Exception:
            pass
    return []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle - connect to MongoDB and cache on startup."""
    global movie_repo, curated_repo
    # Initialize MongoDB
    db = await get_database()
    if db is not None:
        movie_repo = MovieRepository(db)
        curated_repo = CuratedListRepository(db)
        await init_indexes(db)
        logger.info("MongoDB repository initialized")
    else:
        logger.warning("Running without MongoDB - using JSON file cache only")
    # Initialize cache (Redis if REDIS_URL set, otherwise in-memory)
    await init_cache()
    yield
    await close_cache()
    await close_connection()


app = FastAPI(
    title="Free Movies India API",
    description="Find free movies available to watch in India",
    version="1.0.0",
    lifespan=lifespan,
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


def fetch_and_cache_movies(
    limit: int = 500,
    include_archive: bool = True,
    enrich_with_tmdb: bool = True
) -> List[Movie]:
    """Fetch movies from sources and update cache."""
    if cache._is_fetching:
        return cache.get_movies()

    cache._is_fetching = True
    try:
        all_movies = []

        # Fetch from JustWatch India (now includes all monetization types)
        justwatch = JustWatchScraper()
        jw_movies = justwatch.fetch_movies(limit=limit)
        all_movies.extend(jw_movies)

        # Fetch from Internet Archive
        if include_archive:
            archive = InternetArchiveScraper()
            ia_movies = archive.fetch_movies(limit=100)
            all_movies.extend(ia_movies)

        # Enrich with TMDB data
        if enrich_with_tmdb:
            tmdb = TMDBClient()
            if tmdb.is_available:
                print(f"Enriching {len(all_movies)} movies with TMDB data...")
                for i, movie in enumerate(all_movies):
                    all_movies[i] = tmdb.enrich_movie(movie)
                    if (i + 1) % 50 == 0:
                        print(f"Enriched {i + 1}/{len(all_movies)} movies")

        cache.set_movies(all_movies)
        return all_movies
    finally:
        cache._is_fetching = False


def get_cached_movies() -> List[Movie]:
    """Get movies from cache, fetching if needed."""
    if cache.is_empty() or cache.is_stale():
        return fetch_and_cache_movies()
    return cache.get_movies()


async def get_movies_from_db_or_cache() -> List[Movie]:
    """Get movies from MongoDB, falling back to file cache if unavailable."""
    if movie_repo is not None:
        try:
            movies = await movie_repo.get_all(limit=1000)
            if movies:
                return movies
        except Exception as e:
            logger.error(f"MongoDB query failed: {e}")
    # Fallback to file cache
    return get_cached_movies()


async def sync_movies_to_mongodb(movies: List[Movie]):
    """Sync movies to MongoDB after fetching from scrapers."""
    if movie_repo is not None:
        try:
            count = await movie_repo.upsert_movies(movies)
            await movie_repo.set_last_refresh()
            logger.info(f"Synced {count} movies to MongoDB")
            # Invalidate metadata cache
            global _cache_timestamp
            _cache_timestamp = 0
            # Invalidate cache (Redis or memory)
            await get_cache().invalidate_all()
            logger.info(f"Cache invalidated after sync (backend: {get_cache_backend_name()})")
        except Exception as e:
            logger.error(f"Failed to sync to MongoDB: {e}")


async def get_cached_genres_services() -> Tuple[List[str], List[str]]:
    """Get genres and services from cache or MongoDB."""
    global _genres_cache, _services_cache, _cache_timestamp

    # Check if cache is valid
    if time.time() - _cache_timestamp < METADATA_CACHE_TTL and _genres_cache:
        return _genres_cache, _services_cache

    # Refresh from MongoDB
    if movie_repo is not None:
        try:
            _genres_cache, _services_cache = await asyncio.gather(
                movie_repo.get_all_genres(),
                movie_repo.get_all_services(),
            )
            _cache_timestamp = time.time()
        except Exception as e:
            logger.error(f"Failed to refresh metadata cache: {e}")

    # Fallback to file cache if needed
    if not _genres_cache:
        movies = cache.get_movies()
        _genres_cache = get_all_genres(movies)
        _services_cache = get_all_services(movies)
        _cache_timestamp = time.time()

    return _genres_cache, _services_cache


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
async def home(request: Request):
    """SSR home page with top-rated movies."""
    cache_mgr = get_cache()
    curated_lists = await get_curated_lists_for_menu()
    # Try cache first (Redis or memory)
    top_movies = await cache_mgr.get_top_rated(24)

    if top_movies is None:
        # Cache miss - try MongoDB
        if movie_repo is not None:
            try:
                top_movies = await movie_repo.get_top_rated(limit=24)
                if top_movies:
                    await cache_mgr.set_top_rated(24, top_movies)
            except Exception as e:
                logger.error(f"MongoDB query failed: {e}")
                top_movies = []

        if not top_movies:
            # Fallback to file cache
            movies = get_cached_movies()
            top_movies = sorted(
                [m for m in movies if m.rating],
                key=lambda m: m.rating or 0,
                reverse=True
            )[:24]

    return templates.TemplateResponse("index.html", {
        "request": request,
        "movies": top_movies,
        "curated_lists": curated_lists,
        "base_url": BASE_URL,
        "page_title": "Watchlazy - Free Movies, Zero Effort",
        "page_description": "Discover and watch free movies on JioHotstar, MX Player, Zee5, Plex and more. No subscriptions needed.",
        "canonical_path": "/",
        "active_tab": "home",
    })


@app.get("/movie/{slug}")
async def movie_detail(request: Request, slug: str):
    """SSR individual movie page."""
    cache_mgr = get_cache()
    curated_lists = await get_curated_lists_for_menu()
    # Try cache first (Redis or memory)
    cached = await cache_mgr.get_movie_with_related(slug)

    if cached is not None:
        movie, related = cached
    else:
        movie = None
        related = []

        # Try MongoDB
        if movie_repo is not None:
            try:
                movie, related = await movie_repo.get_movie_with_related(slug, related_limit=6)
                if movie is not None:
                    await cache_mgr.set_movie_with_related(slug, movie, related)
            except Exception as e:
                logger.error(f"MongoDB query failed: {e}")

        # Fallback to file cache
        if movie is None:
            movies = get_cached_movies()
            movie = find_movie_by_slug(movies, slug)
            if movie:
                related = get_related_movies(movies, movie, limit=6)

    if movie is None:
        raise HTTPException(status_code=404, detail="Movie not found")

    return templates.TemplateResponse("movie_detail.html", {
        "request": request,
        "movie": movie,
        "related_movies": related,
        "curated_lists": curated_lists,
        "base_url": BASE_URL,
        "page_title": f"{movie.title} ({movie.year}) - Watch Free on Watchlazy" if movie.year else f"{movie.title} - Watch Free on Watchlazy",
        "page_description": movie.synopsis[:160] if movie.synopsis else f"Watch {movie.title} for free on streaming platforms.",
        "canonical_path": movie.canonical_url,
        "og_type": "video.movie",
        "og_image": movie.poster_url,
        "active_tab": None,
    })


@app.get("/browse")
async def browse(
    request: Request,
    service: Optional[str] = Query(None),
    min_rating: float = Query(0, ge=0, le=10),
    availability: str = Query("all"),
    letter: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
):
    """SSR browse page with filters and pagination."""
    per_page = 24
    skip = (page - 1) * per_page
    paginated = []
    total = 0
    services_list = []
    curated_lists = await get_curated_lists_for_menu()

    # Map availability to type filter
    avail_filter = None if availability == "all" else availability
    min_rating_filter = min_rating if min_rating > 0 else None
    use_fallback = True

    # Get movies from MongoDB or file cache
    if movie_repo is not None:
        try:
            # Build query with letter filter
            paginated, total, (_, services_list) = await asyncio.gather(
                movie_repo.get_all(
                    service=service,
                    availability=avail_filter,
                    min_rating=min_rating_filter,
                    letter=letter,
                    sort_by="title" if letter else "rating",
                    skip=skip,
                    limit=per_page,
                ),
                movie_repo.count(
                    service=service,
                    availability=avail_filter,
                    min_rating=min_rating_filter,
                    letter=letter,
                ),
                get_cached_genres_services(),
            )
            use_fallback = False
        except Exception as e:
            logger.error(f"MongoDB query failed: {e}")
            paginated = []

    # Fallback to file cache if MongoDB fails or unavailable
    if use_fallback:
        movies = get_cached_movies()

        # Apply filters
        filtered = movies
        if service:
            filtered = [m for m in filtered if service in m.streaming_services]
        if min_rating > 0:
            filtered = [m for m in filtered if m.rating and m.rating >= min_rating]

        # Filter by availability type
        if availability == "free":
            filtered = [m for m in filtered if m.is_free]
        elif availability == "subscription":
            filtered = [m for m in filtered if m.has_subscription]
        elif availability == "rent":
            filtered = [m for m in filtered if m.is_rentable]
        elif availability == "buy":
            filtered = [m for m in filtered if m.is_buyable]

        # Filter by letter
        if letter:
            if letter == "0-9":
                filtered = [m for m in filtered if m.title and m.title[0].isdigit()]
            else:
                filtered = [m for m in filtered if m.title and m.title[0].upper() == letter.upper()]

        # Sort by title if letter filter, otherwise by rating
        if letter:
            filtered = sorted(filtered, key=lambda m: m.title.lower())
        else:
            filtered = sorted(filtered, key=lambda m: m.rating or 0, reverse=True)

        total = len(filtered)
        paginated = filtered[skip:skip + per_page]
        services_list = get_all_services(movies)

    total_pages = (total + per_page - 1) // per_page if total > 0 else 1

    # Build page description
    availability_labels = {
        "all": "all",
        "free": "free",
        "subscription": "subscription",
        "rent": "rental",
        "buy": "purchase"
    }
    avail_label = availability_labels.get(availability, "all")
    desc_parts = [f"Browse {avail_label} movies"]
    if letter:
        desc_parts.append(f"starting with {letter}")
    if service:
        desc_parts.append(f"on {service}")
    page_desc = " ".join(desc_parts) + " on Watchlazy."

    return templates.TemplateResponse("browse.html", {
        "request": request,
        "movies": paginated,
        "services": services_list,
        "curated_lists": curated_lists,
        "current_service": service,
        "min_rating": min_rating,
        "current_availability": availability,
        "current_letter": letter,
        "page": page,
        "total_pages": total_pages,
        "total_movies": total,
        "base_url": BASE_URL,
        "page_title": f"Browse {letter + ' ' if letter else ''}Movies - Watchlazy",
        "page_description": page_desc,
        "canonical_path": "/browse",
        "active_tab": "browse",
    })


@app.get("/genre/{genre_name}")
async def genre_page(
    request: Request,
    genre_name: str,
    page: int = Query(1, ge=1),
):
    """SSR genre page showing movies in a specific genre."""
    per_page = 24
    skip = (page - 1) * per_page
    paginated = []
    total = 0
    curated_lists = await get_curated_lists_for_menu()

    # Capitalize genre name for display
    genre_display = genre_name.replace("-", " ").title()
    if genre_name.lower() == "sci-fi":
        genre_display = "Sci-Fi"

    if movie_repo is not None:
        try:
            paginated, total = await asyncio.gather(
                movie_repo.get_all(
                    genre=genre_display,
                    sort_by="rating",
                    skip=skip,
                    limit=per_page,
                ),
                movie_repo.count(genre=genre_display),
            )
        except Exception as e:
            logger.error(f"MongoDB query failed: {e}")

    # Fallback to file cache
    if not paginated:
        movies = get_cached_movies()
        filtered = [m for m in movies if genre_display in m.genres]
        filtered = sorted(filtered, key=lambda m: m.rating or 0, reverse=True)
        total = len(filtered)
        paginated = filtered[skip:skip + per_page]

    total_pages = (total + per_page - 1) // per_page if total > 0 else 1

    return templates.TemplateResponse("genre.html", {
        "request": request,
        "movies": paginated,
        "genre": genre_display,
        "curated_lists": curated_lists,
        "page": page,
        "total_pages": total_pages,
        "total_movies": total,
        "base_url": BASE_URL,
        "page_title": f"{genre_display} Movies - Watchlazy",
        "page_description": f"Browse {genre_display} movies on Watchlazy. Find free and streaming {genre_display} films.",
        "canonical_path": f"/genre/{genre_name}",
        "active_tab": "browse",
    })


@app.get("/genres")
async def all_genres_page(request: Request):
    """SSR page showing all genres with movie counts."""
    genre_counts = {}
    curated_lists = await get_curated_lists_for_menu()

    if movie_repo is not None:
        try:
            genre_counts = await movie_repo.get_genre_counts()
        except Exception as e:
            logger.error(f"MongoDB query failed: {e}")

    # Fallback to file cache
    if not genre_counts:
        movies = get_cached_movies()
        for movie in movies:
            for genre in movie.genres:
                genre_counts[genre] = genre_counts.get(genre, 0) + 1

    # Sort by count descending
    sorted_genres = sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)

    return templates.TemplateResponse("genres.html", {
        "request": request,
        "genres": sorted_genres,
        "curated_lists": curated_lists,
        "base_url": BASE_URL,
        "page_title": "All Genres - Watchlazy",
        "page_description": "Browse movies by genre on Watchlazy. Find action, comedy, drama, horror and more.",
        "canonical_path": "/genres",
        "active_tab": "browse",
    })


@app.get("/search")
async def search_page(request: Request, q: str = Query("")):
    """SSR search results page."""
    results = []
    cache_mgr = get_cache()
    curated_lists = await get_curated_lists_for_menu()

    if q:
        # Try cache first (Redis or memory)
        results = await cache_mgr.get_search(q)

        if results is None:
            results = []
            # Cache miss - try MongoDB
            if movie_repo is not None:
                try:
                    results = await movie_repo.search(q, limit=50)
                    if results:
                        await cache_mgr.set_search(q, results)
                except Exception as e:
                    logger.error(f"MongoDB search failed: {e}")

            # Fallback to in-memory search
            if not results:
                movies = get_cached_movies()
                results = search_cached_movies(q, movies)[:50]

    return templates.TemplateResponse("search_results.html", {
        "request": request,
        "query": q,
        "results": results,
        "curated_lists": curated_lists,
        "base_url": BASE_URL,
        "page_title": f"Search: {q} - Watchlazy" if q else "Search Movies - Watchlazy",
        "page_description": f"Search results for '{q}' on Watchlazy." if q else "Search for free movies on Watchlazy.",
        "canonical_path": f"/search?q={q}" if q else "/search",
        "active_tab": None,
    })


@app.get("/for-me")
async def for_me_page(request: Request):
    """SSR personalized recommendations page."""
    movies = await get_movies_from_db_or_cache()
    curated_lists = await get_curated_lists_for_menu()

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

    movies_json = json.dumps(movies_data)

    return templates.TemplateResponse("for_me.html", {
        "request": request,
        "movies_json": movies_json,
        "curated_lists": curated_lists,
        "base_url": BASE_URL,
        "page_title": "For Me - Personalized Recommendations - Watchlazy",
        "page_description": "Get personalized movie recommendations based on your watch history and preferences.",
        "canonical_path": "/for-me",
        "active_tab": "for-me",
    })


@app.get("/sitemap.xml")
async def sitemap():
    """Generate dynamic XML sitemap for SEO."""
    from datetime import datetime
    movies = await get_movies_from_db_or_cache()
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


@app.get("/favicon.ico")
async def favicon():
    """Redirect favicon.ico to SVG favicon."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/static/favicon.svg", status_code=301)


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
async def get_movies(
    limit: int = Query(50, ge=1, le=500, description="Number of movies to return"),
    service: Optional[str] = Query(None, description="Filter by streaming service"),
    genre: Optional[str] = Query(None, description="Filter by genre"),
):
    """Get all available free movies."""
    # Try MongoDB first
    if movie_repo is not None:
        try:
            movies = await movie_repo.get_all(
                genre=genre,
                service=service,
                limit=limit,
            )
            return [m.to_dict() for m in movies]
        except Exception as e:
            logger.error(f"MongoDB query failed: {e}")

    # Fallback to file cache
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
async def search_movies(
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
    cache_results = []
    online_results = []
    source = "mongodb" if movie_repo is not None else "cache"

    # Step 1: Search MongoDB or cache first (unless force_online)
    if not force_online:
        if movie_repo is not None:
            try:
                cache_results = await movie_repo.search(q, limit=50)
            except Exception as e:
                logger.error(f"MongoDB search failed: {e}")
                source = "cache"

        if not cache_results:
            cached_movies = cache.get_movies()
            if cached_movies:
                cache_results = search_cached_movies(q, cached_movies)
                source = "cache"

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

    return {
        "results": [m.to_dict() for m in all_results],
        "source": source,
        "cache_count": len(cache_results),
        "online_count": len(online_results),
        "total": len(all_results),
    }


@app.get("/movies/random", response_model=List[Dict])
async def get_random_movies(
    count: int = Query(5, ge=1, le=20, description="Number of random movies"),
    service: Optional[str] = Query(None, description="Filter by streaming service"),
):
    """Get random movie recommendations."""
    # Try MongoDB first (uses $sample aggregation)
    if movie_repo is not None and not service:
        try:
            movies = await movie_repo.get_random(limit=count)
            if movies:
                return [m.to_dict() for m in movies]
        except Exception as e:
            logger.error(f"MongoDB random query failed: {e}")

    # Fallback to file cache
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
async def get_top_movies(
    limit: int = Query(20, ge=1, le=100, description="Number of top movies to return"),
    min_rating: float = Query(0.0, ge=0.0, le=10.0, description="Minimum IMDb rating"),
    service: Optional[str] = Query(None, description="Filter by streaming service"),
):
    """Get top-rated movies sorted by IMDb score."""
    # Try MongoDB first
    if movie_repo is not None:
        try:
            movies = await movie_repo.get_all(
                service=service,
                min_rating=min_rating if min_rating > 0 else None,
                sort_by="rating",
                limit=limit,
            )
            if movies:
                return [m.to_dict() for m in movies]
        except Exception as e:
            logger.error(f"MongoDB query failed: {e}")

    # Fallback to file cache
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
async def get_streaming_services():
    """Get list of all available streaming services."""
    # Try MongoDB aggregation first
    if movie_repo is not None:
        try:
            service_counts = await movie_repo.get_service_counts()
            total = await movie_repo.get_total_count()
            sorted_services = sorted(service_counts.items(), key=lambda x: x[1], reverse=True)
            return {
                "services": [{"name": name, "movie_count": count} for name, count in sorted_services],
                "total_movies": total,
            }
        except Exception as e:
            logger.error(f"MongoDB query failed: {e}")

    # Fallback to file cache
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


@app.get("/movies/offers/{slug}")
async def get_movie_offers(slug: str):
    """Get detailed streaming offers and pricing for a movie."""
    movie = None

    # Try MongoDB first
    if movie_repo is not None:
        try:
            movie = await movie_repo.get_by_slug(slug)
        except Exception as e:
            logger.error(f"MongoDB query failed: {e}")

    # Fallback to file cache
    if not movie:
        movies = get_cached_movies()
        movie = find_movie_by_slug(movies, slug)

    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found")

    return {
        "title": movie.title,
        "year": movie.year,
        "free": [o.to_dict() for o in movie.streaming.free_offers],
        "subscription": [o.to_dict() for o in movie.streaming.subscription_offers],
        "rent": {
            "offers": [o.to_dict() for o in movie.streaming.rent_offers],
            "min_price": movie.streaming.min_rent_price,
        },
        "buy": {
            "offers": [o.to_dict() for o in movie.streaming.buy_offers],
            "min_price": movie.streaming.min_buy_price,
        },
    }


@app.get("/movies/{movie_title}")
async def get_movie_by_title(movie_title: str):
    """Get a specific movie by title (partial match)."""
    # Try MongoDB search first
    if movie_repo is not None:
        try:
            matches = await movie_repo.search(movie_title, limit=20)
            if matches:
                return [m.to_dict() for m in matches]
        except Exception as e:
            logger.error(f"MongoDB search failed: {e}")

    # Fallback to file cache
    movies = get_cached_movies()

    title_lower = movie_title.lower()
    matches = [m for m in movies if title_lower in m.title.lower()]

    if not matches:
        raise HTTPException(status_code=404, detail=f"Movie not found: {movie_title}")

    return [m.to_dict() for m in matches]


# ========== ADMIN ROUTES ==========

@app.get("/admin")
async def admin_login_page(request: Request):
    """Admin login page."""
    if verify_admin_key(request):
        return RedirectResponse(url="/admin/dashboard", status_code=302)
    return templates.TemplateResponse("admin/login.html", {
        "request": request,
        "error": request.query_params.get("error"),
    })


@app.post("/admin/login")
async def admin_login(request: Request, key: str = Form(...)):
    """Process admin login."""
    if key == ADMIN_ACCESS_KEY and ADMIN_ACCESS_KEY != "":
        response = RedirectResponse(url="/admin/dashboard", status_code=302)
        response.set_cookie("admin_key", key, httponly=True, max_age=86400)
        return response
    return RedirectResponse(url="/admin?error=invalid", status_code=302)


@app.get("/admin/logout")
async def admin_logout():
    """Admin logout."""
    response = RedirectResponse(url="/admin", status_code=302)
    response.delete_cookie("admin_key")
    return response


@app.get("/admin/dashboard")
async def admin_dashboard(request: Request, page: int = Query(1, ge=1), search: str = Query("")):
    """Admin dashboard with movies table."""
    if not verify_admin_key(request):
        return RedirectResponse(url="/admin", status_code=302)

    per_page = 50
    skip = (page - 1) * per_page
    movies = []
    total = 0

    if movie_repo is not None:
        try:
            if search:
                movies = await movie_repo.search(search, limit=per_page)
                total = len(movies)
            else:
                movies, total = await asyncio.gather(
                    movie_repo.get_all(sort_by="title", skip=skip, limit=per_page),
                    movie_repo.get_total_count(),
                )
        except Exception as e:
            logger.error(f"Admin dashboard query failed: {e}")

    # Fallback to file cache
    if not movies and not search:
        all_movies = get_cached_movies()
        all_movies = sorted(all_movies, key=lambda m: m.title.lower())
        total = len(all_movies)
        movies = all_movies[skip:skip + per_page]

    total_pages = (total + per_page - 1) // per_page if total > 0 else 1

    # Get curated lists for the dropdown
    curated_lists = []
    if curated_repo is not None:
        try:
            curated_lists = await curated_repo.get_all(active_only=False)
        except Exception:
            pass

    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "movies": movies,
        "curated_lists": curated_lists,
        "page": page,
        "total_pages": total_pages,
        "total_movies": total,
        "search": search,
    })


@app.get("/admin/movie/{slug}")
async def admin_edit_movie(request: Request, slug: str):
    """Admin movie edit page."""
    if not verify_admin_key(request):
        return RedirectResponse(url="/admin", status_code=302)

    movie = None
    if movie_repo is not None:
        try:
            movie = await movie_repo.get_by_slug(slug)
        except Exception as e:
            logger.error(f"Failed to get movie: {e}")

    if not movie:
        movies = get_cached_movies()
        movie = find_movie_by_slug(movies, slug)

    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found")

    return templates.TemplateResponse("admin/edit_movie.html", {
        "request": request,
        "movie": movie,
    })


@app.post("/admin/movie/{slug}")
async def admin_update_movie(
    request: Request,
    slug: str,
    title: str = Form(...),
    year: int = Form(None),
    rating: float = Form(None),
    synopsis: str = Form(""),
    director: str = Form(""),
    genres: str = Form(""),
):
    """Update movie details."""
    if not verify_admin_key(request):
        return RedirectResponse(url="/admin", status_code=302)

    if movie_repo is not None:
        try:
            movie = await movie_repo.get_by_slug(slug)
            if movie:
                # Update fields
                movie.title = title
                movie.year = year
                movie.rating = rating
                movie.synopsis = synopsis
                movie.director = director
                movie.genres = [g.strip() for g in genres.split(",") if g.strip()]

                # Save to database
                await movie_repo.upsert_movies([movie])

                # Invalidate cache
                await get_cache().invalidate_all()

                return RedirectResponse(
                    url=f"/admin/movie/{slug}?success=1",
                    status_code=302
                )
        except Exception as e:
            logger.error(f"Failed to update movie: {e}")

    return RedirectResponse(url=f"/admin/movie/{slug}?error=1", status_code=302)


@app.get("/admin/lists")
async def admin_curated_lists(request: Request):
    """Admin curated lists management page."""
    if not verify_admin_key(request):
        return RedirectResponse(url="/admin", status_code=302)

    curated_lists = []
    if curated_repo is not None:
        try:
            curated_lists = await curated_repo.get_all(active_only=False)
        except Exception as e:
            logger.error(f"Failed to get curated lists: {e}")

    return templates.TemplateResponse("admin/curated_lists.html", {
        "request": request,
        "lists": curated_lists,
    })


@app.post("/admin/lists/create")
async def admin_create_list(
    request: Request,
    label: str = Form(...),
    slug: str = Form(...),
    description: str = Form(""),
):
    """Create a new curated list."""
    if not verify_admin_key(request):
        return RedirectResponse(url="/admin", status_code=302)

    if curated_repo is not None:
        try:
            new_list = CuratedList(
                slug=slug.lower().replace(" ", "-"),
                label=label,
                description=description,
                is_active=True,
            )
            await curated_repo.create(new_list)
        except Exception as e:
            logger.error(f"Failed to create curated list: {e}")

    return RedirectResponse(url="/admin/lists", status_code=302)


@app.get("/admin/lists/{slug}")
async def admin_edit_list(request: Request, slug: str):
    """Edit a curated list."""
    if not verify_admin_key(request):
        return RedirectResponse(url="/admin", status_code=302)

    curated_list = None
    movies = []

    if curated_repo is not None:
        try:
            curated_list = await curated_repo.get_by_slug(slug)
            if curated_list:
                movies = await curated_repo.get_movies_for_list(slug, limit=100)
        except Exception as e:
            logger.error(f"Failed to get curated list: {e}")

    if not curated_list:
        raise HTTPException(status_code=404, detail="List not found")

    return templates.TemplateResponse("admin/edit_list.html", {
        "request": request,
        "list": curated_list,
        "movies": movies,
    })


@app.post("/admin/lists/{slug}/update")
async def admin_update_list(
    request: Request,
    slug: str,
    label: str = Form(...),
    description: str = Form(""),
    is_active: bool = Form(False),
    display_order: int = Form(0),
):
    """Update a curated list."""
    if not verify_admin_key(request):
        return RedirectResponse(url="/admin", status_code=302)

    if curated_repo is not None:
        try:
            curated_list = await curated_repo.get_by_slug(slug)
            if curated_list:
                curated_list.label = label
                curated_list.description = description
                curated_list.is_active = is_active
                curated_list.display_order = display_order
                await curated_repo.update(curated_list)
        except Exception as e:
            logger.error(f"Failed to update curated list: {e}")

    return RedirectResponse(url=f"/admin/lists/{slug}", status_code=302)


@app.post("/admin/lists/{slug}/add-movie")
async def admin_add_movie_to_list(
    request: Request,
    slug: str,
    movie_slug: str = Form(...),
):
    """Add a movie to a curated list."""
    if not verify_admin_key(request):
        return {"success": False, "error": "Unauthorized"}

    if curated_repo is not None:
        try:
            await curated_repo.add_movie(slug, movie_slug)
            return {"success": True}
        except Exception as e:
            logger.error(f"Failed to add movie to list: {e}")
            return {"success": False, "error": str(e)}

    return {"success": False, "error": "Database not available"}


@app.post("/admin/lists/{slug}/remove-movie")
async def admin_remove_movie_from_list(
    request: Request,
    slug: str,
    movie_slug: str = Form(...),
):
    """Remove a movie from a curated list."""
    if not verify_admin_key(request):
        return {"success": False, "error": "Unauthorized"}

    if curated_repo is not None:
        try:
            await curated_repo.remove_movie(slug, movie_slug)
            return {"success": True}
        except Exception as e:
            logger.error(f"Failed to remove movie from list: {e}")
            return {"success": False, "error": str(e)}

    return {"success": False, "error": "Database not available"}


@app.post("/admin/lists/{slug}/delete")
async def admin_delete_list(request: Request, slug: str):
    """Delete a curated list."""
    if not verify_admin_key(request):
        return RedirectResponse(url="/admin", status_code=302)

    if curated_repo is not None:
        try:
            await curated_repo.delete(slug)
        except Exception as e:
            logger.error(f"Failed to delete curated list: {e}")

    return RedirectResponse(url="/admin/lists", status_code=302)


@app.post("/admin/refresh")
async def admin_refresh_cache(
    request: Request,
    limit: int = Form(500),
):
    """Admin-only: Force refresh the movie cache and sync to MongoDB."""
    if not verify_admin_key(request):
        return RedirectResponse(url="/admin", status_code=302)

    movies = fetch_and_cache_movies(limit=limit, include_archive=True)
    await sync_movies_to_mongodb(movies)

    return RedirectResponse(url="/admin/dashboard?refreshed=1", status_code=302)


# ========== CURATED LIST USER ROUTES ==========

@app.get("/list/{slug}")
async def curated_list_page(
    request: Request,
    slug: str,
    page: int = Query(1, ge=1),
):
    """Display a curated list to users."""
    per_page = 24
    curated_list = None
    movies = []
    curated_lists = await get_curated_lists_for_menu()

    if curated_repo is not None:
        try:
            curated_list = await curated_repo.get_by_slug(slug)
            if curated_list and curated_list.is_active:
                movies = await curated_repo.get_movies_for_list(slug, limit=100)
        except Exception as e:
            logger.error(f"Failed to get curated list: {e}")

    if not curated_list or not curated_list.is_active:
        raise HTTPException(status_code=404, detail="List not found")

    total = len(movies)
    skip = (page - 1) * per_page
    paginated = movies[skip:skip + per_page]
    total_pages = (total + per_page - 1) // per_page if total > 0 else 1

    return templates.TemplateResponse("curated_list.html", {
        "request": request,
        "list": curated_list,
        "movies": paginated,
        "curated_lists": curated_lists,
        "page": page,
        "total_pages": total_pages,
        "total_movies": total,
        "base_url": BASE_URL,
        "page_title": f"{curated_list.label} - Watchlazy",
        "page_description": curated_list.description or f"Browse {curated_list.label} on Watchlazy.",
        "canonical_path": f"/list/{slug}",
        "active_tab": None,
    })


# ========== LEGACY API ENDPOINTS (Admin-only refresh) ==========

@app.post("/refresh")
async def refresh_cache(
    request: Request,
    limit: int = Query(500, ge=100, le=1000, description="Number of movies to fetch"),
):
    """Force refresh the movie cache and sync to MongoDB. Requires admin key."""
    if not verify_admin_key(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    movies = fetch_and_cache_movies(limit=limit, include_archive=True)

    # Sync to MongoDB
    await sync_movies_to_mongodb(movies)

    return {
        "message": "Cache refreshed successfully",
        "total_movies": len(movies),
        "cache_ttl_seconds": cache.ttl,
        "mongodb_synced": movie_repo is not None,
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    mongodb_connected = await check_connection() if movie_repo is not None else False
    mongodb_count = 0

    if movie_repo is not None and mongodb_connected:
        try:
            mongodb_count = await movie_repo.get_total_count()
        except Exception:
            pass

    # Get cache stats (works for both Redis and memory cache)
    cache_mgr = get_cache()
    cache_backend = get_cache_backend_name()

    # Handle async get_stats for Redis, sync for memory
    if hasattr(cache_mgr, 'get_stats'):
        cache_stats = cache_mgr.get_stats()
        if asyncio.iscoroutine(cache_stats):
            cache_stats = await cache_stats
    else:
        cache_stats = {}

    return {
        "status": "healthy",
        "cache_size": len(cache.get_movies()),
        "cache_stale": cache.is_stale(),
        "mongodb_connected": mongodb_connected,
        "mongodb_count": mongodb_count,
        "cache_backend": cache_backend,
        "cache_stats": cache_stats,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
