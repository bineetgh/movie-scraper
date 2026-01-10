"""URL slug generation utilities for SEO-friendly movie URLs."""

from slugify import slugify
from typing import Optional, Tuple, Union


def generate_movie_slug(title: Union[str, list], year: Optional[int] = None) -> str:
    """
    Generate a URL-friendly slug for a movie.

    Examples:
        "The Dark Knight" (2008) -> "the-dark-knight-2008"
        "Inception" (2010) -> "inception-2010"
        "Movie Title" (None) -> "movie-title"
    """
    # Handle case where title is accidentally a list
    if isinstance(title, list):
        title = title[0] if title else ""
    
    # Ensure title is a string
    if not isinstance(title, str):
        title = str(title) if title else ""
    
    base_slug = slugify(title, lowercase=True, max_length=50)
    if year:
        return f"{base_slug}-{year}"
    return base_slug


def parse_movie_slug(slug: str) -> Tuple[str, Optional[int]]:
    """
    Parse a slug to extract potential year.

    Returns:
        Tuple of (slug_without_year, year_or_none)

    Examples:
        "the-dark-knight-2008" -> ("the-dark-knight", 2008)
        "inception-2010" -> ("inception", 2010)
        "movie-title" -> ("movie-title", None)
    """
    parts = slug.rsplit('-', 1)
    if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) == 4:
        year = int(parts[1])
        # Sanity check: year should be reasonable (1880-2100)
        if 1880 <= year <= 2100:
            return parts[0], year
    return slug, None
