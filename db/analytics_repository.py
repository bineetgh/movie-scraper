"""Analytics repository for tracking and querying site metrics."""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import DESCENDING

logger = logging.getLogger(__name__)


class AnalyticsRepository:
    """Repository for analytics database operations."""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.page_views = db.analytics_pageviews
        self.searches = db.analytics_searches
        self.admin_actions = db.analytics_admin_actions

    async def record_page_view(self, path: str, movie_slug: Optional[str] = None):
        """Record a page view event."""
        now = datetime.utcnow()
        await self.page_views.insert_one({
            "path": path,
            "movie_slug": movie_slug,
            "timestamp": now,
            "date": now.strftime("%Y-%m-%d"),
            "hour": now.hour,
        })

    async def record_search(self, query: str, results_count: int):
        """Record a search query."""
        now = datetime.utcnow()
        await self.searches.insert_one({
            "query": query.lower().strip(),
            "results_count": results_count,
            "timestamp": now,
            "date": now.strftime("%Y-%m-%d"),
        })

    async def record_admin_action(self, action: str, target: Optional[str] = None, details: Optional[Dict] = None):
        """Record an admin action for audit log."""
        await self.admin_actions.insert_one({
            "action": action,
            "target": target,
            "details": details or {},
            "timestamp": datetime.utcnow(),
        })

    async def get_overview_stats(self, days: int = 7) -> Dict[str, Any]:
        """Get overview statistics for the dashboard."""
        since = datetime.utcnow() - timedelta(days=days)

        # Total page views
        total_views = await self.page_views.count_documents({"timestamp": {"$gte": since}})

        # Total searches
        total_searches = await self.searches.count_documents({"timestamp": {"$gte": since}})

        # Unique movies viewed
        unique_movies = await self.page_views.distinct("movie_slug", {
            "timestamp": {"$gte": since},
            "movie_slug": {"$ne": None}
        })

        return {
            "total_views": total_views,
            "total_searches": total_searches,
            "unique_movies_viewed": len(unique_movies),
            "period_days": days,
        }

    async def get_popular_movies(self, days: int = 7, limit: int = 10) -> List[Dict[str, Any]]:
        """Get most viewed movies."""
        since = datetime.utcnow() - timedelta(days=days)

        pipeline = [
            {"$match": {"timestamp": {"$gte": since}, "movie_slug": {"$ne": None}}},
            {"$group": {"_id": "$movie_slug", "views": {"$sum": 1}}},
            {"$sort": {"views": -1}},
            {"$limit": limit},
        ]

        cursor = self.page_views.aggregate(pipeline)
        results = await cursor.to_list(length=limit)
        return [{"slug": r["_id"], "views": r["views"]} for r in results]

    async def get_popular_searches(self, days: int = 7, limit: int = 10) -> List[Dict[str, Any]]:
        """Get most popular search queries."""
        since = datetime.utcnow() - timedelta(days=days)

        pipeline = [
            {"$match": {"timestamp": {"$gte": since}}},
            {"$group": {"_id": "$query", "count": {"$sum": 1}, "avg_results": {"$avg": "$results_count"}}},
            {"$sort": {"count": -1}},
            {"$limit": limit},
        ]

        cursor = self.searches.aggregate(pipeline)
        results = await cursor.to_list(length=limit)
        return [{"query": r["_id"], "count": r["count"], "avg_results": round(r["avg_results"], 1)} for r in results]

    async def get_views_by_day(self, days: int = 7) -> List[Dict[str, Any]]:
        """Get page views grouped by day."""
        since = datetime.utcnow() - timedelta(days=days)

        pipeline = [
            {"$match": {"timestamp": {"$gte": since}}},
            {"$group": {"_id": "$date", "views": {"$sum": 1}}},
            {"$sort": {"_id": 1}},
        ]

        cursor = self.page_views.aggregate(pipeline)
        results = await cursor.to_list(length=days + 1)
        return [{"date": r["_id"], "views": r["views"]} for r in results]

    async def get_views_by_hour(self, days: int = 1) -> List[Dict[str, Any]]:
        """Get page views grouped by hour for traffic patterns."""
        since = datetime.utcnow() - timedelta(days=days)

        pipeline = [
            {"$match": {"timestamp": {"$gte": since}}},
            {"$group": {"_id": "$hour", "views": {"$sum": 1}}},
            {"$sort": {"_id": 1}},
        ]

        cursor = self.page_views.aggregate(pipeline)
        results = await cursor.to_list(length=24)

        # Fill in missing hours with 0
        hours_data = {r["_id"]: r["views"] for r in results}
        return [{"hour": h, "views": hours_data.get(h, 0)} for h in range(24)]

    async def get_top_pages(self, days: int = 7, limit: int = 10) -> List[Dict[str, Any]]:
        """Get most visited pages."""
        since = datetime.utcnow() - timedelta(days=days)

        pipeline = [
            {"$match": {"timestamp": {"$gte": since}}},
            {"$group": {"_id": "$path", "views": {"$sum": 1}}},
            {"$sort": {"views": -1}},
            {"$limit": limit},
        ]

        cursor = self.page_views.aggregate(pipeline)
        results = await cursor.to_list(length=limit)
        return [{"path": r["_id"], "views": r["views"]} for r in results]

    async def get_recent_admin_actions(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent admin actions for audit log."""
        cursor = self.admin_actions.find().sort("timestamp", DESCENDING).limit(limit)
        results = await cursor.to_list(length=limit)
        return [{
            "action": r["action"],
            "target": r.get("target"),
            "details": r.get("details", {}),
            "timestamp": r["timestamp"],
        } for r in results]

    async def get_zero_result_searches(self, days: int = 7, limit: int = 10) -> List[Dict[str, Any]]:
        """Get searches that returned no results - content gap analysis."""
        since = datetime.utcnow() - timedelta(days=days)

        pipeline = [
            {"$match": {"timestamp": {"$gte": since}, "results_count": 0}},
            {"$group": {"_id": "$query", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": limit},
        ]

        cursor = self.searches.aggregate(pipeline)
        results = await cursor.to_list(length=limit)
        return [{"query": r["_id"], "count": r["count"]} for r in results]
