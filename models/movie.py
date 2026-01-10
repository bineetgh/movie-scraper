from dataclasses import dataclass, field
from typing import List, Optional

from dataclasses_json import dataclass_json

from utils.slug import generate_movie_slug


@dataclass_json
@dataclass
class Movie:
    title: str
    year: Optional[int] = None
    genres: List[str] = field(default_factory=list)
    rating: Optional[float] = None
    synopsis: str = ""
    cast: List[str] = field(default_factory=list)
    director: Optional[str] = None
    runtime_minutes: Optional[int] = None
    poster_url: Optional[str] = None
    trailer_url: Optional[str] = None
    streaming_services: List[str] = field(default_factory=list)
    source_urls: List[str] = field(default_factory=list)

    @property
    def slug(self) -> str:
        """Generate URL slug for this movie."""
        return generate_movie_slug(self.title, self.year)

    @property
    def canonical_url(self) -> str:
        """Get the canonical URL path for this movie."""
        return f"/movie/{self.slug}"

    def merge_with(self, other: "Movie") -> "Movie":
        """Merge another movie's data into this one (for deduplication)."""
        return Movie(
            title=self.title,
            year=self.year or other.year,
            genres=list(set(self.genres + other.genres)),
            rating=self.rating or other.rating,
            synopsis=self.synopsis or other.synopsis,
            cast=list(set(self.cast + other.cast)),
            director=self.director or other.director,
            runtime_minutes=self.runtime_minutes or other.runtime_minutes,
            poster_url=self.poster_url or other.poster_url,
            trailer_url=self.trailer_url or other.trailer_url,
            streaming_services=list(set(self.streaming_services + other.streaming_services)),
            source_urls=list(set(self.source_urls + other.source_urls)),
        )
