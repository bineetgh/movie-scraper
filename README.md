# Watchlazy - Free Movie Finder for India

A web application to discover free movies available on streaming platforms in India. Aggregates content from JustWatch and Internet Archive.

## Features

- **Multi-source aggregation** - Fetches free movies from JustWatch India and Internet Archive
- **Smart caching** - 6-hour server cache with file persistence, configurable client-side caching
- **Cache-first search** - Instant search results from cache, falls back to APIs when needed
- **Embedded player** - Watch Internet Archive movies directly on the site
- **Personalized recommendations** - "For You" section based on your ratings and watch history
- **User preferences** - Rate movies, mark as watched, hide unwanted titles
- **My List** - Save movies to watch later (stored in browser)
- **Filtering & sorting** - Filter by service, genre, rating; sort by year, rating, title

## Quick Start

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd movie-scraper

# Install dependencies
pip install -r requirements.txt

# (Optional) Configure cache TTL
cp .env.example .env
# Edit .env as needed
```

### Running the Server

```bash
# Development mode with auto-reload
uvicorn api:app --reload

# Production mode
uvicorn api:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000 in your browser.

## Configuration

Create a `.env` file in the project root:

```env
# Cache TTL in seconds (default: 21600 = 6 hours)
CACHE_TTL_SECONDS=21600
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web frontend |
| `/movies` | GET | List all cached movies |
| `/movies/search?q=<query>` | GET | Search movies (cache-first) |
| `/movies/top` | GET | Top-rated movies by IMDb score |
| `/movies/random` | GET | Random movie recommendations |
| `/movies/services` | GET | List streaming services with counts |
| `/movies/{title}` | GET | Find movie by title |
| `/refresh` | POST | Force refresh movie cache |
| `/health` | GET | Health check |

### Search Parameters

```
GET /movies/search?q=love&force_online=false&cache_min_results=5
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `q` | required | Search query |
| `force_online` | false | Bypass cache, search external APIs |
| `cache_min_results` | 5 | Min cache results before API fallback |

### Filter Parameters

```
GET /movies?limit=50&service=JioHotstar&genre=drm
GET /movies/top?limit=20&min_rating=7.0&service=Plex
```

## Project Structure

```
movie-scraper/
├── api.py              # FastAPI application
├── main.py             # CLI scraper
├── models/
│   └── movie.py        # Movie dataclass
├── scrapers/
│   ├── base.py         # Base scraper class
│   ├── justwatch.py    # JustWatch India scraper
│   └── fallback.py     # Internet Archive scraper
├── static/
│   └── index.html      # Web frontend (single-page app)
├── cache/
│   └── movies.json     # Cached movie data
├── .env                # Environment configuration
└── requirements.txt    # Python dependencies
```

## Data Sources

- **JustWatch India** - Free movies from streaming platforms (JioHotstar, MX Player, etc.)
- **Internet Archive** - Public domain and freely available films

## Browser Storage

The frontend uses localStorage for:
- `myMovieList` - Saved movies
- `movieReactions` - User ratings (loved/liked/meh/disliked)
- `watchedMovies` - Watch history
- `hiddenMovies` - Hidden titles (permanent)
- `watchlazySettings` - User preferences
- `apiCache` - Client-side API response cache

## Tech Stack

- **Backend**: Python, FastAPI, uvicorn
- **Frontend**: Vanilla JavaScript, CSS (no framework)
- **Data**: JustWatch GraphQL API, Internet Archive Search API

## License

MIT
