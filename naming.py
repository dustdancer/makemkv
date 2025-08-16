# naming.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import re
from pathlib import Path
from typing import Optional, Tuple

# Versuche sanitize_filename aus utils zu nutzen; bei Bedarf Fallback
try:
    from utils import sanitize_filename  # type: ignore
except Exception:  # Fallback, falls utils.sanitize_filename nicht vorhanden ist
    def sanitize_filename(name: str) -> str:
        import re as _re
        name = name.strip()
        name = _re.sub(r"[\\/:\*\?\"<>\|\x00-\x1F]", "_", name)
        name = _re.sub(r"\s+", " ", name)
        return name.strip().rstrip("._")


_SEASON_PATTERNS = [
    r"\b[Ss](?:taffel|eason)\s*(\d{1,2})\b",  # Staffel 6 / Season 6
    r"\bS(\d{1,2})\b",                        # S6
    r"\bS(\d{1,2})D\d{1,2}\b",                # S6D7  (liefert Season)
]

_DISC_PATTERNS = [
    r"\b[Dd]isc\s*(\d{1,2})\b", r"\b[Dd]isk\s*(\d{1,2})\b",
    r"\b[Dd](\d{1,2})\b", r"\bCD\s*(\d{1,2})\b",
    r"\bDvD\s*(\d{1,2})\b", r"\bDVD\s*(\d{1,2})\b",
    r"\bS\d{1,2}D(\d{1,2})\b",
]


def _extract_season(s: str) -> Optional[int]:
    s = s.replace("_", " ")
    for pat in _SEASON_PATTERNS:
        m = re.search(pat, s, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                return None
    return None


def _extract_disc(s: str) -> Optional[int]:
    s = s.replace("_", " ")
    for pat in _DISC_PATTERNS:
        m = re.search(pat, s, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                return None
    return None


def parse_name_year(base: str) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Zerlegt einen Basisnamen in (bereinigter Name, Jahr, Version).
    - Entfernt [Version]-Tags und (YYYY)
    - Entfernt Season/Staffel/Disk/DvD-Tokens wie 'Staffel 6', 'Disc 2', 'DvD 7', 'S6D7'
    """
    original = base
    name = base
    version = None
    # [Version]
    mver = re.search(r"\[(.+?)\]", name)
    if mver:
        version = mver.group(1).strip()
        name = re.sub(r"\s*\[.+?\]\s*", " ", name).strip()

    # (YYYY)
    my = re.search(r"\((\d{4})\)", name)
    year = my.group(1) if my else None
    if my:
        name = re.sub(r"\s*\(\d{4}\)\s*", " ", name).strip()

    # Season/Staffel/Disk entfernen, damit nur der Serien-/Filmtitel bleibt
    drop_tokens = [
        r"\b[Ss](?:taffel|eason)\s*\d{1,2}\b",  # Staffel 6 / Season 6
        r"\bS\d{1,2}\b",                        # S6
        r"\bS\d{1,2}D\d{1,2}\b",               # S6D7
        r"\b[Dd]isc\s*\d{1,2}\b",
        r"\b[Dd]isk\s*\d{1,2}\b",
        r"\b[Dd]\d{1,2}\b",
        r"\bCD\s*\d{1,2}\b",
        r"\bDvD\s*\d{1,2}\b",
        r"\bDVD\s*\d{1,2}\b",
    ]
    for pat in drop_tokens:
        name = re.sub(pat, " ", name, flags=re.IGNORECASE)

    # überflüssige Trennzeichen am Rand entfernen
    name = re.sub(r"[_\.\-]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip(" -_.")
    name = sanitize_filename(name)

    # Fallback: wenn das Leeren zu nichts geführt hat, nimm Original bereinigt
    if not name:
        name = sanitize_filename(original)

    return name, year, version


def destination_for_movie(remux_root: Path, base: str) -> Path:
    """
    Zielordner für Filme:  .../remux/movies/<Titel (Jahr)>
    """
    name, year, _ = parse_name_year(base)
    dir_name = f"{name} ({year})" if year else name
    return Path(remux_root) / "movies" / dir_name


def destination_for_tv(remux_root: Path, base: str, season_no: Optional[int] = None) -> Path:
    """
    Zielordner für TV:  .../remux/tv/<Serienname (Jahr)>/season XX
    - Season wird aus season_no übernommen oder aus base (Staffel/Season/Sxx) ermittelt.
    - Falls nicht ermittelbar: 'season ??'
    """
    series_name, year, _ = parse_name_year(base)
    s = season_no if season_no is not None else _extract_season(base)
    series_dir = f"{series_name} ({year})" if year else series_name
    season_dir = f"season {s:02d}" if isinstance(s, int) else "season ??"
    return Path(remux_root) / "tv" / series_dir / season_dir


# Optional – nützlich für Scanner/Logs, falls gebraucht:
def guess_from_path(path_or_name: str) -> Tuple[str, Optional[int], Optional[int]]:
    """
    Extrahiert (Serien-/Filmtitel, Season, Disc) heuristisch aus einem Pfad oder Namen.
    Titel ist bereits von Tokens wie 'Staffel 6'/'Disc 2' befreit.
    """
    base = Path(path_or_name).name
    title, _, _ = parse_name_year(base)
    season = _extract_season(base)
    disc = _extract_disc(base)
    return title, season, disc
