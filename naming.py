# naming.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import re
from pathlib import Path
from typing import Optional, Tuple

__all__ = [
    "sanitize_filename",
    "parse_name_year",
    "extract_season",
    "extract_disc_no",
    "fallback_series_info",
]

# -- kleine Helfer --

def sanitize_filename(name: str) -> str:
    name = name.strip()
    name = re.sub(r"[\\/:\*\?\"<>\|\x00-\x1F]", "_", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip().rstrip("._-")

def parse_name_year(base: str) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Zerlegt "Titel (2001) [Version]" in (Titel, Jahr, Version). Alles optional.
    """
    name = base
    version = None

    mver = re.search(r"\[(.+?)\]", name)
    if mver:
        version = mver.group(1).strip()
        name = re.sub(r"\s*\[.+?\]\s*", " ", name).strip()

    myear = re.search(r"\((\d{4})\)", name)
    year = myear.group(1) if myear else None
    if myear:
        name = re.sub(r"\s*\(\d{4}\)\s*", " ", name).strip()

    name = sanitize_filename(name)
    return name, year, version

# -- Season/Disc aus Strings extrahieren --

_SEASON_PATTERNS = (
    r"(?i)\bstaffel\s*(\d{1,2})\b",
    r"(?i)\bseason\s*(\d{1,2})\b",
    r"(?i)\bs(\d{1,2})\b",
    r"(?i)s(\d{1,2})d(\d{1,2})",  # kombiniert; liefert Season in group(1)
)

_DISC_PATTERNS = (
    r"(?i)\bdvd\s*(\d{1,2})\b",
    r"(?i)\bdisc\s*(\d{1,2})\b",
    r"(?i)\bdisk\s*(\d{1,2})\b",
    r"(?i)\bs\d{1,2}d(\d{1,2})\b",  # SxxDyy
    r"(?i)s\d{1,2}d(\d{1,2})",      # SxxDyy (ohne Wortgrenzen – für DSNS6D7 etc.)
    r"(?i)\bD(\d{1,2})\b",          # D7
    r"(?i)D(\d{1,2})",              # D7 (ohne \b – greift bei z.B. DSNS6D7)
)

def extract_season(s: str) -> Optional[int]:
    s_norm = s.replace("_", " ")
    for pat in _SEASON_PATTERNS:
        m = re.search(pat, s_norm)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
    return None

def extract_disc_no(s: str) -> Optional[int]:
    s_norm = s.replace("_", " ")
    for pat in _DISC_PATTERNS:
        m = re.search(pat, s_norm)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
    return None

# -- Serienname (Fallback) aus Verzeichnisstruktur ermitteln --

_TOKEN_PAT = re.compile(
    r"(?ix)"
    r"(?:\b(?:staffel|season)\s*\d{1,2}\b)"
    r"|(?:\bS\d{1,2}\b)"
    r"|(?:\bS\d{1,2}D\d{1,2}\b)"
    r"|(?:\b(?:dvd|disc|disk)\s*\d{1,2}\b)"
    r"|(?:\bD\d{1,2}\b)"
    r"|(?:\(\d{4}\))"
    r"|(?:\[[^\]]+\])"
)

def _strip_tokens(name: str) -> str:
    # entfernt Season/Disc/Jahr/Klammer-Teile
    s = _TOKEN_PAT.sub(" ", name)
    s = re.sub(r"[-_.]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return sanitize_filename(s)

def _first_nonempty(*cands: Optional[str]) -> Optional[str]:
    for c in cands:
        if c:
            c2 = c.strip()
            if c2:
                return c2
    return None

def fallback_series_info(item_root: Path, name_hint: Optional[str] = None) -> Tuple[str, Optional[int], Optional[int]]:
    """
    Leitet bei TV-Fällen aus der Ordnerstruktur robuste Defaults ab.
    Beispiel:
      ".../tv/dvd/Star Trek - Deep Space Nine Staffel 6 DvD 7/DSNS6D7/VIDEO_TS"
      → ("Star Trek - Deep Space Nine", 6, 7)
    """
    # Kandidaten-Strings von unten nach oben
    parts = []
    p = item_root
    for _ in range(5):  # die letzten ~5 Ebenen reichen hier typischerweise aus
        if p is None:
            break
        parts.append(p.name)
        if p.parent == p:
            break
        p = p.parent
    if name_hint:
        parts.insert(0, name_hint)

    season: Optional[int] = None
    disc: Optional[int] = None
    for s in parts:
        if season is None:
            season = extract_season(s or "")
        if disc is None:
            disc = extract_disc_no(s or "")

    # Serienbasis: erste Ebene, die nach dem Stripping nicht leer ist (meist item_root)
    series_name = None
    for s in (item_root.name, item_root.parent.name if item_root.parent else "", name_hint or ""):
        base = _strip_tokens(s or "")
        if base:
            series_name = base
            break

    # Falls trotzdem nichts: als allerletztes die erste nicht-leere Ebene nehmen
    series_name = _first_nonempty(series_name, name_hint, item_root.name) or "Unbenannte Serie"
    return series_name, season, disc
