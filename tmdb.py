# -*- coding: utf-8 -*-
"""
Shim-Modul: Stellt die bisher aus 'tmdb' importierten Funktionen bereit,
leitet intern an tmdb_client weiter. So muss main.py nicht angefasst werden.
"""

from tmdb_client import (
    tmdb_is_enabled,
    tmdb_get_season_episode_count,
    tmdb_search_tv_id,
)

__all__ = [
    "tmdb_is_enabled",
    "tmdb_get_season_episode_count",
    "tmdb_search_tv_id",
]
