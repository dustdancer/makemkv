# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from typing import Dict, Optional

try:
    from urllib.request import Request, urlopen
    from urllib.parse import urlencode
except Exception:
    Request = None  # type: ignore
    urlopen = None  # type: ignore
    urlencode = None  # type: ignore


def tmdb_is_enabled(cfg: Dict) -> bool:
    return bool(cfg.get("API_KEY"))


def _http_get_json(url: str, params: Dict[str, str], timeout: int) -> Optional[Dict]:
    if Request is None or urlopen is None or urlencode is None:
        return None
    q = urlencode(params)
    req = Request(url + ("?" + q if q else ""), headers={"Accept": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8", errors="replace")
            return json.loads(data)
    except Exception:
        return None


def _tmdb_search_tv_id(series_name: str, year_hint: Optional[str], cfg: Dict) -> Optional[int]:
    api = cfg.get("API_KEY")
    base = "https://api.themoviedb.org/3/search/tv"
    params = {"api_key": api, "language": cfg.get("LANG", "de-DE"), "query": series_name}
    if year_hint and year_hint.isdigit():
        params["first_air_date_year"] = year_hint
    data = _http_get_json(base, params, cfg.get("TIMEOUT", 8))
    if not data or not data.get("results"):
        return None
    res = data["results"]
    for r in res:
        if r.get("name", "").lower() == series_name.lower():
            return r.get("id")
    return res[0].get("id")


def tmdb_get_season_episode_count(series_name: str, year_hint: Optional[str], season_no: Optional[int], cfg: Dict, log) -> Optional[int]:
    if not season_no:
        return None
    if not tmdb_is_enabled(cfg):
        return None
    sid = _tmdb_search_tv_id(series_name, year_hint, cfg)
    if not sid:
        return None
    base = f"https://api.themoviedb.org/3/tv/{sid}/season/{season_no}"
    params = {"api_key": cfg.get("API_KEY"), "language": cfg.get("LANG", "de-DE")}
    data = _http_get_json(base, params, cfg.get("TIMEOUT", 8))
    if not data:
        return None
    eps = data.get("episodes")
    return len(eps) if isinstance(eps, list) else None
