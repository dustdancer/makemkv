# file: makemkv/tmdb_client.py
from __future__ import annotations
"""
Lightweight TMDb client (no external deps).

Features
- Reads API key, language and timeout from config.CONFIG["TMDB"]
- Search TV / Movie
- Resolve TV show id from (name, optional year)
- Get episode count for a specific TV season
- Tiny retry & 429 handling, careful logging (API key never printed)

Typical use:
    from .tmdb_client import tmdb_is_enabled, get_season_episode_count
    eps = get_season_episode_count("Adventure Time: Distant Lands", "2020", 1, log)

Returns `None` when:
- No API key configured,
- No match found,
- Network/API error occurred.
"""

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from .config import CONFIG


BASE_URL = "https://api.themoviedb.org/3"


# -----------------------------
# Helpers
# -----------------------------

def _mask(s: str, keep: int = 4) -> str:
    if not s:
        return ""
    return s[:keep] + ("…" if len(s) > keep else "")


def _http_get_json(
    path: str,
    params: Dict[str, Any],
    *,
    timeout: int,
    log: Optional[logging.Logger] = None,
    retries: int = 2,
    retry_backoff: float = 1.25
) -> Optional[Dict[str, Any]]:
    """
    Minimal GET with query params and small retry loop.
    - Retries on 5xx, 429, and transient URLError.
    - Returns parsed JSON dict or None.
    """
    url = f"{BASE_URL}{path}"
    q = urlencode(params)
    full_url = f"{url}?{q}" if q else url
    headers = {
        "Accept": "application/json",
        "Accept-Language": CONFIG["TMDB"].get("LANG", "de-DE"),
        "User-Agent": "makemkv-auto/1.0 (+tmdb-client)",
    }

    attempt = 0
    while True:
        attempt += 1
        try:
            req = Request(full_url, headers=headers)
            with urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw) if raw else {}
        except HTTPError as e:
            # 429 or 5xx -> retry; 4xx -> no retry
            if log:
                log.debug(f"TMDb HTTPError {e.code} on {path} (attempt {attempt}/{retries+1})")
            if e.code in (429, 500, 502, 503, 504) and attempt <= (retries + 1):
                # Respect Retry-After if present (seconds)
                delay = float(e.headers.get("Retry-After") or 0) or (retry_backoff * attempt)
                time.sleep(delay)
                continue
            return None
        except URLError as e:
            if log:
                log.debug(f"TMDb URLError on {path}: {e} (attempt {attempt}/{retries+1})")
            if attempt <= (retries + 1):
                time.sleep(retry_backoff * attempt)
                continue
            return None
        except Exception as e:
            if log:
                log.debug(f"TMDb unknown error on {path}: {e}")
            return None


def tmdb_is_enabled() -> bool:
    """True wenn ein API-Key in CONFIG gesetzt ist."""
    return bool(CONFIG.get("TMDB", {}).get("API_KEY"))


@dataclass
class TMDbConfig:
    api_key: str
    lang: str
    timeout: int


def _cfg() -> Optional[TMDbConfig]:
    api = CONFIG["TMDB"].get("API_KEY") or ""
    if not api:
        return None
    return TMDbConfig(
        api_key=api,
        lang=CONFIG["TMDB"].get("LANG", "de-DE"),
        timeout=int(CONFIG["TMDB"].get("TIMEOUT", 8)),
    )


# -----------------------------
# Core client
# -----------------------------

def search_tv(
    query: str,
    *,
    year_hint: Optional[str] = None,
    log: Optional[logging.Logger] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Return list of TV results, or None on error; empty list if no match."""
    cfg = _cfg()
    if not cfg:
        if log:
            log.debug("TMDb: kein API-Key konfiguriert.")
        return None

    params = {
        "api_key": cfg.api_key,
        "language": cfg.lang,
        "query": query,
        "page": 1,
        "include_adult": "false",
    }
    if year_hint and year_hint.isdigit():
        params["first_air_date_year"] = year_hint

    data = _http_get_json("/search/tv", params, timeout=cfg.timeout, log=log)
    if data is None:
        return None
    return data.get("results", []) or []


def search_movie(
    query: str,
    *,
    year_hint: Optional[str] = None,
    log: Optional[logging.Logger] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Return list of Movie results, or None on error; empty list if no match."""
    cfg = _cfg()
    if not cfg:
        if log:
            log.debug("TMDb: kein API-Key konfiguriert.")
        return None

    params = {
        "api_key": cfg.api_key,
        "language": cfg.lang,
        "query": query,
        "page": 1,
        "include_adult": "false",
    }
    if year_hint and year_hint.isdigit():
        params["year"] = year_hint

    data = _http_get_json("/search/movie", params, timeout=cfg.timeout, log=log)
    if data is None:
        return None
    return data.get("results", []) or []


def resolve_tv_id(
    series_name: str,
    *,
    year_hint: Optional[str] = None,
    log: Optional[logging.Logger] = None,
) -> Optional[int]:
    """
    Heuristics to pick the best TV id:
    - Exact name match (casefold) on "name" or "original_name"
    - Otherwise: first result
    """
    results = search_tv(series_name, year_hint=year_hint, log=log)
    if results is None:
        # API error / key missing
        return None
    if not results:
        if log:
            log.debug("TMDb: keine Treffer in search/tv")
        return None

    want = series_name.casefold()
    exact = next(
        (r for r in results if str(r.get("name", "")).casefold() == want or str(r.get("original_name", "")).casefold() == want),
        None
    )
    chosen = exact or results[0]
    return int(chosen.get("id")) if chosen and chosen.get("id") is not None else None


def get_tv_season(
    tv_id: int,
    season_no: int,
    *,
    log: Optional[logging.Logger] = None,
) -> Optional[Dict[str, Any]]:
    """Return season object or None on error."""
    cfg = _cfg()
    if not cfg:
        return None

    params = {"api_key": cfg.api_key, "language": cfg.lang}
    data = _http_get_json(f"/tv/{tv_id}/season/{season_no}", params, timeout=cfg.timeout, log=log)
    return data


def get_season_episode_count(
    series_name: str,
    year_hint: Optional[str],
    season_no: Optional[int],
    log: Optional[logging.Logger] = None,
) -> Optional[int]:
    """
    Resolve expected number of episodes for a season by series name + optional year.
    Returns None if season_no is None or no match/error.
    """
    if season_no is None:
        return None

    tv_id = resolve_tv_id(series_name, year_hint=year_hint, log=log)
    if not tv_id:
        return None

    season = get_tv_season(tv_id, int(season_no), log=log)
    if not season:
        return None

    eps = season.get("episodes")
    return len(eps) if isinstance(eps, list) else None


# -----------------------------
# Convenience logging wrappers
# -----------------------------

def log_tmdb_status(log: logging.Logger) -> None:
    """Log a small status line telling if the API key is present."""
    api = CONFIG["TMDB"].get("API_KEY") or ""
    if api:
        log.info(f"TMDb: API-Key erkannt ({_mask(api)})")
    else:
        log.info("TMDb: kein API-Key geladen")


__all__ = [
    "tmdb_is_enabled",
    "search_tv",
    "search_movie",
    "resolve_tv_id",
    "get_tv_season",
    "get_season_episode_count",
    "log_tmdb_status",
]
