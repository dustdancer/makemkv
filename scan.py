# scanner.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import re

from naming import sanitize_filename, extract_season, extract_disc_no, fallback_series_info

__all__ = ["find_sources"]

def _contains_dvd_files(p: Path) -> bool:
    # DVD-Strukturen haben entweder einen VIDEO_TS-Ordner ODER die VIDEO_TS.* / VTS_* Dateien direkt im Wurzelordner
    if (p / "VIDEO_TS").is_dir():
        return True
    # Direkt im Ordner?
    if (p / "VIDEO_TS.IFO").exists() or (p / "VIDEO_TS.BUP").exists():
        return True
    # Typische VTS_* Dateien (mind. eine IFO)
    for cand in p.glob("VTS_*_0.IFO"):
        if cand.is_file():
            return True
    return False

def _is_disc_folder(p: Path) -> Optional[str]:
    """
    Ermittelt, ob der gegebene Ordner eine Disc-Struktur enthält.
    Rückgabe:
      'bdmv' | 'dvd' | None
    """
    # Blu-ray
    if (p / "BDMV").is_dir() or p.name.upper() == "BDMV":
        return "bdmv"
    # DVD
    if p.name.upper() == "VIDEO_TS" or _contains_dvd_files(p):
        return "dvd"
    return None

def _effective_disc_path(p: Path, kind: str) -> Tuple[Path, Path]:
    """
    Liefert (item_root, eff_path) – also den logischen "Disc-Ordner" (item_root)
    und den Pfad, der an MakeMKV übergeben werden soll (eff_path).
    """
    if kind == "bdmv":
        if p.name.upper() == "BDMV":
            return p.parent, p  # item_root ist der Ordner über BDMV
        if (p / "BDMV").is_dir():
            return p, (p / "BDMV")
    elif kind == "dvd":
        if p.name.upper() == "VIDEO_TS":
            return p.parent, p
        if (p / "VIDEO_TS").is_dir():
            return p, (p / "VIDEO_TS")
        # DVD-Dateien direkt im Ordner
        if _contains_dvd_files(p):
            return p, p
    return p, p

def _category_for(transcode_root: Path, root_p: Path) -> Optional[str]:
    try:
        rel = root_p.relative_to(transcode_root)
    except Exception:
        return None
    parts = [x.lower() for x in rel.parts]
    if "tv" in parts:
        return "tv"
    if "movies" in parts or "movie" in parts:
        return "movies"
    return None

def _append_source(
    sources: List[Dict],
    kind: str,
    eff_path: Path,
    item_root: Path,
    category: Optional[str],
    display: str,
    season: Optional[int],
    disc: Optional[int],
):
    sources.append({
        "kind": kind,           # "iso" oder "file"
        "path": eff_path,       # Pfad, den MakeMKV bekommt
        "category": category,   # "tv" | "movies" | None
        "display": display,     # Anzeigename / Serienname (bei TV bereits bereinigt)
        "item_root": item_root, # eigentlicher Disc-Ordner
        "season": season,
        "disc": disc,
    })

def find_sources(transcode_root: Path, log) -> List[Dict]:
    """
    Sucht unterhalb von .../transcode alle ISO- und Disc-Quellen.
    - DVD-Erkennung robust (VIDEO_TS-Ordner ODER VIDEO_TS/VTS_* direkt im Ordner)
    - Bei TV wird 'display' bereits auf Serien-Basisnamen gesetzt (Fallback aus Ordnernamen),
      Season/Disc werden – falls möglich – aus dem Pfad gelesen.
    """
    log.info(f"Scan: {transcode_root}")
    sources: List[Dict] = []

    for root, dirs, files in os.walk(transcode_root):
        root_p = Path(root)

        # 1) Disc-Ordner (DVD/BDMV) – funktioniert auch bei DSNS6D7 mit VIDEO_TS-Dateien direkt im Ordner
        kind_here = _is_disc_folder(root_p)
        if kind_here:
            item_root, eff_path = _effective_disc_path(root_p, kind_here)
            category = _category_for(transcode_root, item_root)
            base_disp = sanitize_filename(item_root.name)

            # TV-Fallback: Serienname/Season/Disc aus Ordnerstruktur ableiten
            if category == "tv":
                series_name, s_season, s_disc = fallback_series_info(item_root)
                display = series_name
                season = s_season if s_season is not None else extract_season(item_root.name)
                disc   = s_disc   if s_disc   is not None else extract_disc_no(item_root.name)
            else:
                display = base_disp
                season = None
                disc   = extract_disc_no(item_root.name)  # für Movies i.d.R. egal

            _append_source(sources, "file", eff_path, item_root, category, display, season, disc)
            log.debug(f"Disc: kind={kind_here} | eff={eff_path} | item_root={item_root} | cat={category} | disp={display} | season={season} | disc={disc}")

        # 2) ISO-Dateien
        for f in files:
            if not f.lower().endswith(".iso"):
                continue
            p = root_p / f
            item_root = p.parent
            category = _category_for(transcode_root, item_root)

            if category == "tv":
                # namauswertung auch aus Dateinamen+Ordner
                series_name, s_season, s_disc = fallback_series_info(item_root, name_hint=p.stem)
                display = series_name
                season = s_season if s_season is not None else extract_season(p.stem)
                disc   = s_disc   if s_disc   is not None else extract_disc_no(p.stem) or extract_disc_no(item_root.name)
            else:
                display = sanitize_filename(p.stem)
                season = None
                disc   = extract_disc_no(p.stem) or extract_disc_no(item_root.name)

            _append_source(sources, "iso", p, item_root, category, display, season, disc)
            log.debug(f"ISO:   path={p} | cat={category} | disp={display} | season={season} | disc={disc}")

    # 3) Deduplizieren nach (kind, path)
    deduped: List[Dict] = []
    seen = set()
    for s in sources:
        key = (s.get("kind"), str(s.get("path")).lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(s)

    if len(deduped) != len(sources):
        log.info(f"Duplikate entfernt: {len(sources) - len(deduped)}")

    log.info(f"Scan fertig: {len(deduped)} Quelle(n)")
    return deduped
