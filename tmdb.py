# tmdb.py
# -*- coding: utf-8 -*-
"""
Kleines TMDb-Hilfsmodul für makemkv:
- tmdb_is_enabled()
- tmdb_get_season_episode_count(series_name, year_hint, season_no, log)

API-Key wird aus der Umgebungsvariable TMDB_API_KEY gelesen.
Optional: secrets.txt (neben dieser Datei) mit z.B.:
    tmdb=DEIN_API_KEY
    apikey=DEIN_API_KEY
    tmdb_api_key=DEIN_API_KEY
"""

from __future__ import annotations
import os
import json
import logging
from pathlib import Path
from typing import Optional, Dict

try:
    from urllib.request import Request, urlopen
    from urllib.parse import urlencode
except Exception:
    Request = None  # type: ignore
    urlopen = None  # type: ignore
    urlencode = None  # type: ignore

# --- Konstante Defaults ---
_LANG = "de-DE"
_TIMEOUT = 8


def _load_api_key_from_secrets() -> Optional[str]:
    """
    Liest optional 'secrets.txt' aus demselben Ordner wie diese Datei.
    Erlaubte Schlüssel: tmdb, apikey, tmdb_api_key  (Groß-/Kleinschreibung egal)
    Format: key=value (Werte dürfen in '...' oder "..." stehen)
    """
    try:
        sec = Path(__file__).resolve().parent / "secrets.txt"
        if not sec.exists():
            return None
        for raw in sec.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith(";") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            key = k.strip().lower()
            val = v.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                val = val[1:-1]
            if key in ("tmdb", "apikey", "tmdb_api_key"):
                return val
    except Exception:
        pass
    return None


def _api_key() -> Optional[str]:
    return os.environ.get("TMDB_API_KEY") or _load_api_key_from_secrets()


def tmdb_is_enabled() -> bool:
    """Gibt True zurück, wenn ein TMDb-API-Key verfügbar ist."""
    return bool(_api_key())


def _http_get_json(url: str, params: Dict[str, str], timeout: int) -> Optional[Dict]:
    if Request is None or urlopen is None or urlencode is None:
        return None
    try:
        q = urlencode(params)
        req = Request(url + ("?" + q if q else ""), headers={"Accept": "application/json"})
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8", errors="replace")
            return json.loads(data)
    except Exception:
        return None


def _tmdb_search_tv_id(series_name: str, year_hint: Optional[str], log: logging.Logger) -> Optional[int]:
    api = _api_key()
    if not api:
        return None
    params = {
        "api_key": api,
        "language": _LANG,
        "query": series_name,
    }
    if year_hint and year_hint.isdigit():
        params["first_air_date_year"] = year_hint
    data = _http_get_json("https://api.themoviedb.org/3/search/tv", params, _TIMEOUT)
    if not data or not data.get("results"):
        if log:
            log.debug("TMDb: keine Treffer in search/tv")
        return None
    results = data["results"]
    # Versuche exakten Namen zuerst
    for r in results:
        if r.get("name", "").lower() == series_name.lower():
            return r.get("id")
    # sonst den ersten Treffer nehmen
    return results[0].get("id")


def tmdb_get_season_episode_count(
    series_name: str,
    year_hint: Optional[str],
    season_no: Optional[int],
    log: logging.Logger,
) -> Optional[int]:
    """
    Liefert die Episodenanzahl einer Staffel laut TMDb oder None, wenn nicht verfügbar.
    Signatur passt zu main.py (4 Parameter).
    """
    if season_no is None:
        return None
    api = _api_key()
    if not api:
        return None
    sid = _tmdb_search_tv_id(series_name, year_hint, log)
    if not sid:
        return None
    params = {"api_key": api, "language": _LANG}
    data = _http_get_json(f"https://api.themoviedb.org/3/tv/{sid}/season/{season_no}", params, _TIMEOUT)
    if not data:
        return None
    eps = data.get("episodes")
    return len(eps) if isinstance(eps, list) else None
