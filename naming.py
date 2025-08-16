# -*- coding: utf-8 -*-
from __future__ import annotations
import re
from pathlib import Path
from typing import Optional, Tuple
from utils import sanitize_filename

def parse_name_year(base: str) -> Tuple[str, Optional[str], Optional[str]]:
    """Entfernt '(YYYY)' und '[Version]' aus dem Anzeigenamen; liefert (name, year, version)."""
    name = base; version = None
    mver = re.search(r"\[(.+?)\]", base)
    if mver:
        version = mver.group(1).strip()
        name = re.sub(r"\s*\[.+?\]\s*", " ", name).strip()
    my = re.search(r"\((\d{4})\)", base)
    year = my.group(1) if my else None
    if my:
        name = re.sub(r"\s*\(\d{4}\)\s*", " ", name).strip()
    name = sanitize_filename(name)
    return name, year, version

def destination_for_movie(remux_root: Path, base: str) -> Path:
    name, year, _ = parse_name_year(base)
    dir_name = f"{name} ({year})" if year else name
    return remux_root / "movies" / dir_name

def destination_for_tv(remux_root: Path, base: str, season_no: Optional[int]) -> Path:
    name, year, _ = parse_name_year(base)
    series_dir = f"{name} ({year})" if year else name
    # nie "season ??" – stattdessen "season 00"
    season_dir = f"season {season_no:02d}" if season_no is not None else "season 00"
    return remux_root / "tv" / series_dir / season_dir
