from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime

from dataclasses_json import dataclass_json

from utils.slug import generate_movie_slug
from models.offer import StreamingAvailability, StreamingOffer


@dataclass_json
@dataclass
class TVShow:
    """Represents a TV show with streaming availability."""

    title: str
    year: Optional[int] = None  # First air year
    genres: List[str] = field(default_factory=list)
    rating: Optional[float] = None
    synopsis: str = ""
    cast: List[str] = field(default_factory=list)
    creator: Optional[str] = None
    seasons_count: Optional[int] = None
    episodes_count: Optional[int] = None
    poster_url: Optional[str] = None
    trailer_url: Optional[str] = None
    streaming_services: List[str] = field(default_factory=list)
    source_urls: List[str] = field(default_factory=list)

    # External IDs
    tmdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    justwatch_id: Optional[str] = None

    # TMDB high-quality images
    backdrop_url: Optional[str] = None
    tmdb_poster_url: Optional[str] = None

    # Additional metadata
    tagline: Optional[str] = None
    original_language: Optional[str] = None
    popularity: Optional[float] = None
    vote_count: Optional[int] = None
    first_air_date: Optional[str] = None  # ISO format: YYYY-MM-DD
    last_air_date: Optional[str] = None
    status: Optional[str] = None  # Returning Series, Ended, Canceled, etc.
    episode_runtime: Optional[int] = None  # Average episode runtime in minutes

    # Structured streaming offers
    streaming: StreamingAvailability = field(default_factory=StreamingAvailability)

    @property
    def slug(self) -> str:
        """Generate URL slug for this TV show."""
        return generate_movie_slug(self.title, self.year)

    @property
    def canonical_url(self) -> str:
        """Get the canonical URL path for this TV show."""
        return f"/tv/{self.slug}"

    @property
    def is_free(self) -> bool:
        """Check if show is available for free."""
        return self.streaming.is_free

    @property
    def has_subscription(self) -> bool:
        """Check if show is available via subscription."""
        return self.streaming.is_subscription

    @property
    def is_rentable(self) -> bool:
        """Check if show is available to rent."""
        return self.streaming.is_rentable

    @property
    def is_buyable(self) -> bool:
        """Check if show is available to buy."""
        return self.streaming.is_buyable

    @property
    def best_poster_url(self) -> Optional[str]:
        """Return highest quality poster available."""
        return self.tmdb_poster_url or self.poster_url

    @property
    def seasons_display(self) -> str:
        """Human-readable seasons count."""
        if self.seasons_count:
            return f"{self.seasons_count} season{'s' if self.seasons_count != 1 else ''}"
        return ""

    def to_document(self) -> Dict[str, Any]:
        """Convert to MongoDB document with denormalized fields for queries."""
        return {
            "_id": self.slug,
            "title": self.title,
            "year": self.year,
            "slug": self.slug,
            "genres": self.genres,
            "rating": self.rating,
            "synopsis": self.synopsis,
            "cast": self.cast,
            "creator": self.creator,
            "seasons_count": self.seasons_count,
            "episodes_count": self.episodes_count,
            "poster_url": self.poster_url,
            "trailer_url": self.trailer_url,
            "streaming_services": self.streaming_services,
            "source_urls": self.source_urls,
            "tmdb_id": self.tmdb_id,
            "imdb_id": self.imdb_id,
            "justwatch_id": self.justwatch_id,
            "backdrop_url": self.backdrop_url,
            "tmdb_poster_url": self.tmdb_poster_url,
            "tagline": self.tagline,
            "original_language": self.original_language,
            "popularity": self.popularity,
            "vote_count": self.vote_count,
            "first_air_date": self.first_air_date,
            "last_air_date": self.last_air_date,
            "status": self.status,
            "episode_runtime": self.episode_runtime,
            "streaming": self.streaming.to_document(),
            # Denormalized fields for efficient queries
            "streaming_providers": list(set(self.streaming_services + self.streaming.all_providers)),
            "availability_types": self._get_availability_types(),
            "has_free": self.is_free,
            "has_subscription": self.has_subscription,
            "is_rentable": self.is_rentable,
            "is_buyable": self.is_buyable,
            "content_type": "tvshow",
            "updated_at": datetime.utcnow(),
        }

    def _get_availability_types(self) -> List[str]:
        """Get list of availability types for this show."""
        types = []
        if self.is_free:
            types.append("free")
        if self.has_subscription:
            types.append("subscription")
        if self.is_rentable:
            types.append("rent")
        if self.is_buyable:
            types.append("buy")
        return types

    @classmethod
    def from_document(cls, doc: Dict[str, Any]) -> "TVShow":
        """Create TVShow instance from MongoDB document."""
        if not doc:
            return None
        return cls(
            title=doc.get("title", ""),
            year=doc.get("year"),
            genres=doc.get("genres", []),
            rating=doc.get("rating"),
            synopsis=doc.get("synopsis", ""),
            cast=doc.get("cast", []),
            creator=doc.get("creator"),
            seasons_count=doc.get("seasons_count"),
            episodes_count=doc.get("episodes_count"),
            poster_url=doc.get("poster_url"),
            trailer_url=doc.get("trailer_url"),
            streaming_services=doc.get("streaming_services", []),
            source_urls=doc.get("source_urls", []),
            tmdb_id=doc.get("tmdb_id"),
            imdb_id=doc.get("imdb_id"),
            justwatch_id=doc.get("justwatch_id"),
            backdrop_url=doc.get("backdrop_url"),
            tmdb_poster_url=doc.get("tmdb_poster_url"),
            tagline=doc.get("tagline"),
            original_language=doc.get("original_language"),
            popularity=doc.get("popularity"),
            vote_count=doc.get("vote_count"),
            first_air_date=doc.get("first_air_date"),
            last_air_date=doc.get("last_air_date"),
            status=doc.get("status"),
            episode_runtime=doc.get("episode_runtime"),
            streaming=StreamingAvailability.from_document(doc.get("streaming", {})),
        )
