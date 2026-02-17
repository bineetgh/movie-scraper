"""Analytics models for tracking site usage."""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime


@dataclass
class PageView:
    """Represents a page view event."""
    path: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    movie_slug: Optional[str] = None
    referrer: Optional[str] = None
    user_agent: Optional[str] = None

    def to_document(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "timestamp": self.timestamp,
            "movie_slug": self.movie_slug,
            "referrer": self.referrer,
            "user_agent": self.user_agent,
            "date": self.timestamp.strftime("%Y-%m-%d"),
            "hour": self.timestamp.hour,
        }


@dataclass
class SearchQuery:
    """Represents a search query event."""
    query: str
    results_count: int
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_document(self) -> Dict[str, Any]:
        return {
            "query": self.query.lower().strip(),
            "results_count": self.results_count,
            "timestamp": self.timestamp,
            "date": self.timestamp.strftime("%Y-%m-%d"),
        }


@dataclass
class AdminAction:
    """Represents an admin action for audit log."""
    action: str  # e.g., "movie_edit", "list_create", "refresh"
    target: Optional[str] = None  # e.g., movie slug or list slug
    details: Optional[Dict[str, Any]] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_document(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "target": self.target,
            "details": self.details or {},
            "timestamp": self.timestamp,
        }
