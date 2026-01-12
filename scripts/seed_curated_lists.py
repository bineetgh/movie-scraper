"""Seed curated movie lists into MongoDB with movies."""

import asyncio
import os
import sys
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()


async def get_movies_by_criteria(db, genres=None, min_rating=None, max_rating=None,
                                  exclude_genres=None, limit=20, title_contains=None):
    """Get movie slugs matching criteria."""
    query = {}

    if genres:
        query["genres"] = {"$in": genres}

    if exclude_genres:
        query["genres"] = query.get("genres", {})
        query.setdefault("genres", {})["$nin"] = exclude_genres

    if min_rating is not None or max_rating is not None:
        query["rating"] = {}
        if min_rating is not None:
            query["rating"]["$gte"] = min_rating
        if max_rating is not None:
            query["rating"]["$lte"] = max_rating
        if not query["rating"]:
            del query["rating"]

    # Sort by rating descending
    cursor = db.movies.find(query, {"_id": 1}).sort("rating", -1).limit(limit)
    movies = await cursor.to_list(length=limit)
    return [m["_id"] for m in movies]


async def seed_lists():
    """Insert curated lists into MongoDB with movies."""
    mongo_uri = os.getenv("MONGODB_URI")
    if not mongo_uri:
        print("Error: MONGODB_URI not set in environment")
        return

    client = AsyncIOMotorClient(mongo_uri)
    db = client.get_default_database()
    collection = db.curated_lists

    now = datetime.utcnow()

    # Genre codes mapping:
    # act=action, cmy=comedy, drm=drama, hrr=horror, rma=romance, trl=thriller
    # scf=sci-fi, fnt=fantasy, crm=crime, doc=documentary, war=war, hst=history
    # eur=erotic, msc=music, spt=sports, anm=animation

    print("Fetching movies for each list...\n")

    # Build lists with movie criteria
    CURATED_LISTS = [
        {
            "_id": "must-watch",
            "label": "Must Watch",
            "description": "Timeless classics and modern masterpieces you can't miss",
            "is_active": True,
            "display_order": 1,
            "criteria": {"min_rating": 7.5, "limit": 25},
        },
        {
            "_id": "weekend-bingeworthy",
            "label": "Weekend Bingeworthy",
            "description": "Perfect picks for your lazy weekend marathon",
            "is_active": True,
            "display_order": 2,
            "criteria": {"genres": ["act", "trl", "scf"], "min_rating": 6.5, "limit": 20},
        },
        {
            "_id": "kids-corner",
            "label": "Kids Corner",
            "description": "Fun and family-friendly movies for the little ones",
            "is_active": True,
            "display_order": 3,
            "criteria": {"genres": ["anm", "fnt"], "exclude_genres": ["hrr", "eur"], "min_rating": 5.0, "limit": 20},
        },
        {
            "_id": "teen-picks",
            "label": "Teen Picks",
            "description": "Action, adventure, and coming-of-age stories for teens",
            "is_active": True,
            "display_order": 4,
            "criteria": {"genres": ["act", "scf", "fnt"], "exclude_genres": ["eur"], "min_rating": 6.0, "limit": 20},
        },
        {
            "_id": "date-night",
            "label": "Date Night",
            "description": "Romantic and feel-good movies for couples",
            "is_active": True,
            "display_order": 5,
            "criteria": {"genres": ["rma"], "exclude_genres": ["hrr", "eur"], "min_rating": 5.5, "limit": 20},
        },
        {
            "_id": "late-night-steamy",
            "label": "Late Night Steamy",
            "description": "Bold and sensual picks for mature audiences",
            "is_active": True,
            "display_order": 6,
            "criteria": {"genres": ["eur", "rma"], "min_rating": 4.0, "limit": 25},
        },
        {
            "_id": "desi-hits",
            "label": "Desi Hits",
            "description": "Best of Bollywood, Tollywood, and regional Indian cinema",
            "is_active": True,
            "display_order": 7,
            "criteria": {"min_rating": 6.5, "limit": 30},  # Will filter by Indian titles
        },
        {
            "_id": "south-masala",
            "label": "South Masala",
            "description": "Action-packed blockbusters from South Indian cinema",
            "is_active": True,
            "display_order": 8,
            "criteria": {"genres": ["act"], "min_rating": 6.0, "limit": 25},
        },
        {
            "_id": "hidden-gems",
            "label": "Hidden Gems",
            "description": "Underrated movies that deserve more love",
            "is_active": True,
            "display_order": 9,
            "criteria": {"min_rating": 6.5, "max_rating": 7.5, "limit": 20},
        },
        {
            "_id": "mind-benders",
            "label": "Mind Benders",
            "description": "Thrillers and mysteries that will keep you guessing",
            "is_active": True,
            "display_order": 10,
            "criteria": {"genres": ["trl", "crm"], "min_rating": 6.0, "limit": 20},
        },
        {
            "_id": "laugh-out-loud",
            "label": "Laugh Out Loud",
            "description": "Comedies guaranteed to crack you up",
            "is_active": True,
            "display_order": 11,
            "criteria": {"genres": ["cmy"], "exclude_genres": ["hrr", "eur"], "min_rating": 5.5, "limit": 20},
        },
        {
            "_id": "edge-of-seat",
            "label": "Edge of Your Seat",
            "description": "Heart-pounding action and suspense thrillers",
            "is_active": True,
            "display_order": 12,
            "criteria": {"genres": ["act", "trl"], "min_rating": 6.5, "limit": 20},
        },
    ]

    # Fetch movies for each list
    for lst in CURATED_LISTS:
        criteria = lst.pop("criteria", {})
        movie_slugs = await get_movies_by_criteria(
            db,
            genres=criteria.get("genres"),
            min_rating=criteria.get("min_rating"),
            max_rating=criteria.get("max_rating"),
            exclude_genres=criteria.get("exclude_genres"),
            limit=criteria.get("limit", 20),
        )
        lst["movie_slugs"] = movie_slugs

    # Special handling for Desi Hits - look for Indian movie patterns
    desi_patterns = ["2025", "2024", "2023"]  # Recent Indian movies
    indian_keywords = ["bahubali", "kantara", "akhanda", "jolly", "de-de-pyaar",
                       "saali", "haq", "thamma", "kaantha", "mass-jathara",
                       "andhra", "dominic", "saiyaara", "eko", "raat-akeli"]

    desi_cursor = db.movies.find(
        {"rating": {"$gte": 5.0}},
        {"_id": 1, "title": 1}
    ).sort("rating", -1).limit(200)
    all_movies = await desi_cursor.to_list(length=200)

    desi_slugs = []
    for m in all_movies:
        slug = m["_id"]
        if any(kw in slug for kw in indian_keywords):
            desi_slugs.append(slug)
        if len(desi_slugs) >= 25:
            break

    # Update Desi Hits list
    for lst in CURATED_LISTS:
        if lst["_id"] == "desi-hits":
            lst["movie_slugs"] = desi_slugs if desi_slugs else lst["movie_slugs"][:15]
            break

    # Insert or update lists
    inserted = 0
    updated = 0

    for lst in CURATED_LISTS:
        existing = await collection.find_one({"_id": lst["_id"]})

        lst["created_at"] = existing["created_at"] if existing else now
        lst["updated_at"] = now

        if existing:
            await collection.replace_one({"_id": lst["_id"]}, lst)
            print(f"  Updated: {lst['label']} ({len(lst['movie_slugs'])} movies)")
            updated += 1
        else:
            await collection.insert_one(lst)
            print(f"  Created: {lst['label']} ({len(lst['movie_slugs'])} movies)")
            inserted += 1

    print(f"\nDone! Created: {inserted}, Updated: {updated}")

    # Show sample movies for verification
    print("\n--- Sample movies per list ---")
    for lst in CURATED_LISTS:
        slugs = lst["movie_slugs"][:3]
        print(f"{lst['label']}: {', '.join(slugs) if slugs else '(empty)'}")

    client.close()


if __name__ == "__main__":
    print("Seeding curated lists with movies...\n")
    asyncio.run(seed_lists())
