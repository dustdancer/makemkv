# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Tuple


def sanitize_filename(name: str) -> str:
    name = name.strip()
    name = re.sub(r"[\\/:\*\?\"<>\|\x00-\x1F]", "_", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip().rstrip("._")


def parse_name_year(base: str) -> Tuple[str, Optional[str], Optional[str]]:
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
    return sanitize_filename(name), year, version


def destination_for_movie(remux_root: Path, base: str) -> Path:
    name, year, version = parse_name_year(base)
    dir_name = f"{name} ({year})" if year else name
    return remux_root / "movies" / dir_name


def destination_for_tv(remux_root: Path, base: str, season_no: Optional[int]) -> Path:
    name, year, version = parse_name_year(base)
    series_dir = f"{name} ({year})" if year else name
    season_dir = f"season {season_no:02d}" if season_no is not None else "season ??"
    return remux_root / "tv" / series_dir / season_dir


def extract_season(s: str) -> Optional[int]:
    m = re.search(r"[Ss](?:eason)?\s*[_\-\.\s]?(\d{1,2})", s)
    if m: return int(m.group(1))
    m = re.search(r"\bS(\d{1,2})\b", s)
    return int(m.group(1)) if m else None


def extract_disc_no(s: str) -> Optional[int]:
    s = s.replace("_", " ")
    pats = [
        r"\bdisc\s*(\d{1,2})\b", r"\bdisk\s*(\d{1,2})\b", r"\bd\s*(\d{1,2})\b",
        r"\bD(\d{1,2})\b", r"\bCD\s*(\d{1,2})\b", r"\bS\d{1,2}D(\d{1,2})\b",
        r"\bDisc(\d{1,2})\b", r"\bDisk(\d{1,2})\b"
    ]
    for pat in pats:
        m = re.search(pat, s, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
    return None
