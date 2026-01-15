from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime, date

from dataclasses_json import dataclass_json

from utils.slug import generate_movie_slug
from models.offer import StreamingAvailability, StreamingOffer


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
    release_date: Optional[str] = None  # ISO format: YYYY-MM-DD

    # Structured streaming offers
    streaming: StreamingAvailability = field(default_factory=StreamingAvailability)

    @property
    def slug(self) -> str:
        """Generate URL slug for this movie."""
        return generate_movie_slug(self.title, self.year)

    @property
    def canonical_url(self) -> str:
        """Get the canonical URL path for this movie."""
        return f"/movie/{self.slug}"

    @property
    def is_free(self) -> bool:
        """Check if movie is available for free."""
        return self.streaming.is_free

    @property
    def has_subscription(self) -> bool:
        """Check if movie is available via subscription."""
        return self.streaming.is_subscription

    @property
    def is_rentable(self) -> bool:
        """Check if movie is available to rent."""
        return self.streaming.is_rentable

    @property
    def is_buyable(self) -> bool:
        """Check if movie is available to buy."""
        return self.streaming.is_buyable

    @property
    def best_poster_url(self) -> Optional[str]:
        """Return highest quality poster available."""
        return self.tmdb_poster_url or self.poster_url

    def merge_with(self, other: "Movie") -> "Movie":
        """Merge another movie's data into this one (for deduplication)."""
        # Merge streaming offers
        merged_streaming = StreamingAvailability(
            free_offers=list({o.provider_name: o for o in
                             self.streaming.free_offers + other.streaming.free_offers}.values()),
            subscription_offers=list({o.provider_name: o for o in
                                      self.streaming.subscription_offers + other.streaming.subscription_offers}.values()),
            rent_offers=list({o.provider_name: o for o in
                             self.streaming.rent_offers + other.streaming.rent_offers}.values()),
            buy_offers=list({o.provider_name: o for o in
                            self.streaming.buy_offers + other.streaming.buy_offers}.values()),
        )

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
            tmdb_id=self.tmdb_id or other.tmdb_id,
            imdb_id=self.imdb_id or other.imdb_id,
            justwatch_id=self.justwatch_id or other.justwatch_id,
            backdrop_url=self.backdrop_url or other.backdrop_url,
            tmdb_poster_url=self.tmdb_poster_url or other.tmdb_poster_url,
            tagline=self.tagline or other.tagline,
            original_language=self.original_language or other.original_language,
            popularity=self.popularity or other.popularity,
            vote_count=self.vote_count or other.vote_count,
            release_date=self.release_date or other.release_date,
            streaming=merged_streaming,
        )

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
            "director": self.director,
            "runtime_minutes": self.runtime_minutes,
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
            "release_date": self.release_date,
            "streaming": self.streaming.to_document(),
            # Denormalized fields for efficient queries
            "streaming_providers": list(set(self.streaming_services + self.streaming.all_providers)),
            "availability_types": self._get_availability_types(),
            "has_free": self.is_free,
            "has_subscription": self.has_subscription,
            "is_rentable": self.is_rentable,
            "is_buyable": self.is_buyable,
            "min_rent_price": self.streaming.min_rent_price,
            "min_buy_price": self.streaming.min_buy_price,
            "updated_at": datetime.utcnow(),
        }

    def _get_availability_types(self) -> List[str]:
        """Get list of availability types for this movie."""
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
    def from_document(cls, doc: Dict[str, Any]) -> "Movie":
        """Create Movie instance from MongoDB document."""
        if not doc:
            return None
        return cls(
            title=doc.get("title", ""),
            year=doc.get("year"),
            genres=doc.get("genres", []),
            rating=doc.get("rating"),
            synopsis=doc.get("synopsis", ""),
            cast=doc.get("cast", []),
            director=doc.get("director"),
            runtime_minutes=doc.get("runtime_minutes"),
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
            release_date=doc.get("release_date"),
            streaming=StreamingAvailability.from_document(doc.get("streaming", {})),
        )
