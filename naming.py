# naming.py
from __future__ import annotations
import re
from pathlib import Path
from typing import Optional, Tuple

# ---------------------------
# Filename/Name Utilities
# ---------------------------

def sanitize_filename(name: str) -> str:
    """Entfernt problematische Zeichen für Dateinamen, trimmt/normalisiert Whitespace."""
    name = name.strip()
    # Windows-forbidden + Steuerzeichen
    name = re.sub(r'[\\/:\*\?"<>\|\x00-\x1F]', "_", name)
    # Mehrfach-Whitespace reduzieren
    name = re.sub(r"\s+", " ", name)
    return name.strip().rstrip("._-")

def parse_name_year(base: str) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Extrahiert Name + Jahr + (optionale) Versionsbezeichnung in eckigen Klammern.
    Beispiele:
      "Blade Runner (1982) [Final Cut]" -> ("Blade Runner", "1982", "Final Cut")
      "Heat (1995)"                      -> ("Heat", "1995", None)
      "Dune"                             -> ("Dune", None, None)
    """
    name = base
    version = None

    # [Version] herausziehen
    mver = re.search(r"\[(.+?)\]", name)
    if mver:
        version = mver.group(1).strip()
        name = re.sub(r"\s*\[.+?\]\s*", " ", name).strip()

    # (YYYY) herausziehen
    my = re.search(r"\((\d{4})\)", name)
    year = my.group(1) if my else None
    if my:
        name = re.sub(r"\s*\(\d{4}\)\s*", " ", name).strip()

    name = sanitize_filename(name)
    return name, year, version

# ---------------------------
# TV-Parsing (Season/Disc)
# ---------------------------

def extract_season(s: str) -> Optional[int]:
    """
    Versucht eine Season-Nummer zu erkennen.
    Unterstützt u.a.: "Season 6", "S6", "Staffel 6", "S 06".
    """
    # Deutsch/Englisch
    m = re.search(r"(?i)\b(?:staffel|season)\s*[_\-\.\s]?(\d{1,2})\b", s)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    # Kurzform "S06" / "S6"
    m = re.search(r"(?i)\bS\s*0?(\d{1,2})\b", s)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None

def extract_disc_no(s: str) -> Optional[int]:
    """
    Versucht eine Disc-Nummer zu erkennen.
    Unterstützt u.a.: "Disc 7", "Disk 2", "D7", "DVD 3", "DvD 5", "S06D2".
    """
    s = s.replace("_", " ")
    patterns = [
        r"(?i)\bdisc\s*0?(\d{1,2})\b",
        r"(?i)\bdisk\s*0?(\d{1,2})\b",
        r"(?i)\bdvd\s*0?(\d{1,2})\b",       # "DVD 3" / "DvD 3"
        r"(?i)\bd\s*0?(\d{1,2})\b",         # "D7"
        r"(?i)\bS\d{1,2}D0?(\d{1,2})\b",    # "S06D2"
        r"(?i)\bDisc0?(\d{1,2})\b",
        r"(?i)\bDisk0?(\d{1,2})\b",
    ]
    for pat in patterns:
        m = re.search(pat, s)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return None
    return None

def _strip_tokens_for_series_name(text: str) -> str:
    """Entfernt Season-/Disc-Tokens aus einem Serienordnernamen, um den reinen Serientitel zu erhalten."""
    t = text
    # Season/Staffel entfernen
    t = re.sub(r"(?i)\b(?:staffel|season)\s*\d{1,2}\b", " ", t)
    t = re.sub(r"(?i)\bS\s*\d{1,2}\b", " ", t)  # S06
    # Disc/DvD entfernen
    t = re.sub(r"(?i)\b(?:disc|disk|dvd)\s*\d{1,2}\b", " ", t)
    t = re.sub(r"(?i)\bD\s*\d{1,2}\b", " ", t)  # D7
    # Doppel-/Sonderzeichen/Whitespace aufräumen
    t = t.replace("_", " ").replace(".", " ")
    t = re.sub(r"\s+", " ", t).strip(" -_.")
    return sanitize_filename(t)

def fallback_series_info(path: Path) -> Tuple[str, Optional[int], Optional[int]]:
    """
    Heuristik: Leitet Serienname, Season und Disc aus Pfadbestandteilen ab,
    z.B.:
      ".../tv/dvd/Star Trek - Deep Space Nine Staffel 6 DvD 7/VIDEO_TS" ->
         ("Star Trek - Deep Space Nine", 6, 7)
    """
    base = path if path.is_dir() else path.parent

    # Kandidatennamen (vom spezifischen Ordner hochlaufen)
    names = [
        base.name,
        base.parent.name if base.parent else "",
        base.parent.parent.name if base.parent and base.parent.parent else "",
    ]

    season = None
    disc   = None
    series_title = None

    # 1) Erst Season/Disk ableiten
    for n in names:
        if season is None:
            season = extract_season(n)
        if disc is None:
            disc = extract_disc_no(n)

    # 2) Serientitel ableiten – nimm ersten sinnvollen Kandidaten und streife Tokens ab
    for n in names:
        t = _strip_tokens_for_series_name(n)
        # Heuristik: ein sinnvoller Titel hat mehr als 2 Zeichen
        if len(t) > 2:
            series_title = t
            break

    if not series_title:
        series_title = _strip_tokens_for_series_name(base.name)

    return series_title, season, disc

# ---------------------------
# Zielpfade (Movies/TV)
# ---------------------------

def destination_for_movie(remux_root: Path, base: str) -> Path:
    """Zielordner für Movies:  .../remux/movies/<Name (YYYY)>"""
    name, year, _version = parse_name_year(base)
    dir_name = f"{name} ({year})" if year else name
    return Path(remux_root) / "movies" / dir_name

def destination_for_tv(remux_root: Path, base: str, season_no: Optional[int]) -> Path:
    """Zielordner für TV:      .../remux/tv/<Serie (YYYY)>/season XX"""
    name, year, _version = parse_name_year(base)
    series_dir = f"{name} ({year})" if year else name
    season_dir = f"season {season_no:02d}" if season_no is not None else "season ??"
    return Path(remux_root) / "tv" / series_dir / season_dir
