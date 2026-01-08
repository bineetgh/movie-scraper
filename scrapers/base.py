import time
from abc import ABC, abstractmethod
from typing import List, Optional

import requests

from models.movie import Movie


class BaseScraper(ABC):
    """Base class for all movie scrapers."""

    RATE_LIMIT_SECONDS = 1.0
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    MAX_RETRIES = 3

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.USER_AGENT})
        self._last_request_time = 0.0

    def _rate_limit(self):
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.RATE_LIMIT_SECONDS:
            time.sleep(self.RATE_LIMIT_SECONDS - elapsed)
        self._last_request_time = time.time()

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Make a rate-limited request with retries."""
        self._rate_limit()

        for attempt in range(self.MAX_RETRIES):
            try:
                response = self.session.request(method, url, timeout=30, **kwargs)
                response.raise_for_status()
                return response
            except requests.RequestException as e:
                if attempt == self.MAX_RETRIES - 1:
                    raise
                print(f"Request failed (attempt {attempt + 1}): {e}")
                time.sleep(2 ** attempt)

        raise RuntimeError("Max retries exceeded")

    def get(self, url: str, **kwargs) -> requests.Response:
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> requests.Response:
        return self._request("POST", url, **kwargs)

    @abstractmethod
    def fetch_movies(self, limit: Optional[int] = None) -> List[Movie]:
        """Fetch movies from this source. Override in subclasses."""
        pass

    @abstractmethod
    def search(self, query: str) -> List[Movie]:
        """Search for movies by title. Override in subclasses."""
        pass
