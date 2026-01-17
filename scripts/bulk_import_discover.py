#!/usr/bin/env python3
"""
Bulk import movies from TMDB Discover API with JustWatch streaming data.

Usage:
    python scripts/bulk_import_discover.py --count 100
    python scripts/bulk_import_discover.py --count 5000
    python scripts/bulk_import_discover.py --count 5000 --skip-justwatch
    python scripts/bulk_import_discover.py --resume

Examples:
    # Test with small batch
    python scripts/bulk_import_discover.py --count 50 --dry-run

    # Import 5000 popular movies with streaming data
    python scripts/bulk_import_discover.py --count 5000

    # Fast import without streaming data
    python scripts/bulk_import_discover.py --count 5000 --skip-justwatch

    # Import top-rated movies only
    python scripts/bulk_import_discover.py --count 1000 --sort vote_average.desc
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent.parent / ".env")

from models.movie import Movie
from scrapers.tmdb import TMDBClient
from scrapers.justwatch import JustWatchScraper
from db.mongodb import get_database, close_connection, init_indexes
from db.movie_repository import MovieRepository


# Checkpoint file for resumability
CHECKPOINT_FILE = Path(__file__).parent.parent / "cache" / "discover_checkpoint.json"
BATCH_SIZE = 100  # Movies per DB insert batch


class BulkImporter:
    """Handles bulk import with progress tracking and resumability."""

    def __init__(self, skip_justwatch: bool = False, dry_run: bool = False):
        self.tmdb = TMDBClient()
        self.justwatch = JustWatchScraper() if not skip_justwatch else None
        self.skip_justwatch = skip_justwatch
        self.dry_run = dry_run

        # Stats tracking
        self.stats = {
            "fetched": 0,
            "enriched": 0,
            "inserted": 0,
            "skipped": 0,
            "failed": 0,
            "start_time": None,
        }

    def load_checkpoint(self) -> Optional[Dict]:
        """Load checkpoint from file if exists."""
        if CHECKPOINT_FILE.exists():
            try:
                with open(CHECKPOINT_FILE, "r") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Warning: Could not load checkpoint: {e}")
        return None

    def save_checkpoint(self, page: int, total_fetched: int, last_tmdb_id: Optional[int]):
        """Save checkpoint for resumability."""
        checkpoint = {
            "page": page,
            "total_fetched": total_fetched,
            "last_tmdb_id": last_tmdb_id,
            "timestamp": datetime.utcnow().isoformat(),
            "stats": self.stats,
        }
        try:
            CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(CHECKPOINT_FILE, "w") as f:
                json.dump(checkpoint, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save checkpoint: {e}")

    def clear_checkpoint(self):
        """Clear checkpoint file after successful completion."""
        if CHECKPOINT_FILE.exists():
            try:
                CHECKPOINT_FILE.unlink()
            except Exception:
                pass

    def print_progress(self):
        """Print current progress stats."""
        elapsed = time.time() - self.stats["start_time"] if self.stats["start_time"] else 0
        rate = self.stats["fetched"] / elapsed if elapsed > 0 else 0

        print(f"\n--- Progress ---")
        print(f"Fetched: {self.stats['fetched']}")
        print(f"Enriched with JustWatch: {self.stats['enriched']}")
        print(f"Inserted: {self.stats['inserted']}")
        print(f"Skipped (existing): {self.stats['skipped']}")
        print(f"Failed: {self.stats['failed']}")
        print(f"Elapsed: {elapsed:.1f}s ({rate:.1f} movies/s)")
        print("-" * 20)

    async def import_movies(
        self,
        total_count: int = 5000,
        sort_by: str = "popularity.desc",
        vote_count_gte: int = 100,
        release_date_gte: Optional[str] = None,
        release_date_lte: Optional[str] = None,
        language: Optional[str] = None,
        resume: bool = False,
    ) -> tuple:
        """
        Import movies from TMDB Discover with optional JustWatch enrichment.

        Returns:
            Tuple of (inserted_count, skipped_count, failed_count)
        """
        self.stats["start_time"] = time.time()

        # Check TMDB availability
        if not self.tmdb.is_available:
            print("Error: TMDB API key not configured.")
            print("Set TMDB_API_KEY in your .env file.")
            return 0, 0, 0

        # Connect to MongoDB
        print("\nConnecting to MongoDB...")
        db = await get_database()
        if db is None:
            print("Error: Failed to connect to MongoDB.")
            return 0, 0, 0

        print("Connected to MongoDB successfully.")
        await init_indexes(db)
        repo = MovieRepository(db)

        # Check for resume
        start_page = 1
        if resume:
            checkpoint = self.load_checkpoint()
            if checkpoint:
                start_page = checkpoint.get("page", 1) + 1
                self.stats = checkpoint.get("stats", self.stats)
                print(f"Resuming from page {start_page} ({self.stats['fetched']} already fetched)")

        print(f"\nStarting TMDB Discover import:")
        print(f"  Target: {total_count} movies")
        print(f"  Sort: {sort_by}")
        print(f"  Min votes: {vote_count_gte}")
        print(f"  JustWatch enrichment: {'Disabled' if self.skip_justwatch else 'Enabled'}")
        print(f"  Dry run: {self.dry_run}")
        print()

        batch_buffer: List[Movie] = []
        page = start_page

        try:
            for batch in self.tmdb.fetch_discover(
                total_movies=total_count,
                sort_by=sort_by,
                vote_count_gte=vote_count_gte,
                release_date_gte=release_date_gte,
                release_date_lte=release_date_lte,
                with_original_language=language,
            ):
                for movie in batch:
                    self.stats["fetched"] += 1

                    # Enrich with JustWatch streaming data
                    if self.justwatch:
                        try:
                            jw_movie = self.justwatch.search_and_match(
                                title=movie.title,
                                year=movie.year,
                                tmdb_id=movie.tmdb_id,
                            )
                            if jw_movie:
                                # Merge streaming data from JustWatch into TMDB movie
                                movie.streaming = jw_movie.streaming
                                movie.streaming_services = jw_movie.streaming_services
                                movie.source_urls = jw_movie.source_urls
                                movie.justwatch_id = jw_movie.justwatch_id
                                if not movie.imdb_id and jw_movie.imdb_id:
                                    movie.imdb_id = jw_movie.imdb_id
                                self.stats["enriched"] += 1
                        except Exception as e:
                            print(f"JustWatch enrichment failed for '{movie.title}': {e}")

                    batch_buffer.append(movie)

                    # Insert batch when buffer is full
                    if len(batch_buffer) >= BATCH_SIZE:
                        if not self.dry_run:
                            inserted, skipped = await repo.insert_new_movies_only(batch_buffer)
                            self.stats["inserted"] += inserted
                            self.stats["skipped"] += skipped
                        else:
                            print(f"[DRY RUN] Would insert {len(batch_buffer)} movies")
                            self.stats["inserted"] += len(batch_buffer)

                        batch_buffer.clear()
                        self.save_checkpoint(page, self.stats["fetched"], movie.tmdb_id)

                        # Print progress every batch
                        self.print_progress()

                page += 1

            # Insert remaining movies
            if batch_buffer:
                if not self.dry_run:
                    inserted, skipped = await repo.insert_new_movies_only(batch_buffer)
                    self.stats["inserted"] += inserted
                    self.stats["skipped"] += skipped
                else:
                    print(f"[DRY RUN] Would insert {len(batch_buffer)} movies")
                    self.stats["inserted"] += len(batch_buffer)

            # Clear checkpoint on success
            self.clear_checkpoint()

        except KeyboardInterrupt:
            print("\n\nInterrupted! Saving checkpoint...")
            self.save_checkpoint(page, self.stats["fetched"], None)
            print("You can resume later with --resume flag")

        except Exception as e:
            print(f"\nError during import: {e}")
            self.save_checkpoint(page, self.stats["fetched"], None)
            self.stats["failed"] += 1

        finally:
            await close_connection()

        # Print final stats
        print("\n" + "=" * 50)
        print("IMPORT COMPLETE")
        print("=" * 50)
        self.print_progress()

        return self.stats["inserted"], self.stats["skipped"], self.stats["failed"]


def main():
    parser = argparse.ArgumentParser(
        description="Bulk import movies from TMDB Discover API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--count", type=int, default=5000,
        help="Number of movies to import (default: 5000, max: 10000)"
    )
    parser.add_argument(
        "--sort", type=str, default="popularity.desc",
        choices=["popularity.desc", "vote_average.desc", "release_date.desc", "revenue.desc"],
        help="Sort order (default: popularity.desc)"
    )
    parser.add_argument(
        "--vote-count", type=int, default=100,
        help="Minimum vote count filter (default: 100)"
    )
    parser.add_argument(
        "--year-from", type=str,
        help="Release date start filter (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--year-to", type=str,
        help="Release date end filter (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--language", type=str,
        help="Original language filter (e.g., 'en', 'hi')"
    )
    parser.add_argument(
        "--skip-justwatch", action="store_true",
        help="Skip JustWatch streaming enrichment (faster, no streaming data)"
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Resume from last checkpoint"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch and process without inserting to DB"
    )

    args = parser.parse_args()

    # Validate count
    if args.count < 1 or args.count > 10000:
        print("Error: --count must be between 1 and 10000")
        sys.exit(1)

    print("=" * 50)
    print("TMDB Discover Bulk Import")
    print("=" * 50)

    # Check for required environment variables
    if not os.getenv("TMDB_API_KEY"):
        print("\nError: TMDB_API_KEY environment variable not set.")
        sys.exit(1)

    if not os.getenv("MONGODB_URI"):
        print("\nError: MONGODB_URI environment variable not set.")
        sys.exit(1)

    # Run import
    importer = BulkImporter(
        skip_justwatch=args.skip_justwatch,
        dry_run=args.dry_run,
    )

    inserted, skipped, failed = asyncio.run(importer.import_movies(
        total_count=args.count,
        sort_by=args.sort,
        vote_count_gte=args.vote_count,
        release_date_gte=args.year_from,
        release_date_lte=args.year_to,
        language=args.language,
        resume=args.resume,
    ))

    print(f"\nFinal: {inserted} inserted, {skipped} skipped, {failed} failed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
