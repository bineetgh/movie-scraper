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

    def get_upcoming_movie_full(self, tmdb_id: int) -> Optional[Movie]:
        """Get full movie details for an upcoming movie."""
        if not self.is_available:
            return None

        data = self.get_movie_details(tmdb_id)
        if not data:
            return None

        # Parse year from release date
        release_date = data.get("release_date", "")
        year = None
        if release_date and len(release_date) >= 4:
            try:
                year = int(release_date[:4])
            except ValueError:
                pass

        # Get genre names
        genres = [g.get("name", "") for g in data.get("genres", [])]

        movie = Movie(
            title=data.get("title", "Unknown"),
            year=year,
            tmdb_id=tmdb_id,
            imdb_id=data.get("external_ids", {}).get("imdb_id"),
            synopsis=data.get("overview", ""),
            rating=data.get("vote_average"),
            vote_count=data.get("vote_count"),
            popularity=data.get("popularity"),
            release_date=release_date,
            genres=genres,
            original_language=data.get("original_language"),
            runtime_minutes=data.get("runtime"),
            tagline=data.get("tagline"),
        )

        # Add poster
        if data.get("poster_path"):
            movie.poster_url = f"{self.IMAGE_BASE_URL}/w342{data['poster_path']}"
            movie.tmdb_poster_url = f"{self.IMAGE_BASE_URL}/w780{data['poster_path']}"

        # Add backdrop
        if data.get("backdrop_path"):
            movie.backdrop_url = f"{self.IMAGE_BASE_URL}/w1280{data['backdrop_path']}"

        # Extract cast
        credits = data.get("credits", {})
        if credits.get("cast"):
            movie.cast = [c["name"] for c in credits["cast"][:10]]

        # Extract director
        if credits.get("crew"):
            for crew in credits["crew"]:
                if crew.get("job") == "Director":
                    movie.director = crew["name"]
                    break

        # Extract trailer URL
        videos = data.get("videos", {}).get("results", [])
        for video in videos:
            if video.get("type") == "Trailer" and video.get("site") == "YouTube":
                movie.trailer_url = f"https://www.youtube.com/watch?v={video['key']}"
                break

        return movie

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

    def fetch_upcoming(self, region: str = "IN", pages: int = 3) -> List[Movie]:
        """Fetch upcoming movies from TMDB."""
        if not self.is_available:
            return []

        movies = []
        seen_ids = set()

        for page in range(1, pages + 1):
            try:
                response = self.get(
                    f"{self.BASE_URL}/movie/upcoming",
                    params={
                        "api_key": self.api_key,
                        "language": "en-US",
                        "region": region,
                        "page": page,
                    }
                )
                data = response.json()
                results = data.get("results", [])

                for item in results:
                    tmdb_id = item.get("id")
                    if tmdb_id in seen_ids:
                        continue
                    seen_ids.add(tmdb_id)

                    release_date = item.get("release_date", "")
                    # Skip if no release date or already released
                    if not release_date:
                        continue

                    # Parse year from release date
                    year = None
                    if release_date and len(release_date) >= 4:
                        try:
                            year = int(release_date[:4])
                        except ValueError:
                            pass

                    # Get genre names from genre_ids
                    genres = self._get_genre_names(item.get("genre_ids", []))

                    movie = Movie(
                        title=item.get("title", "Unknown"),
                        year=year,
                        tmdb_id=tmdb_id,
                        synopsis=item.get("overview", ""),
                        rating=item.get("vote_average"),
                        vote_count=item.get("vote_count"),
                        popularity=item.get("popularity"),
                        release_date=release_date,
                        genres=genres,
                        original_language=item.get("original_language"),
                    )

                    # Add poster
                    if item.get("poster_path"):
                        movie.poster_url = f"{self.IMAGE_BASE_URL}/w342{item['poster_path']}"
                        movie.tmdb_poster_url = f"{self.IMAGE_BASE_URL}/w780{item['poster_path']}"

                    # Add backdrop
                    if item.get("backdrop_path"):
                        movie.backdrop_url = f"{self.IMAGE_BASE_URL}/w1280{item['backdrop_path']}"

                    movies.append(movie)

                print(f"Fetched {len(results)} upcoming movies from page {page}")

            except Exception as e:
                print(f"TMDB upcoming fetch error (page {page}): {e}")

        # Sort by release date
        movies.sort(key=lambda m: m.release_date or "9999-99-99")
        print(f"Fetched {len(movies)} upcoming movies total")
        return movies

    def _get_genre_names(self, genre_ids: List[int]) -> List[str]:
        """Convert TMDB genre IDs to names."""
        genre_map = {
            28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy",
            80: "Crime", 99: "Documentary", 18: "Drama", 10751: "Family",
            14: "Fantasy", 36: "History", 27: "Horror", 10402: "Music",
            9648: "Mystery", 10749: "Romance", 878: "Sci-Fi", 10770: "TV Movie",
            53: "Thriller", 10752: "War", 37: "Western",
        }
        return [genre_map.get(gid, "") for gid in genre_ids if gid in genre_map]

    def fetch_movies(self, limit: Optional[int] = None) -> List[Movie]:
        """Not used - TMDB is for enrichment only."""
        return []

    def search(self, query: str) -> List[Movie]:
        """Not used - TMDB is for enrichment only."""
        return []
