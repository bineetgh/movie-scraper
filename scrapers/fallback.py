from typing import Dict, List, Optional

from models.movie import Movie
from scrapers.base import BaseScraper


class InternetArchiveScraper(BaseScraper):
    """Scraper for Internet Archive's free movie collection."""

    BASE_URL = "https://archive.org"
    SEARCH_URL = f"{BASE_URL}/advancedsearch.php"

    # Feature films collection on Internet Archive
    COLLECTION = "feature_films"

    def _parse_item(self, item: Dict) -> Movie:
        """Parse an Internet Archive item into a Movie."""
        identifier = item.get("identifier", "")
        watch_url = f"{self.BASE_URL}/details/{identifier}"

        # Parse year from date if available
        year = None
        date = item.get("date") or item.get("year")
        if date:
            try:
                year = int(str(date)[:4])
            except (ValueError, TypeError):
                pass

        return Movie(
            title=item.get("title", ""),
            year=year,
            genres=[],
            rating=None,
            synopsis=item.get("description", "") or "",
            cast=[],
            director=item.get("creator"),
            runtime_minutes=None,
            poster_url=f"{self.BASE_URL}/services/img/{identifier}" if identifier else None,
            trailer_url=None,
            streaming_services=["Internet Archive"],
            source_urls=[watch_url],
        )

    def fetch_movies(self, limit: Optional[int] = 100) -> List[Movie]:
        """Fetch free movies from Internet Archive's feature films collection."""
        movies = []
        rows = limit or 100
        page = 1
        page_size = min(rows, 100)

        print(f"Fetching movies from Internet Archive...")

        while len(movies) < rows:
            params = {
                "q": f"collection:{self.COLLECTION} AND mediatype:movies",
                "fl[]": ["identifier", "title", "description", "date", "year", "creator"],
                "sort[]": "downloads desc",
                "rows": page_size,
                "page": page,
                "output": "json",
            }

            try:
                response = self.get(self.SEARCH_URL, params=params)
                data = response.json()
                docs = data.get("response", {}).get("docs", [])

                if not docs:
                    break

                for item in docs:
                    movie = self._parse_item(item)
                    if movie.title:
                        movies.append(movie)

                    if len(movies) >= rows:
                        break

                page += 1
                print(f"Fetched {len(movies)} movies from Internet Archive...")

            except Exception as e:
                print(f"Error fetching from Internet Archive: {e}")
                break

        print(f"Fetched {len(movies)} movies from Internet Archive total")
        return movies

    def search(self, query: str) -> List[Movie]:
        """Search for movies by title in Internet Archive."""
        params = {
            "q": f'collection:{self.COLLECTION} AND mediatype:movies AND title:"{query}"',
            "fl[]": ["identifier", "title", "description", "date", "year", "creator"],
            "sort[]": "downloads desc",
            "rows": 20,
            "output": "json",
        }

        try:
            response = self.get(self.SEARCH_URL, params=params)
            data = response.json()
            docs = data.get("response", {}).get("docs", [])

            return [self._parse_item(item) for item in docs if item.get("title")]

        except Exception as e:
            print(f"Error searching Internet Archive: {e}")
            return []
