#!/usr/bin/env python3
"""
Migration script to import existing JSON cache data into MongoDB.

Usage:
    python scripts/migrate_to_mongodb.py

Requirements:
    - MONGODB_URI environment variable must be set
    - cache/movies.json must exist with movie data
"""

import asyncio
import json
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent.parent / ".env")

from models.movie import Movie
from db.mongodb import get_database, close_connection, init_indexes
from db.movie_repository import MovieRepository


async def migrate():
    """Migrate movies from JSON cache to MongoDB."""
    cache_file = Path(__file__).parent.parent / "cache" / "movies.json"

    # Check if cache file exists
    if not cache_file.exists():
        print(f"Error: Cache file not found at {cache_file}")
        print("Run the scraper first to populate the cache.")
        return False

    # Load movies from JSON
    print(f"Loading movies from {cache_file}...")
    with open(cache_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    movies_data = data.get("movies", [])
    if not movies_data:
        print("Error: No movies found in cache file.")
        return False

    print(f"Found {len(movies_data)} movies in cache.")

    # Convert to Movie objects
    movies = []
    for movie_dict in movies_data:
        try:
            movie = Movie.from_dict(movie_dict)
            movies.append(movie)
        except Exception as e:
            print(f"Warning: Failed to parse movie: {e}")
            continue

    print(f"Successfully parsed {len(movies)} movies.")

    # Connect to MongoDB
    print("\nConnecting to MongoDB...")
    db = await get_database()
    if db is None:
        print("Error: Failed to connect to MongoDB.")
        print("Make sure MONGODB_URI is set in your .env file.")
        return False

    print("Connected to MongoDB successfully.")

    # Create indexes
    print("\nCreating indexes...")
    await init_indexes(db)
    print("Indexes created.")

    # Insert movies
    print(f"\nMigrating {len(movies)} movies to MongoDB...")
    repo = MovieRepository(db)

    count = await repo.upsert_movies(movies)
    await repo.set_last_refresh()

    print(f"\nMigration complete!")
    print(f"  - Inserted/updated: {count} movies")

    # Verify
    total = await repo.get_total_count()
    print(f"  - Total in database: {total} movies")

    # Close connection
    await close_connection()
    return True


def main():
    """Entry point for migration script."""
    print("=" * 50)
    print("MongoDB Migration Script")
    print("=" * 50)

    # Check for MONGODB_URI
    if not os.getenv("MONGODB_URI"):
        print("\nError: MONGODB_URI environment variable not set.")
        print("\nTo set it:")
        print("  1. Copy .env.example to .env")
        print("  2. Add your MongoDB Atlas connection string")
        print("  3. Run this script again")
        sys.exit(1)

    # Run migration
    success = asyncio.run(migrate())
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
