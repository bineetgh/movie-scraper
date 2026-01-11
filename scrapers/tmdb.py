import os
from typing import Dict, List, Optional

from scrapers.base import BaseScraper
from models.movie import Movie


class TMDBClient(BaseScraper):
    """Client for The Movie Database API for enriched metadata."""

    BASE_URL = "https://api.themoviedb.org/3"
    IMAGE_BASE_URL = "https://image.tmdb.org/t/p"

    def __init__(self):
        super().__init__()
        self.api_key = os.getenv("TMDB_API_KEY")
        # TMDB v3 API uses api_key as query parameter

    @property
    def is_available(self) -> bool:
        """Check if TMDB API key is configured."""
        return bool(self.api_key)

    def search_movie(self, title: str, year: Optional[int] = None) -> Optional[Dict]:
        """Search for a movie by title and optional year."""
        if not self.is_available:
            return None

        params = {
            "api_key": self.api_key,
            "query": title,
            "language": "en-US",
            "include_adult": "false",
            "region": "IN",
        }
        if year:
            params["year"] = year

        try:
            response = self.get(f"{self.BASE_URL}/search/movie", params=params)
            results = response.json().get("results", [])
            if results:
                return results[0]
        except Exception as e:
            print(f"TMDB search error: {e}")
        return None

    def get_movie_details(self, tmdb_id: int) -> Optional[Dict]:
        """Get detailed movie information by TMDB ID."""
        if not self.is_available:
            return None

        try:
            response = self.get(
                f"{self.BASE_URL}/movie/{tmdb_id}",
                params={
                    "api_key": self.api_key,
                    "language": "en-US",
                    "append_to_response": "credits,videos,external_ids"
                }
            )
            return response.json()
        except Exception as e:
            print(f"TMDB details error for {tmdb_id}: {e}")
        return None

    def enrich_movie(self, movie: Movie) -> Movie:
        """Enrich a movie with TMDB data."""
        if not self.is_available:
            return movie

        tmdb_data = None

        # Try to find by TMDB ID first
        if movie.tmdb_id:
            tmdb_data = self.get_movie_details(movie.tmdb_id)
        else:
            # Search by title and year
            search_result = self.search_movie(movie.title, movie.year)
            if search_result:
                movie.tmdb_id = search_result.get("id")
                tmdb_data = self.get_movie_details(movie.tmdb_id)

        if not tmdb_data:
            return movie

        # Enrich with TMDB data
        if not movie.imdb_id:
            external_ids = tmdb_data.get("external_ids", {})
            movie.imdb_id = external_ids.get("imdb_id")

        movie.tagline = tmdb_data.get("tagline") or movie.tagline
        movie.original_language = tmdb_data.get("original_language")
        movie.popularity = tmdb_data.get("popularity")
        movie.vote_count = tmdb_data.get("vote_count")

        # Better synopsis if available
        overview = tmdb_data.get("overview", "")
        if overview and len(overview) > len(movie.synopsis or ""):
            movie.synopsis = overview

        # High-quality images
        if tmdb_data.get("poster_path"):
            movie.tmdb_poster_url = f"{self.IMAGE_BASE_URL}/w780{tmdb_data['poster_path']}"

        if tmdb_data.get("backdrop_path"):
            movie.backdrop_url = f"{self.IMAGE_BASE_URL}/w1280{tmdb_data['backdrop_path']}"

        # Extract trailer URL from videos
        videos = tmdb_data.get("videos", {}).get("results", [])
        for video in videos:
            if video.get("type") == "Trailer" and video.get("site") == "YouTube":
                movie.trailer_url = f"https://www.youtube.com/watch?v={video['key']}"
                break

        # Enrich cast if not already present
        credits = tmdb_data.get("credits", {})
        if not movie.cast and credits.get("cast"):
            movie.cast = [c["name"] for c in credits["cast"][:10]]
        if not movie.director and credits.get("crew"):
            for crew in credits["crew"]:
                if crew.get("job") == "Director":
                    movie.director = crew["name"]
                    break

        return movie

    def fetch_movies(self, limit: Optional[int] = None) -> List[Movie]:
        """Not used - TMDB is for enrichment only."""
        return []

    def search(self, query: str) -> List[Movie]:
        """Not used - TMDB is for enrichment only."""
        return []
