# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Dict, List, Optional

from naming import sanitize_filename, extract_season, extract_disc_no


def _is_disc_folder(p: Path) -> Optional[str]:
    # Liefert "dvd" oder "bdmv" wenn ein gültiger Disc-Ordner existiert
    if (p / "BDMV").is_dir():       return "bdmv"
    if (p / "VIDEO_TS").is_dir():   return "dvd"
    if p.name.upper() == "BDMV":     return "bdmv"
    if p.name.upper() == "VIDEO_TS": return "dvd"
    return None


def _category_from_parts(parts: list[str]) -> Optional[str]:
    parts = [x.lower() for x in parts]
    if "tv" in parts:     return "tv"
    if "movies" in parts: return "movies"
    return None


def find_sources(transcode_root: Path, log: logging.Logger) -> List[Dict]:
    log.info(f"Scan: {transcode_root}")
    out: List[Dict] = []

    for root, dirs, files in os.walk(transcode_root):
        root_p = Path(root)
        rel = root_p.relative_to(transcode_root) if root_p != transcode_root else Path("")
        category = _category_from_parts(list(rel.parts))  # tv / movies / None

        # ISO-Dateien
        for f in files:
            if not f.lower().endswith(".iso"):
                continue
            p = root_p / f
            out.append({
                "kind": "iso",
                "path": p,                           # ISO an sich
                "category": category,
                "display": sanitize_filename(p.stem),
                "item_root": p.parent,               # zum Löschen / Anzeigen
                "season": extract_season(p.stem),
                "disc": extract_disc_no(p.stem) or extract_disc_no(str(p.parent)),
            })

        # Disc-Ordner sicher erkennen (VIDEO_TS/BDMV)
        kind_here = _is_disc_folder(root_p)
        if kind_here:
            item_root = root_p if root_p.name.upper() not in ("BDMV", "VIDEO_TS") else root_p.parent
            eff_path  = root_p if root_p.name.upper() in ("BDMV", "VIDEO_TS") else (root_p / ("BDMV" if kind_here == "bdmv" else "VIDEO_TS"))
            out.append({
                "kind": "file",
                "path": eff_path,                     # **direkt auf VIDEO_TS / BDMV**
                "category": category,
                "display": sanitize_filename(item_root.name),
                "item_root": item_root,
                "season": extract_season(item_root.name),
                "disc": extract_disc_no(item_root.name) or extract_disc_no(str(item_root.parent)),
            })

    # Dedupe nach (kind, path)
    deduped: List[Dict] = []
    seen = set()
    for s in out:
        key = (s["kind"], str(s["path"]).lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(s)

    if len(deduped) != len(out):
        log.info(f"Duplikate entfernt: {len(out) - len(deduped)}")
    log.info(f"Scan fertig: {len(deduped)} Quelle(n)")
    return deduped
