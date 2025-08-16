# -*- coding: utf-8 -*-
"""
Naming-/Parsing-Helfer für das MakeMKV-Remux-Projekt.

Enthält:
- sanitize_filename
- extract_season
- extract_disc_no
- parse_name_year
- fallback_series_info  ← robust gegenüber Path-Objekten
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Optional, Tuple, Union


def sanitize_filename(name: str) -> str:
    """Macht einen string dateisystemtauglich (ohne Sonderzeichen/Mehrfachspaces)."""
    name = name.strip()
    name = re.sub(r'[\\/:\*\?"<>\|\x00-\x1F]', "_", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip().rstrip("._- ")


def extract_season(s: str) -> Optional[int]:
    """
    Extrahiert eine Staffelnummer aus einem String.
    Erlaubt u.a.:
      - 'Staffel 1', 'Season 02', 'S01', 's1'
    """
    m = re.search(r"(?i)\bStaffel\s*(\d{1,2})\b", s)
    if m:
        return int(m.group(1))
    m = re.search(r"(?i)\bSeason\s*(\d{1,2})\b", s)
    if m:
        return int(m.group(1))
    m = re.search(r"(?i)\bS(?:eason)?\s*[_\-\.\s]?(\d{1,2})\b", s)
    if m:
        return int(m.group(1))
    return None


def extract_disc_no(s: str) -> Optional[int]:
    """
    Extrahiert eine Disc-/DVD-Nummer aus einem String.
    Erlaubt u.a.:
      - 'Disc 1', 'Disk 2', 'DVD 3', 'DvD 4', 'D 5', 'D5', 'S1D2'
    """
    s = s.replace("_", " ")
    patterns = [
        r"(?i)\bDisc\s*(\d{1,2})\b",
        r"(?i)\bDisk\s*(\d{1,2})\b",
        r"(?i)\bDVD\s*(\d{1,2})\b",
        r"(?i)\bDvD\s*(\d{1,2})\b",
        r"(?i)\bD\s*(\d{1,2})\b",
        r"(?i)\bD(\d{1,2})\b",
        r"(?i)\bS\d{1,2}D(\d{1,2})\b",
        r"(?i)\bCD\s*(\d{1,2})\b",
    ]
    for pat in patterns:
        m = re.search(pat, s)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
    return None


def parse_name_year(base: str) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Zerlegt 'Titel (1999) [Version]' in (Titel, Jahr, Version).
    Klammern werden entfernt und Titel sanitiziert.
    """
    name = base
    version = None

    mver = re.search(r"\[(.+?)\]", name)
    if mver:
        version = mver.group(1).strip()
        name = re.sub(r"\s*\[.+?\]\s*", " ", name).strip()

    my = re.search(r"\((\d{4})\)", name)
    year = my.group(1) if my else None
    if my:
        name = re.sub(r"\s*\(\d{4}\)\s*", " ", name).strip()

    name = sanitize_filename(name)
    return name, year, version


def _clean_series_base(series_base: str) -> str:
    """
    Entfernt Staffel-/Disc-Tokens aus einem Serien-Basisnamen.
    """
    s = series_base

    # SxxDyy-Kombis zuerst
    s = re.sub(r"(?i)\bS\d{1,2}D\d{1,2}\b", "", s)

    # Staffel/Season
    s = re.sub(r"(?i)\bStaffel\s*\d{1,2}\b", "", s)
    s = re.sub(r"(?i)\bSeason\s*\d{1,2}\b", "", s)
    s = re.sub(r"(?i)\bS(?:eason)?\s*[_\-\.\s]?\d{1,2}\b", "", s)

    # Disc/Disk/DVD/DvD/D/ D##
    s = re.sub(r"(?i)\bDisc\s*\d{1,2}\b", "", s)
    s = re.sub(r"(?i)\bDisk\s*\d{1,2}\b", "", s)
    s = re.sub(r"(?i)\bDVD\s*\d{1,2}\b", "", s)
    s = re.sub(r"(?i)\bDvD\s*\d{1,2}\b", "", s)
    s = re.sub(r"(?i)\bD\s*\d{1,2}\b", "", s)
    s = re.sub(r"(?i)\bD\d{1,2}\b", "", s)

    # Mehrfach-Trenner/Spaces normalisieren
    s = re.sub(r"[ \t\-_.]+", " ", s)
    return sanitize_filename(s).strip()


def fallback_series_info(item_root: Union[str, Path]) -> Tuple[str, Optional[int], Optional[int]]:
    """
    Liefert (Serienname_ohne_Tokens, Staffel, Disc) aus einem Ordnernamen/F Pfad.
    Robuste Annahmen für DS9-Beispiele wie:
      - 'Star Trek - Deep Space Nine Staffel 1 DvD 1'
      - 'STDSNS1D2'
      - 'DSNS6D4'
    Akzeptiert Path-Objekte oder Strings (fix für TypeError bei re.sub).
    """
    # Robust in Path wandeln
    p = item_root if isinstance(item_root, Path) else Path(str(item_root))
    series_base = p.name
    parent_name = p.parent.name

    # Saison / Disc aus Basis *oder* Parent ziehen (falls Infos im Elternordner stehen)
    season = extract_season(series_base) or extract_season(parent_name) or None
    disc = extract_disc_no(series_base) or extract_disc_no(parent_name) or None

    # Seriennamen bereinigen (Tokens entfernen)
    cleaned = _clean_series_base(series_base)
    if not cleaned:
        # Fallback: Elternnamen säubern
        cleaned = _clean_series_base(parent_name)

    return cleaned, season, disc
