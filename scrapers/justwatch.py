from typing import Dict, List, Optional

from models.movie import Movie
from scrapers.base import BaseScraper


class JustWatchScraper(BaseScraper):
    """Scraper for JustWatch India - aggregates free movies from multiple services."""

    GRAPHQL_URL = "https://apis.justwatch.com/graphql"
    COUNTRY = "IN"
    LANGUAGE = "en"

    # GraphQL query to fetch free movies
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
                        scoring {
                            imdbScore
                        }
                    }
                    offers(country: $country, platform: WEB) {
                        monetizationType
                        presentationType
                        standardWebURL
                        package {
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
                        scoring {
                            imdbScore
                        }
                    }
                    offers(country: $country, platform: WEB) {
                        monetizationType
                        presentationType
                        standardWebURL
                        package {
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

    def _parse_movie(self, node: Dict) -> Optional[Movie]:
        """Parse a movie node from GraphQL response."""
        content = node.get("content", {})
        offers = node.get("offers", []) or []

        # Filter for free offers only
        free_offers = [
            o for o in offers
            if o.get("monetizationType") in ("FREE", "ADS", "FLATRATE_AND_ADS")
        ]

        if not free_offers:
            return None

        # Extract cast and director
        cast = []
        director = None
        for credit in content.get("credits", []) or []:
            if credit.get("role") == "DIRECTOR" and not director:
                director = credit.get("name")
            elif credit.get("role") == "ACTOR":
                cast.append(credit.get("name"))

        # Extract streaming services and URLs
        services = list({o.get("package", {}).get("clearName") for o in free_offers if o.get("package")})
        urls = list({o.get("standardWebURL") for o in free_offers if o.get("standardWebURL")})

        # Build poster URL
        poster_url = None
        if content.get("posterUrl"):
            poster_url = f"https://images.justwatch.com{content['posterUrl'].replace('{profile}', 's592')}"

        return Movie(
            title=content.get("title", ""),
            year=content.get("originalReleaseYear"),
            genres=[g.get("shortName", "") for g in content.get("genres", []) or []],
            rating=content.get("scoring", {}).get("imdbScore") if content.get("scoring") else None,
            synopsis=content.get("shortDescription", "") or "",
            cast=cast[:10],  # Limit to top 10 cast
            director=director,
            runtime_minutes=content.get("runtime"),
            poster_url=poster_url,
            trailer_url=None,
            streaming_services=services,
            source_urls=urls,
        )

    def fetch_movies(self, limit: Optional[int] = 100) -> List[Movie]:
        """Fetch free movies from JustWatch India."""
        movies = []
        cursor = None
        page_size = min(limit or 100, 50)  # JustWatch limits to ~50 per page

        print(f"Fetching free movies from JustWatch India...")

        while True:
            variables = {
                "country": self.COUNTRY,
                "language": self.LANGUAGE,
                "first": page_size,
                "after": cursor,
                "filter": {
                    "objectTypes": ["MOVIE"],
                    "monetizationTypes": ["FREE", "ADS"],
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
                        print(f"Fetched {len(movies)} free movies")
                        return movies

                page_info = titles.get("pageInfo", {})
                if not page_info.get("hasNextPage"):
                    break

                cursor = page_info.get("endCursor")
                print(f"Fetched {len(movies)} movies so far...")

            except Exception as e:
                print(f"Error fetching from JustWatch: {e}")
                break

        print(f"Fetched {len(movies)} free movies total")
        return movies

    def search(self, query: str) -> List[Movie]:
        """Search for free movies by title."""
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
