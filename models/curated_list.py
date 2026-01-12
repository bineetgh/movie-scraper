"""Curated movie lists model."""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime


@dataclass
class CuratedList:
    """A curated list of movies created by admin."""
    slug: str
    label: str
    description: str = ""
    movie_slugs: List[str] = field(default_factory=list)
    is_active: bool = True
    display_order: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_document(self) -> Dict[str, Any]:
        """Convert to MongoDB document."""
        return {
            "_id": self.slug,
            "label": self.label,
            "description": self.description,
            "movie_slugs": self.movie_slugs,
            "is_active": self.is_active,
            "display_order": self.display_order,
            "created_at": self.created_at or datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }

    @classmethod
    def from_document(cls, doc: Dict[str, Any]) -> Optional["CuratedList"]:
        """Create from MongoDB document."""
        if not doc:
            return None
        return cls(
            slug=doc.get("_id", ""),
            label=doc.get("label", ""),
            description=doc.get("description", ""),
            movie_slugs=doc.get("movie_slugs", []),
            is_active=doc.get("is_active", True),
            display_order=doc.get("display_order", 0),
            created_at=doc.get("created_at"),
            updated_at=doc.get("updated_at"),
        )
