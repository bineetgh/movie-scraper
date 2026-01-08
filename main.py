#!/usr/bin/env python3
"""
Movie Scraper - Find free movies available to watch in India.

Usage:
    python main.py                    # Fetch all free movies
    python main.py --limit 50         # Limit to 50 movies
    python main.py --search "Inception"  # Search for a specific movie
    python main.py --include-archive  # Include Internet Archive results
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

from models.movie import Movie
from scrapers.justwatch import JustWatchScraper
from scrapers.fallback import InternetArchiveScraper


def deduplicate_movies(movies: List[Movie]) -> List[Movie]:
    """Deduplicate movies by title and year, merging data."""
    seen: Dict[str, Movie] = {}

    for movie in movies:
        # Create a key from normalized title + year
        key = f"{movie.title.lower().strip()}_{movie.year or 'unknown'}"

        if key in seen:
            seen[key] = seen[key].merge_with(movie)
        else:
            seen[key] = movie

    return list(seen.values())


def fetch_all_movies(limit: Optional[int] = None, include_archive: bool = False) -> List[Movie]:
    """Fetch free movies from all sources."""
    all_movies = []

    # Primary source: JustWatch India
    justwatch = JustWatchScraper()
    jw_movies = justwatch.fetch_movies(limit=limit)
    all_movies.extend(jw_movies)
    print(f"Found {len(jw_movies)} free movies on JustWatch India")

    # Optional: Internet Archive (public domain movies)
    if include_archive:
        archive = InternetArchiveScraper()
        archive_limit = max(50, (limit or 100) // 2)
        ia_movies = archive.fetch_movies(limit=archive_limit)
        all_movies.extend(ia_movies)
        print(f"Found {len(ia_movies)} movies on Internet Archive")

    # Deduplicate
    unique_movies = deduplicate_movies(all_movies)
    print(f"Total unique movies after deduplication: {len(unique_movies)}")

    return unique_movies


def search_movies(query: str, include_archive: bool = False) -> List[Movie]:
    """Search for a specific movie across sources."""
    all_results = []

    # Search JustWatch
    justwatch = JustWatchScraper()
    jw_results = justwatch.search(query)
    all_results.extend(jw_results)

    # Optionally search Internet Archive
    if include_archive:
        archive = InternetArchiveScraper()
        ia_results = archive.search(query)
        all_results.extend(ia_results)

    return deduplicate_movies(all_results)


def save_to_json(movies: List[Movie], output_path: Path):
    """Save movies to a JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    data = [movie.to_dict() for movie in movies]

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(movies)} movies to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Find free movies available to watch in India"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of movies to fetch (default: 100)",
    )
    parser.add_argument(
        "--search",
        type=str,
        help="Search for a specific movie by title",
    )
    parser.add_argument(
        "--include-archive",
        action="store_true",
        help="Include Internet Archive (public domain) movies",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="output/movies.json",
        help="Output file path (default: output/movies.json)",
    )

    args = parser.parse_args()
    output_path = Path(args.output)

    try:
        if args.search:
            print(f"Searching for: {args.search}")
            movies = search_movies(args.search, include_archive=args.include_archive)
            if not movies:
                print("No free movies found matching your search.")
                sys.exit(0)
        else:
            movies = fetch_all_movies(
                limit=args.limit,
                include_archive=args.include_archive,
            )

        if movies:
            save_to_json(movies, output_path)

            # Print summary
            print("\n--- Summary ---")
            print(f"Total movies: {len(movies)}")
            services = set()
            for m in movies:
                services.update(m.streaming_services)
            print(f"Streaming services: {', '.join(sorted(services))}")
        else:
            print("No free movies found.")

    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
