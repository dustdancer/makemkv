# tmdb.py
# Kleiner Adapter: re-exportiert Funktionen aus tmdb_client,
# damit main.py weiter "from tmdb import ..." verwenden kann.

from tmdb_client import tmdb_is_enabled, tmdb_get_season_episode_count

__all__ = ["tmdb_is_enabled", "tmdb_get_season_episode_count"]
