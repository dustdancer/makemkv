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
    "destination_for_movie",
    "destination_for_tv",
]


# ---------- Helpers ----------

def sanitize_filename(name: str) -> str:
    """Entfernt unzulässige Zeichen und trimmt Whitespace/Punkte/Unterstriche am Ende."""
    name = name.strip()
    name = re.sub(r'[\\/:\*\?"<>\|\x00-\x1F]', "_", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip().rstrip("._- ")


def parse_name_year(base: str) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Zerlegt 'Titel (1998) [Director's Cut]' in (Titel, 1998, Director's Cut).
    Klammern sind optional.
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


# ---------- Season / Disc ----------

def extract_season(s: str | Path) -> Optional[int]:
    """Findet Staffelangaben wie 'Staffel 2', 'Season 2', 'S02' in String oder Pfad."""
    txt = str(s)
    # Deutsch + Englisch
    m = re.search(r"(?i)\b(?:staffel|season)\s*(\d{1,2})\b", txt)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    # S02 / s2
    m = re.search(r"(?i)\bS(\d{1,2})\b", txt)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None


def extract_disc_no(s: str | Path) -> Optional[int]:
    """Findet Disc-Angaben wie 'Disc 2', 'D2', 'S02D05' in String oder Pfad."""
    txt = str(s).replace("_", " ")
    patterns = [
        r"(?i)\bdisc\s*(\d{1,2})\b",
        r"(?i)\bdisk\s*(\d{1,2})\b",
        r"(?i)\bDVD\s*(\d{1,2})\b",
        r"(?i)\bBD\s*(\d{1,2})\b",
        r"(?i)\bD(\d{1,2})\b",
        r"(?i)\bCD\s*(\d{1,2})\b",
        r"(?i)\bS\d{1,2}D(\d{1,2})\b",  # z.B. STDSNS1D2
    ]
    for pat in patterns:
        m = re.search(pat, txt)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
    return None


# ---------- Fallback Serieninfos aus Ordnernamen ----------

def _strip_series_tokens(s: str) -> str:
    """Entfernt Staffel-/Disc-/Medium-Tokens aus einem Text für Serienbasisnamen."""
    s2 = s
    s2 = re.sub(r"(?i)\b(?:staffel|season)\s*\d{1,2}\b", "", s2)
    s2 = re.sub(r"(?i)\bS\d{1,2}\b", "", s2)
    s2 = re.sub(r"(?i)\bS\d{1,2}D\d{1,2}\b", "", s2)
    s2 = re.sub(r"(?i)\b(?:disc|disk|dvd|bd|bluray|blu[- ]?ray)\b", "", s2)
    s2 = re.sub(r"(?i)\bD\d{1,2}\b", "", s2)
    s2 = re.sub(r"[_\.\-]+", " ", s2)
    s2 = re.sub(r"\s{2,}", " ", s2)
    return s2.strip(" -_.\t\r\n")


def fallback_series_info(item_root: str | Path) -> Tuple[str, Optional[int], Optional[int]]:
    """
    Leitet (Serienname, Staffel, Disc) aus Ordner-/Dateinamen ab.
    - Robust gegen Pfadübergabe als Path
    - Nutzt Elternordner als primäre Quelle für den Seriennamen
    """
    p = Path(item_root)
    name = p.name
    parent = p.parent.name if p.parent else ""
    grand = p.parent.parent.name if p.parent and p.parent.parent else ""

    season = extract_season(name) or extract_season(parent) or extract_season(grand)
    disc = extract_disc_no(name) or extract_disc_no(parent) or extract_disc_no(grand)

    # Kandidaten für Serienbasis
    candidates = [
        _strip_series_tokens(parent),
        _strip_series_tokens(name),
        _strip_series_tokens(grand),
        _strip_series_tokens(f"{parent} {name}"),
    ]
    series_base = max((c for c in candidates if c), key=len, default=name)
    series_base = sanitize_filename(series_base) if series_base else sanitize_filename(name)

    return series_base, season, disc


# ---------- Destination-Pfade ----------

def destination_for_movie(remux_root: Path, base: str) -> Path:
    """Zielordner für Filme: remux_root/movies/'Titel (Jahr)'."""
    name, year, _ = parse_name_year(base)
    dir_name = f"{name} ({year})" if year else name
    return Path(remux_root) / "movies" / dir_name


def destination_for_tv(remux_root: Path, base: str, season_no: Optional[int]) -> Path:
    """Zielordner für TV: remux_root/tv/'Serie (Jahr)'/'season XX'."""
    name, year, _ = parse_name_year(base)
    series_dir = f"{name} ({year})" if year else name
    season_part = f"season {season_no:02d}" if season_no is not None else "season ??"
    return Path(remux_root) / "tv" / series_dir / season_part
