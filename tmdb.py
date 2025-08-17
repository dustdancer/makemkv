# -*- coding: utf-8 -*-
"""
Thin-Wrapper um tmdb_client.py

Zweck:
- Bietet die erwarteten Funktionen `tmdb_is_enabled()` und
  `tmdb_get_season_episode_count(series_name, year_hint, season_no, log)`
  so wie sie in main.py importiert werden.
- Ist tolerant gegenüber unterschiedlichen Funktionsnamen/Signaturen im
  bestehenden tmdb_client.py (z.B. search_tv_id vs. tmdb_search_tv_id).
- Keine weiteren Seiteneffekte, damit wir nur den ImportError fixen.
"""

from __future__ import annotations
import os
import logging
from typing import Optional, Any

try:
    import tmdb_client as _tc  # vorhandenes Modul aus deinem Repo
except Exception:
    _tc = None  # Fallback: ohne Client -> "deaktiviert"


# ----------------------------
# Hilfsfunktionen (intern)
# ----------------------------

def _has(obj: Any, name: str) -> bool:
    return hasattr(obj, name) and callable(getattr(obj, name, None))


def _try_call(fn, *variants):
    """
    Versucht dieselbe Funktion mit unterschiedlichen Argument-Varianten
    aufzurufen, bis eine ohne TypeError/ValueError durchläuft.
    """
    for args in variants:
        try:
            return fn(*args)
        except (TypeError, ValueError):
            continue
        except Exception:
            # andere Fehler nicht weiter eskalieren – wir probieren die nächste Variante
            continue
    return None


def _search_tv_id(series_name: str, year_hint: Optional[str], log: logging.Logger) -> Optional[int]:
    """
    Findet eine TV-ID über die im tmdb_client vorhandene Suchfunktion.
    Unterstützt mehrere mögliche Funktionsnamen/Signaturen.
    """
    if _tc is None:
        return None

    candidates = [
        "tmdb_search_tv_id",
        "search_tv_id",
        "search_tv_show_id",
        "search_tv",           # evtl. Rückgabe dict -> id extrahieren
        "get_tv_id",
    ]
    for fn_name in candidates:
        if _has(_tc, fn_name):
            fn = getattr(_tc, fn_name)
            res = _try_call(
                fn,
                (series_name, year_hint, log),
                (series_name, year_hint),
                (series_name,)
            )
            # akzeptiere int oder dict mit 'id'
            if isinstance(res, int):
                return res
            if isinstance(res, dict) and "id" in res and isinstance(res["id"], int):
                return res["id"]
            # manche Implementationen liefern (id, score) o.ä.
            if isinstance(res, (list, tuple)) and res:
                first = res[0]
                if isinstance(first, int):
                    return first
                if isinstance(first, dict) and "id" in first and isinstance(first["id"], int):
                    return first["id"]
    return None


def _episodes_count_by_name(series_name: str, year_hint: Optional[str], season_no: int, log: logging.Logger) -> Optional[int]:
    """
    Nutzt – sofern vorhanden – eine by-name Funktion direkt aus tmdb_client.
    """
    if _tc is None:
        return None

    # Mögliche Funktionsnamen, die direkt Name+Season annehmen
    candidates = [
        "tmdb_get_season_episode_count",
        "get_season_episode_count_by_name",
        "season_episode_count_by_name",
    ]
    for fn_name in candidates:
        if _has(_tc, fn_name):
            fn = getattr(_tc, fn_name)
            res = _try_call(
                fn,
                (series_name, year_hint, season_no, log),
                (series_name, year_hint, season_no),
                (series_name, season_no, year_hint),
                (series_name, season_no),
            )
            if isinstance(res, int):
                return res
    return None


def _episodes_count_by_id(tv_id: int, season_no: int, log: logging.Logger) -> Optional[int]:
    """
    Nutzt eine by-id Funktion aus tmdb_client (typisch: get_season_episode_count(tv_id, season)).
    """
    if _tc is None:
        return None

    candidates = [
        "get_season_episode_count",
        "tmdb_get_season_episode_count_by_id",
        "season_episode_count",
    ]
    for fn_name in candidates:
        if _has(_tc, fn_name):
            fn = getattr(_tc, fn_name)
            res = _try_call(
                fn,
                (tv_id, season_no, log),
                (tv_id, season_no),
            )
            if isinstance(res, int):
                return res
    return None


# ----------------------------
# Öffentliche API (für main.py)
# ----------------------------

def tmdb_is_enabled() -> bool:
    """
    True, wenn ein API-Key verfügbar ist – entweder via tmdb_client
    oder via Umgebung (TMDB_API_KEY).
    """
    if _tc is not None:
        # übliche Varianten: Konstante/Attribut oder Helper
        key = getattr(_tc, "TMDB_API_KEY", None)
        if isinstance(key, str) and key.strip():
            return True
        if _has(_tc, "is_enabled"):
            try:
                return bool(_tc.is_enabled())
            except Exception:
                pass
    # Fallback: Umgebungsvariable
    return bool(os.environ.get("TMDB_API_KEY", "").strip())


def tmdb_get_season_episode_count(
    series_name: str,
    year_hint: Optional[str],
    season_no: Optional[int],
    log: logging.Logger,
) -> Optional[int]:
    """
    Liefert die Episodenanzahl für (Serie, Season), oder None, wenn nicht bestimmbar.

    Signatur bleibt exakt so, wie von deiner main.py erwartet.
    """
    if season_no is None:
        return None
    if not tmdb_is_enabled():
        return None

    # 1) Versuche direkte by-name-Implementationen (falls im Client vorhanden)
    val = _episodes_count_by_name(series_name, year_hint, season_no, log)
    if isinstance(val, int):
        return val

    # 2) Fallback: erst TV-ID suchen, dann über by-id-Funktion holen
    tv_id = _search_tv_id(series_name, year_hint, log)
    if tv_id is None:
        return None

    return _episodes_count_by_id(tv_id, season_no, log)
