# file: makemkv/naming.py
from __future__ import annotations

"""
Namens- und Pfad-Helfer für Filme & Serien.

- Zerlegt Roh-Namen (Release/Ordner) in: (name, year, version)
- Extrahiert Season-/Disc-Informationen aus gängigen Mustern
- Liefert Zielordner unterhalb des REMUX-Roots
- Formatiert Dateinamen (SxxExx, Doppel-Episoden, Trailer, Extras)
- Sorgt dafür, dass es NIE wieder 'season ??' gibt → bei unbekannt: 'season 00'
"""

import re
from pathlib import Path
from typing import Optional, Tuple

from .config import CONFIG

# Optional: utils verwenden – mit sicheren Fallbacks
try:
    from .utils import ensure_dir as _ensure_dir, sanitize_filename as _sanitize_filename
except Exception:  # pragma: no cover
    def _ensure_dir(p: Path) -> None:
        p.mkdir(parents=True, exist_ok=True)

    def _sanitize_filename(name: str) -> str:
        name = name.strip()
        name = re.sub(r'[\\/:\*\?"<>\|\x00-\x1F]', "_", name)
        name = re.sub(r"\s+", " ", name)
        return name.strip().rstrip("._")

__all__ = [
    "sanitize_filename",
    "parse_name_year_version",
    "extract_season",
    "extract_disc_no",
    "season_dir_name",
    "series_dir_name",
    "movie_dir_name",
    "destination_for_movie",
    "destination_for_tv",
    "format_movie_main",
    "format_movie_trailer",
    "format_movie_extra",
    "format_tv_episode",
    "format_tv_double",
    "format_tv_trailer",
    "format_tv_extra",
    "make_unique",
]


# ---------------------------------------------------------------------------
# Sanitize
# ---------------------------------------------------------------------------

def sanitize_filename(name: str) -> str:
    """Datei-/Ordnernamen für Windows/Posix säubern."""
    return _sanitize_filename(name)


# ---------------------------------------------------------------------------
# Parsing: Name / Jahr / Version
# ---------------------------------------------------------------------------

def parse_name_year_version(base: str) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Nimmt einen Basisnamen (Ordner/Release) und extrahiert:
      - name:   bereinigt, ohne (YYYY) und ohne [Version/Edition]
      - year:   4-stellig, falls vorhanden in Klammern
      - version: Inhalt der ersten [eckigen Klammern], z.B. 'Extended Cut'
    Beispiel:
      'Blade Runner (1982) [Final Cut] 1080p' → ('Blade Runner 1080p', '1982', 'Final Cut')
    """
    name = base
    version = None

    # Erste [..] als "Version/Edition" interpretieren
    mver = re.search(r"\[(.+?)\]", name)
    if mver:
        version = mver.group(1).strip()
        name = re.sub(r"\s*\[.+?\]\s*", " ", name).strip()

    # (YYYY) isolieren
    my = re.search(r"\((\d{4})\)", name)
    year = my.group(1) if my else None
    if my:
        name = re.sub(r"\s*\(\d{4}\)\s*", " ", name).strip()

    name = sanitize_filename(name)
    return name, year, version


# ---------------------------------------------------------------------------
# Season / Disc-Erkennung
# ---------------------------------------------------------------------------

def extract_season(s: str) -> Optional[int]:
    """
    Sucht nach Staffel/Season-Nummern:
      - 'Season 1', 'S01', 'S1', 'Staffel 2', 'S02E03' → 1 bzw. 2 bzw. 2
    """
    # Eindeutig: SxxExx → Season = Sxx
    m = re.search(r"\b[Ss](\d{1,2})[ _\-\.]*[Ee]\d{1,2}\b", s)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None

    pats = [
        r"[Ss](?:eason)?\s*[_\-\.\s]?(\d{1,2})",   # Season 1 / S01
        r"[Ss]taffel\s*(\d{1,2})",                 # Staffel 1
        r"\bS(\d{1,2})\b",                         # S1
    ]
    for p in pats:
        m = re.search(p, s, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                return None
    return None


def extract_disc_no(s: str) -> Optional[int]:
    """
    Sucht nach Disc-/Disk-/Dxx Mustern:
      - 'Disc 1', 'Disk 2', 'D1', 'CD2', 'S01D02'
    """
    s = s.replace("_", " ")
    pats = [
        r"\bdisc\s*(\d{1,2})\b",
        r"\bdisk\s*(\d{1,2})\b",
        r"\bd\s*(\d{1,2})\b",
        r"\bD(\d{1,2})\b",
        r"\bCD\s*(\d{1,2})\b",
        r"\bS\d{1,2}D(\d{1,2})\b",
        r"\bDisc(\d{1,2})\b",
        r"\bDisk(\d{1,2})\b",
    ]
    for p in pats:
        m = re.search(p, s, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                return None
    return None


# ---------------------------------------------------------------------------
# Zielordner & -namen
# ---------------------------------------------------------------------------

def season_dir_name(season_no: Optional[int]) -> str:
    """
    Liefert 'season 01' … 'season 99'.
    Bei unbekannter Staffel → 'season 00' (keine '??' mehr!)
    """
    if season_no is None:
        return "season 00"
    try:
        return f"season {int(season_no):02d}"
    except Exception:
        return "season 00"


def series_dir_name(series_base: str) -> str:
    """Serien-Ordnername (optional ohne Jahr/Version, aber mit sonstigen Tags)."""
    name, _, _ = parse_name_year_version(series_base)
    return sanitize_filename(name)


def movie_dir_name(movie_base: str) -> str:
    """Film-Ordnername: bevorzugt 'Titel (YYYY)' wenn vorhanden."""
    name, year, _ = parse_name_year_version(movie_base)
    return sanitize_filename(f"{name} ({year})" if year else name)


def destination_for_movie(remux_root: Path, base_display: str) -> Path:
    """
    Zielordner für Filme unterhalb des Remux-Roots.
    Beispiel: <REMUX>/movies/Blade Runner (1982)/
    """
    return Path(remux_root) / "movies" / movie_dir_name(base_display)


def destination_for_tv(remux_root: Path, series_base: str, season_no: Optional[int]) -> Path:
    """
    Zielordner für Serien unterhalb des Remux-Roots.
    Beispiel: <REMUX>/tv/Series Name/season 01/
    """
    series = series_dir_name(series_base)
    return Path(remux_root) / "tv" / series / season_dir_name(season_no)


# ---------------------------------------------------------------------------
# Dateinamen-Formatter
# ---------------------------------------------------------------------------

def format_movie_main(name: str, year: Optional[str] = None, version: Optional[str] = None) -> str:
    """Hauptfilm: 'Name (YYYY)[Version].mkv' (Version in eckigen Klammern, falls gesetzt)."""
    n = sanitize_filename(f"{name} ({year})" if year else name)
    if version:
        n = f"{n} [{sanitize_filename(version)}]"
    return f"{n}.mkv"


def format_movie_trailer(name: str, index: int = 1) -> str:
    """Trailer: 'Name_trailer[-2].mkv'"""
    suf = "" if index == 1 else f"-{index}"
    return f"{sanitize_filename(name)}_trailer{suf}.mkv"


def format_movie_extra(name: str, index: int) -> str:
    """Extras: 'Name [bonusmaterial] - extraNN.mkv'"""
    return f"{sanitize_filename(name)} [bonusmaterial] - extra{int(index):02d}.mkv"


def format_tv_episode(series: str, season_no: Optional[int], ep_no: int) -> str:
    """Episode: 'Series – SxxExx.mkv' bzw. 'Series – Exx.mkv' ohne Season."""
    base = sanitize_filename(series)
    if season_no is None:
        return f"{base} – E{int(ep_no):02d}.mkv"
    return f"{base} – S{int(season_no):02d}E{int(ep_no):02d}.mkv"


def format_tv_double(series: str, season_no: Optional[int], ep_from: int, ep_to: int) -> str:
    """Doppel-Episode: 'Series – SxxExx-Eyy.mkv' bzw. 'Series – Exx-Eyy.mkv' ohne Season."""
    base = sanitize_filename(series)
    if season_no is None:
        return f"{base} – E{int(ep_from):02d}-E{int(ep_to):02d}.mkv"
    return f"{base} – S{int(season_no):02d}E{int(ep_from):02d}-E{int(ep_to):02d}.mkv"


def format_tv_trailer(series: str, index: int = 1) -> str:
    """Serien-Trailer: 'Series_trailer[-2].mkv'"""
    suf = "" if index == 1 else f"-{index}"
    return f"{sanitize_filename(series)}_trailer{suf}.mkv"


def format_tv_extra(series: str, index: int) -> str:
    """Serien-Extras: 'Series [bonusmaterial] - extraNN.mkv'"""
    return f"{sanitize_filename(series)} [bonusmaterial] - extra{int(index):02d}.mkv"


# ---------------------------------------------------------------------------
# Kollision vermeiden
# ---------------------------------------------------------------------------

def make_unique(dst: Path) -> Path:
    """
    Falls Pfad bereits existiert, hänge ' (n)' an, bis er frei ist.
    """
    dst = Path(dst)
    if not dst.exists():
        return dst
    stem, ext = dst.stem, dst.suffix
    i = 1
    while True:
        cand = dst.with_name(f"{stem} ({i}){ext}")
        if not cand.exists():
            return cand
        i += 1


# ---------------------------------------------------------------------------
# (optionaler) High-Level Helper
# ---------------------------------------------------------------------------

def ensure_tv_destination(remux_root: Path, series_base: str, season_no: Optional[int]) -> Path:
    """
    Liefert den TV-Zielordner und erstellt ihn bei Bedarf.
    """
    dst = destination_for_tv(remux_root, series_base, season_no)
    _ensure_dir(dst)
    return dst


def ensure_movie_destination(remux_root: Path, movie_base: str) -> Path:
    """
    Liefert den Movie-Zielordner und erstellt ihn bei Bedarf.
    """
    dst = destination_for_movie(remux_root, movie_base)
    _ensure_dir(dst)
    return dst
