"""Movie shortlisting utilities for language-based and regional filtering."""

from typing import List, Dict, Optional, Set
from dataclasses import dataclass, field

# ISO 639-1 Language codes
LANGUAGE_CODES = {
    # South Indian Languages
    "ta": "Tamil",
    "te": "Telugu",
    "ml": "Malayalam",
    "kn": "Kannada",

    # North Indian / Bollywood
    "hi": "Hindi",
    "bn": "Bengali",
    "mr": "Marathi",
    "pa": "Punjabi",
    "gu": "Gujarati",

    # International
    "ko": "Korean",
    "ja": "Japanese",
    "fr": "French",
    "es": "Spanish",
    "de": "German",
    "it": "Italian",
    "zh": "Chinese",
    "pt": "Portuguese",
    "ru": "Russian",
    "th": "Thai",
    "tl": "Tagalog",
    "id": "Indonesian",

    # English
    "en": "English",
}

# Regional groupings
SOUTH_INDIAN_LANGUAGES = {"ta", "te", "ml", "kn"}
INDIAN_LANGUAGES = {"ta", "te", "ml", "kn", "hi", "bn", "mr", "pa", "gu"}
EAST_ASIAN_LANGUAGES = {"ko", "ja", "zh", "th"}
EUROPEAN_LANGUAGES = {"fr", "es", "de", "it", "pt", "ru"}


@dataclass
class ShortlistCriteria:
    """Criteria for shortlisting movies."""

    # Language filters
    languages: Optional[List[str]] = None
    exclude_languages: Optional[List[str]] = None

    # Genre filters (use short codes: act, cmy, drm, trl, etc.)
    genres: Optional[List[str]] = None
    exclude_genres: Optional[List[str]] = None
    require_all_genres: bool = False

    # Rating filters
    min_rating: Optional[float] = None
    max_rating: Optional[float] = None
    min_vote_count: Optional[int] = None

    # Pagination
    limit: int = 20

    # Sort options: rating, popularity, year, title
    sort_by: str = "rating"

    def to_query_params(self) -> Dict:
        """Convert criteria to query parameters dict."""
        params = {}
        if self.languages:
            params["languages"] = self.languages
        if self.exclude_languages:
            params["exclude_languages"] = self.exclude_languages
        if self.genres:
            params["genres"] = self.genres
        if self.exclude_genres:
            params["exclude_genres"] = self.exclude_genres
        if self.require_all_genres:
            params["require_all_genres"] = self.require_all_genres
        if self.min_rating is not None:
            params["min_rating"] = self.min_rating
        if self.max_rating is not None:
            params["max_rating"] = self.max_rating
        if self.min_vote_count is not None:
            params["min_vote_count"] = self.min_vote_count
        params["limit"] = self.limit
        params["sort_by"] = self.sort_by
        return params


def get_language_name(code: str) -> str:
    """Get human-readable language name from ISO code."""
    return LANGUAGE_CODES.get(code, code.upper())


def is_south_indian(language_code: str) -> bool:
    """Check if language code is South Indian."""
    return language_code in SOUTH_INDIAN_LANGUAGES


def is_indian(language_code: str) -> bool:
    """Check if language code is any Indian language."""
    return language_code in INDIAN_LANGUAGES


def get_regional_languages(region: str) -> Set[str]:
    """Get language codes for a region."""
    regions = {
        "south_indian": SOUTH_INDIAN_LANGUAGES,
        "indian": INDIAN_LANGUAGES,
        "east_asian": EAST_ASIAN_LANGUAGES,
        "european": EUROPEAN_LANGUAGES,
    }
    return regions.get(region, set())
