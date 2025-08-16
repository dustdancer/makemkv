#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import re
import json
import logging
from pathlib import Path
from typing import Optional, Tuple, Dict

# -----------------------
# Filename / String utils
# -----------------------

def sanitize_filename(name: str) -> str:
    name = name.strip()
    name = re.sub(r"[\\/:\*\?\"<>\|\x00-\x1F]", "_", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip().rstrip("._-")

def parse_name_year(base: str) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Extrahiert (Name, Jahr, Version) aus einem Basis-String.
    Beispiele:
      "Blade Runner (1982) [Final Cut]" -> ("Blade Runner", "1982", "Final Cut")
      "Star Trek - DS9" -> ("Star Trek - DS9", None, None)
    """
    name = base
    version = None

    mver = re.search(r"\[(.+?)\]", base)
    if mver:
        version = mver.group(1).strip()
        name = re.sub(r"\s*\[.+?\]\s*", " ", name).strip()

    my = re.search(r"\((\d{4})\)", name)
    year = my.group(1) if my else None
    if my:
        name = re.sub(r"\s*\(\d{4}\)\s*", " ", name).strip()

    name = sanitize_filename(name)
    return name, year, version

def extract_season(s: str) -> Optional[int]:
    """
    Sucht nach Sxx / Season xx in Strings.
    """
    m = re.search(r"[Ss](?:eason)?\s*[_\-\.\s]?(\d{1,2})", s)
    if m:
        return int(m.group(1))
    m = re.search(r"\bS(\d{1,2})\b", s)
    return int(m.group(1)) if m else None

def extract_disc_no(s: str) -> Optional[int]:
    """
    Sucht nach Disc/Disk/D/CD/…-Nummern und Mustern wie S01D02.
    """
    s = s.replace("_", " ")
    patterns = [
        r"\bdisc\s*(\d{1,2})\b",
        r"\bdisk\s*(\d{1,2})\b",
        r"\bd\s*(\d{1,2})\b",
        r"\bD(\d{1,2})\b",
        r"\bCD\s*(\d{1,2})\b",
        r"\bS\d{1,2}D(\d{1,2})\b",
        r"\bDisc(\d{1,2})\b",
        r"\bDisk(\d{1,2})\b",
    ]
    for pat in patterns:
        m = re.search(pat, s, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
    return None

def fallback_series_info(series_base: str) -> Tuple[str, Optional[str]]:
    """
    Entfernt offensichtliche Disc/Season-Tokens und extrahiert (Serienname, Jahr-Hinweis).
    """
    cleaned = re.sub(r"\bS\d{1,2}D\d{1,2}\b", "", series_base, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b[Dd]isc\s*\d{1,2}\b", "", cleaned)
    cleaned = re.sub(r"\b[Dd](\d{1,2})\b", "", cleaned)
    cleaned = re.sub(r"\b[Ss](?:eason)?\s*\d{1,2}\b", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    name, year, _ = parse_name_year(cleaned)
    return name, year

# -----------------------
# Zielpfade
# -----------------------

def destination_for_movie(remux_root: Path, base: str) -> Path:
    name, year, _ = parse_name_year(base)
    dir_name = f"{name} ({year})" if year else name
    return Path(remux_root) / "movies" / dir_name

def destination_for_tv(remux_root: Path, base: str, season_no: Optional[int]) -> Path:
    """
    Ordnerstruktur: tv/<Serienname (Jahr)>/season 01
    """
    name, year, _ = parse_name_year(base)
    series_dir = f"{name} ({year})" if year else name
    season_dir = f"season {season_no:02d}" if season_no is not None else "season ??"
    return Path(remux_root) / "tv" / series_dir / season_dir

# -----------------------
# TMDb Helfer
# -----------------------

def tmdb_is_enabled() -> bool:
    return bool(os.environ.get("TMDB_API_KEY", "").strip())

def _http_get_json(url: str, params: Dict[str, str], timeout: int = 8) -> Optional[Dict]:
    """
    Kleiner urllib-Wrapper ohne externe Abhängigkeiten.
    """
    try:
        from urllib.request import Request, urlopen
        from urllib.parse import urlencode
    except Exception:
        return None

    try:
        q = urlencode(params)
        req = Request(url + ("?" + q if q else ""), headers={"Accept": "application/json"})
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8", errors="replace")
            return json.loads(data)
    except Exception:
        return None

def tmdb_search_tv_id(series_name: str, year_hint: Optional[str], log: Optional[logging.Logger] = None) -> Optional[int]:
    api = os.environ.get("TMDB_API_KEY", "").strip()
    if not api:
        return None
    base = "https://api.themoviedb.org/3/search/tv"
    params = {
        "api_key": api,
        "language": "de-DE",
        "query": series_name,
    }
    if year_hint and year_hint.isdigit():
        params["first_air_date_year"] = year_hint
    data = _http_get_json(base, params, timeout=8)
    if not data or not data.get("results"):
        if log:
            log.debug("TMDb: keine Treffer in search/tv")
        return None
    results = data["results"]
    for r in results:
        if r.get("name", "").lower() == series_name.lower():
            return r.get("id")
    return results[0].get("id")

def tmdb_get_season_episode_count(series_name: str, year_hint: Optional[str], season_no: Optional[int], log: Optional[logging.Logger] = None) -> Optional[int]:
    """
    Angleichen an main.py-Aufruf: (series_name, year_hint, season_no, log)
    """
    if season_no is None:
        return None
    api = os.environ.get("TMDB_API_KEY", "").strip()
    if not api:
        return None
    sid = tmdb_search_tv_id(series_name, year_hint, log)
    if not sid:
        return None
    base = f"https://api.themoviedb.org/3/tv/{sid}/season/{season_no}"
    params = {"api_key": api, "language": "de-DE"}
    data = _http_get_json(base, params, timeout=8)
    if not data:
        return None
    eps = data.get("episodes")
    return len(eps) if isinstance(eps, list) else None
