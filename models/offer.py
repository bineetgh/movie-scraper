from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum

from dataclasses_json import dataclass_json


class MonetizationType(str, Enum):
    """Types of monetization for streaming offers."""
    FREE = "FREE"
    ADS = "ADS"
    FLATRATE = "FLATRATE"  # Subscription
    FLATRATE_AND_ADS = "FLATRATE_AND_ADS"
    RENT = "RENT"
    BUY = "BUY"


class PresentationType(str, Enum):
    """Video quality/presentation types."""
    SD = "SD"
    HD = "HD"
    UHD_4K = "4K"


@dataclass_json
@dataclass
class StreamingOffer:
    """Represents a single streaming offer from a platform."""
    provider_name: str
    provider_id: str = ""
    monetization_type: str = "FREE"
    presentation_type: Optional[str] = None
    price: Optional[float] = None
    currency: str = "INR"
    url: str = ""

    def to_document(self) -> Dict[str, Any]:
        """Convert to MongoDB document."""
        return {
            "provider_name": self.provider_name,
            "provider_id": self.provider_id,
            "monetization_type": self.monetization_type,
            "presentation_type": self.presentation_type,
            "price": self.price,
            "currency": self.currency,
            "url": self.url,
        }

    @classmethod
    def from_document(cls, doc: Dict[str, Any]) -> "StreamingOffer":
        """Create from MongoDB document."""
        return cls(
            provider_name=doc.get("provider_name", ""),
            provider_id=doc.get("provider_id", ""),
            monetization_type=doc.get("monetization_type", "FREE"),
            presentation_type=doc.get("presentation_type"),
            price=doc.get("price"),
            currency=doc.get("currency", "INR"),
            url=doc.get("url", ""),
        )


@dataclass_json
@dataclass
class StreamingAvailability:
    """Aggregated streaming availability for a movie."""
    free_offers: List[StreamingOffer] = field(default_factory=list)
    subscription_offers: List[StreamingOffer] = field(default_factory=list)
    rent_offers: List[StreamingOffer] = field(default_factory=list)
    buy_offers: List[StreamingOffer] = field(default_factory=list)

    @property
    def is_free(self) -> bool:
        """Check if movie is available for free."""
        return len(self.free_offers) > 0

    @property
    def is_subscription(self) -> bool:
        """Check if movie is available via subscription."""
        return len(self.subscription_offers) > 0

    @property
    def is_rentable(self) -> bool:
        """Check if movie is available to rent."""
        return len(self.rent_offers) > 0

    @property
    def is_buyable(self) -> bool:
        """Check if movie is available to buy."""
        return len(self.buy_offers) > 0

    @property
    def min_rent_price(self) -> Optional[float]:
        """Get minimum rent price across all offers."""
        prices = [o.price for o in self.rent_offers if o.price is not None]
        return min(prices) if prices else None

    @property
    def min_buy_price(self) -> Optional[float]:
        """Get minimum buy price across all offers."""
        prices = [o.price for o in self.buy_offers if o.price is not None]
        return min(prices) if prices else None

    @property
    def all_providers(self) -> List[str]:
        """Get unique list of all provider names."""
        providers = set()
        for offers in [self.free_offers, self.subscription_offers,
                       self.rent_offers, self.buy_offers]:
            for offer in offers:
                providers.add(offer.provider_name)
        return sorted(providers)

    def has_any_offer(self) -> bool:
        """Check if there are any streaming offers."""
        return (len(self.free_offers) + len(self.subscription_offers) +
                len(self.rent_offers) + len(self.buy_offers)) > 0

    def to_document(self) -> Dict[str, Any]:
        """Convert to MongoDB document."""
        return {
            "free_offers": [o.to_document() for o in self.free_offers],
            "subscription_offers": [o.to_document() for o in self.subscription_offers],
            "rent_offers": [o.to_document() for o in self.rent_offers],
            "buy_offers": [o.to_document() for o in self.buy_offers],
        }

    @classmethod
    def from_document(cls, doc: Dict[str, Any]) -> "StreamingAvailability":
        """Create from MongoDB document."""
        if not doc:
            return cls()
        return cls(
            free_offers=[StreamingOffer.from_document(o) for o in doc.get("free_offers", [])],
            subscription_offers=[StreamingOffer.from_document(o) for o in doc.get("subscription_offers", [])],
            rent_offers=[StreamingOffer.from_document(o) for o in doc.get("rent_offers", [])],
            buy_offers=[StreamingOffer.from_document(o) for o in doc.get("buy_offers", [])],
        )
