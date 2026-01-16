import re
from typing import Dict, List, Optional

from models.movie import Movie
from models.offer import StreamingOffer, StreamingAvailability, MonetizationType
from scrapers.base import BaseScraper


class JustWatchScraper(BaseScraper):
    """Scraper for JustWatch India - aggregates movies from multiple streaming services."""

    GRAPHQL_URL = "https://apis.justwatch.com/graphql"
    COUNTRY = "IN"
    LANGUAGE = "en"

    # All monetization types
    ALL_MONETIZATION_TYPES = ["FREE", "ADS", "FLATRATE", "RENT", "BUY"]
    FREE_MONETIZATION_TYPES = ["FREE", "ADS", "FLATRATE_AND_ADS"]

    # Genre short code to full name mapping
    GENRE_MAP = {
        "act": "Action",
        "ani": "Animation",
        "cmy": "Comedy",
        "crm": "Crime",
        "doc": "Documentary",
        "drm": "Drama",
        "eur": "European",
        "fml": "Family",
        "fnt": "Fantasy",
        "hst": "History",
        "hrr": "Horror",
        "msc": "Music",
        "rma": "Romance",
        "scf": "Sci-Fi",
        "spt": "Sport",
        "trl": "Thriller",
        "war": "War",
        "wst": "Western",
    }

    # GraphQL query to fetch movies with pricing
    POPULAR_TITLES_QUERY = """
    query GetPopularTitles(
        $country: Country!
        $language: Language!
        $first: Int!
        $after: String
        $filter: TitleFilter
    ) {
        popularTitles(
            country: $country
            first: $first
            after: $after
            filter: $filter
        ) {
            pageInfo {
                endCursor
                hasNextPage
            }
            edges {
                node {
                    id
                    objectType
                    objectId
                    content(country: $country, language: $language) {
                        title
                        originalReleaseYear
                        shortDescription
                        genres {
                            shortName
                        }
                        credits {
                            role
                            name
                        }
                        runtime
                        posterUrl
                        backdrops {
                            backdropUrl
                        }
                        externalIds {
                            imdbId
                            tmdbId
                        }
                        scoring {
                            imdbScore
                        }
                    }
                    offers(country: $country, platform: WEB) {
                        monetizationType
                        presentationType
                        retailPrice(language: $language)
                        currency
                        standardWebURL
                        package {
                            packageId
                            clearName
                        }
                    }
                }
            }
        }
    }
    """

    SEARCH_QUERY = """
    query SearchTitles(
        $country: Country!
        $language: Language!
        $searchQuery: String!
        $first: Int!
    ) {
        popularTitles(
            country: $country
            first: $first
            filter: {
                searchQuery: $searchQuery
                objectTypes: [MOVIE]
            }
        ) {
            edges {
                node {
                    id
                    objectType
                    objectId
                    content(country: $country, language: $language) {
                        title
                        originalReleaseYear
                        shortDescription
                        genres {
                            shortName
                        }
                        credits {
                            role
                            name
                        }
                        runtime
                        posterUrl
                        backdrops {
                            backdropUrl
                        }
                        externalIds {
                            imdbId
                            tmdbId
                        }
                        scoring {
                            imdbScore
                        }
                    }
                    offers(country: $country, platform: WEB) {
                        monetizationType
                        presentationType
                        retailPrice(language: $language)
                        currency
                        standardWebURL
                        package {
                            packageId
                            clearName
                        }
                    }
                }
            }
        }
    }
    """

    def _execute_query(self, query: str, variables: Dict) -> Dict:
        """Execute a GraphQL query against JustWatch API."""
        response = self.post(
            self.GRAPHQL_URL,
            json={"query": query, "variables": variables},
        )
        return response.json()

    def _parse_price(self, price_str: Optional[str]) -> Optional[float]:
        """Parse price string like '₹149' or '149.00' to float."""
        if not price_str:
            return None
        clean = re.sub(r'[^\d.]', '', str(price_str))
        try:
            return float(clean) if clean else None
        except ValueError:
            return None

    def _parse_offers(self, offers: List[Dict]) -> StreamingAvailability:
        """Parse JustWatch offers into structured StreamingAvailability."""
        availability = StreamingAvailability()
        seen = set()

        for offer in offers or []:
            provider = offer.get("package", {}).get("clearName", "")
            if not provider:
                continue

            monetization = offer.get("monetizationType", "")
            presentation = offer.get("presentationType", "")

            # Deduplicate by (provider, monetization, presentation)
            key = (provider, monetization, presentation)
            if key in seen:
                continue
            seen.add(key)

            streaming_offer = StreamingOffer(
                provider_name=provider,
                provider_id=str(offer.get("package", {}).get("packageId", "")),
                monetization_type=monetization,
                presentation_type=presentation if presentation in ["SD", "HD", "4K"] else None,
                price=self._parse_price(offer.get("retailPrice")),
                currency=offer.get("currency", "INR"),
                url=offer.get("standardWebURL", ""),
            )

            # Categorize by monetization type
            if monetization in ("FREE", "ADS", "FLATRATE_AND_ADS"):
                availability.free_offers.append(streaming_offer)
            elif monetization == "FLATRATE":
                availability.subscription_offers.append(streaming_offer)
            elif monetization == "RENT":
                availability.rent_offers.append(streaming_offer)
            elif monetization == "BUY":
                availability.buy_offers.append(streaming_offer)

        return availability

    def _parse_movie(self, node: Dict) -> Optional[Movie]:
        """Parse a movie node from GraphQL response."""
        content = node.get("content", {})
        offers = node.get("offers", []) or []

        # Parse all offers into structured format
        streaming = self._parse_offers(offers)

        # Skip movies with no offers at all
        if not streaming.has_any_offer():
            return None

        # Extract cast and director
        cast = []
        director = None
        for credit in content.get("credits", []) or []:
            if credit.get("role") == "DIRECTOR" and not director:
                director = credit.get("name")
            elif credit.get("role") == "ACTOR":
                cast.append(credit.get("name"))

        # Extract streaming services and URLs (for backwards compatibility)
        all_offers = (streaming.free_offers + streaming.subscription_offers +
                      streaming.rent_offers + streaming.buy_offers)
        services = list({o.provider_name for o in all_offers})
        urls = list({o.url for o in all_offers if o.url})

        # Build poster URL
        poster_url = None
        if content.get("posterUrl"):
            poster_url = f"https://images.justwatch.com{content['posterUrl'].replace('{profile}', 's592')}"

        # Build backdrop URL
        backdrop_url = None
        backdrops = content.get("backdrops", []) or []
        if backdrops:
            backdrop = backdrops[0].get("backdropUrl", "")
            if backdrop:
                backdrop_url = f"https://images.justwatch.com{backdrop.replace('{profile}', 's1440')}"

        # Extract external IDs
        external_ids = content.get("externalIds", {}) or {}
        tmdb_id = None
        imdb_id = None
        if external_ids:
            tmdb_id_str = external_ids.get("tmdbId")
            if tmdb_id_str:
                try:
                    tmdb_id = int(tmdb_id_str)
                except (ValueError, TypeError):
                    pass
            imdb_id = external_ids.get("imdbId")

        return Movie(
            title=content.get("title", ""),
            year=content.get("originalReleaseYear"),
            genres=[self.GENRE_MAP.get(g.get("shortName", ""), g.get("shortName", "").title()) for g in content.get("genres", []) or [] if g.get("shortName")],
            rating=content.get("scoring", {}).get("imdbScore") if content.get("scoring") else None,
            synopsis=content.get("shortDescription", "") or "",
            cast=cast[:10],
            director=director,
            runtime_minutes=content.get("runtime"),
            poster_url=poster_url,
            backdrop_url=backdrop_url,
            trailer_url=None,
            streaming_services=services,
            source_urls=urls,
            tmdb_id=tmdb_id,
            imdb_id=imdb_id,
            justwatch_id=node.get("id"),
            streaming=streaming,
        )

    def fetch_movies(
        self,
        limit: Optional[int] = 100,
        monetization_types: Optional[List[str]] = None
    ) -> List[Movie]:
        """Fetch movies from JustWatch India.

        Args:
            limit: Maximum number of movies to fetch
            monetization_types: List of monetization types to include.
                               Defaults to all types (FREE, ADS, FLATRATE, RENT, BUY)
        """
        if monetization_types is None:
            monetization_types = self.ALL_MONETIZATION_TYPES

        movies = []
        cursor = None
        page_size = min(limit or 100, 50)

        print(f"Fetching movies from JustWatch India (types: {monetization_types})...")

        while True:
            variables = {
                "country": self.COUNTRY,
                "language": self.LANGUAGE,
                "first": page_size,
                "after": cursor,
                "filter": {
                    "objectTypes": ["MOVIE"],
                    "monetizationTypes": monetization_types,
                },
            }

            try:
                data = self._execute_query(self.POPULAR_TITLES_QUERY, variables)
                titles = data.get("data", {}).get("popularTitles", {})
                edges = titles.get("edges", [])

                for edge in edges:
                    movie = self._parse_movie(edge.get("node", {}))
                    if movie:
                        movies.append(movie)

                    if limit and len(movies) >= limit:
                        print(f"Fetched {len(movies)} movies")
                        return movies

                page_info = titles.get("pageInfo", {})
                if not page_info.get("hasNextPage"):
                    break

                cursor = page_info.get("endCursor")
                print(f"Fetched {len(movies)} movies so far...")

            except Exception as e:
                print(f"Error fetching from JustWatch: {e}")
                break

        print(f"Fetched {len(movies)} movies total")
        return movies

    def search(self, query: str) -> List[Movie]:
        """Search for movies by title."""
        variables = {
            "country": self.COUNTRY,
            "language": self.LANGUAGE,
            "searchQuery": query,
            "first": 20,
        }

        try:
            data = self._execute_query(self.SEARCH_QUERY, variables)
            titles = data.get("data", {}).get("popularTitles", {})
            edges = titles.get("edges", [])

            movies = []
            for edge in edges:
                movie = self._parse_movie(edge.get("node", {}))
                if movie:
                    movies.append(movie)

            return movies

        except Exception as e:
            print(f"Error searching JustWatch: {e}")
            return []
