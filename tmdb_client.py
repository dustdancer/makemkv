# -*- coding: utf-8 -*-
from __future__ import annotations
import json
from typing import Dict, Optional
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from config import CONFIG

def _http_get_json(url: str, params: Dict[str, str], timeout: int) -> Optional[Dict]:
    query = urlencode(params)
    req = Request(url + ("?" + query if query else ""), headers={"Accept": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8", errors="replace")
            return json.loads(data)
    except Exception:
        return None

def tmdb_is_enabled() -> bool:
    return bool(CONFIG["TMDB"].get("API_KEY"))

def tmdb_search_tv_id(series_name: str, year_hint: Optional[str]) -> Optional[int]:
    api = CONFIG["TMDB"].get("API_KEY")
    if not api: return None
    base = "https://api.themoviedb.org/3/search/tv"
    params = {
        "api_key": api,
        "language": CONFIG["TMDB"].get("LANG", "de-DE"),
        "query": series_name,
    }
    if year_hint and year_hint.isdigit():
        params["first_air_date_year"] = year_hint
    data = _http_get_json(base, params, CONFIG["TMDB"].get("TIMEOUT", 8))
    if not data or not data.get("results"):
        return None
    results = data["results"]
    for r in results:
        if str(r.get("name", "")).lower() == series_name.lower():
            return r.get("id")
    return results[0].get("id")

def tmdb_get_season_episode_count(series_name: str, year_hint: Optional[str], season_no: Optional[int]) -> Optional[int]:
    if season_no is None: return None
    api = CONFIG["TMDB"].get("API_KEY")
    if not api: return None
    sid = tmdb_search_tv_id(series_name, year_hint)
    if not sid: return None
    base = f"https://api.themoviedb.org/3/tv/{sid}/season/{season_no}"
    params = {"api_key": api, "language": CONFIG["TMDB"].get("LANG", "de-DE")}
    data = _http_get_json(base, params, CONFIG["TMDB"].get("TIMEOUT", 8))
    if not data: return None
    eps = data.get("episodes")
    return len(eps) if isinstance(eps, list) else None
