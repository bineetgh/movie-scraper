"""Database package for MongoDB integration."""

from db.mongodb import get_database, close_connection, init_indexes
from db.movie_repository import MovieRepository

__all__ = ["get_database", "close_connection", "init_indexes", "MovieRepository"]
