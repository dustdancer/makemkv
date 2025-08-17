# -*- coding: utf-8 -*-
"""
Scanner:
- findet ISO/BDMV/VIDEO_TS unterhalb cfg.paths.transcode_dir
- Klassifiziert 'movies' / 'tv'
- Loggt Anomalien (alles außerhalb der erwarteten Struktur)
- Gibt strukturierte Quellen-Liste zurück (noch ohne Remux)

Hinweis:
Returncode-10-Fix (IFO/Index) wird beim Remux gebaut; hier nur Quelle + „effektiver Pfad“-Hinweis.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.core.loader import AppConfig
from src.utils.logger import log_section, log_subsection, log_anomaly

# --- Disc-Erkennung -----------------------------------------------------------

def _is_disc_folder(p: Path) -> Optional[str]:
    """Erkennt typische Disc-Ordner: 'bdmv' oder 'dvd' (VIDEO_TS)."""
    if (p / "BDMV").is_dir() or p.name.upper() == "BDMV":
        return "bdmv"
    if (p / "VIDEO_TS").is_dir() or p.name.upper() == "VIDEO_TS":
        return "dvd"
    return None


def _effective_disc_path(root: Path, kind: str) -> Path:
    """
    Für MakeMKV (RC=10 vermeiden) wollen wir später:
      - DVD:  VIDEO_TS/VIDEO_TS.IFO
      - BD:   BDMV/index.bdmv
    Hier nur vorberechnet (noch nicht genutzt).
    """
    if kind == "bdmv":
        if root.name.upper() == "BDMV":
            return root / "index.bdmv"
        return root / "BDMV" / "index.bdmv"
    if kind == "dvd":
        if root.name.upper() == "VIDEO_TS":
            return root / "VIDEO_TS.IFO"
        return root / "VIDEO_TS" / "VIDEO_TS.IFO"
    return root


def _category_for(rel_parts: Tuple[str, ...]) -> Optional[str]:
    """Erwartete Struktur: .../transcode/movies/** oder .../transcode/tv/**"""
    parts = [p.lower() for p in rel_parts]
    if "movies" in parts:
        return "movies"
    if "tv" in parts:
        return "tv"
    return None


# --- Public API ---------------------------------------------------------------

def scan_sources(cfg: AppConfig, logger) -> List[Dict]:
    """
    Scannt cfg.paths.transcode_dir, loggt und liefert Quellen als Dicts:
    {
      "kind": "iso" | "file",
      "path": <Path>,            # Pfad zur ISO oder Disc-Ordner (effektiver Pfad separat)
      "effective_path": <Path>,  # IFO/index.bdmv (nur bei Disc-Ordnern), sonst path
      "category": "movies" | "tv" | None,
      "display": <str>,          # Basisname zur Anzeige (z. B. Ordner-/Dateiname)
      "item_root": <Path>,       # root des Eintrags (bei BDMV/VIDEO_TS = Parent-Ordner)
    }
    """
    transcode = cfg.paths.transcode_dir
    log_section(logger, "SCAN")

    if not transcode.exists():
        logger.error(f"Transcode-Verzeichnis existiert nicht: {transcode}")
        return []

    logger.info(f"Scan: {transcode}")

    sources: List[Dict] = []
    seen_paths: set[str] = set()
    anomalies = 0

    for root, dirs, files in os.walk(transcode):
        root_p = Path(root)
        rel = root_p.relative_to(transcode) if root_p != transcode else Path("")
        rel_parts = tuple(rel.parts)
        category = _category_for(rel_parts)

        # Anomalie: ISO direkt unter transcode oder in fremden Unterbäumen
        for f in files:
            if not f.lower().endswith(".iso"):
                continue
            p = root_p / f
            key = f"iso::{p.resolve().as_posix().lower()}"
            if key in seen_paths:
                continue
            seen_paths.add(key)
            if category is None:
                anomalies += 1
                log_anomaly(logger, p, "ISO außerhalb der erwarteten Struktur ('movies'/'tv')")
            sources.append({
                "kind": "iso",
                "path": p,
                "effective_path": p,
                "category": category,
                "display": p.stem,
                "item_root": p.parent,
            })

        # Disc-Ordner (BDMV/VIDEO_TS)
        kind = _is_disc_folder(root_p)
        if kind:
            item_root = root_p if root_p.name.upper() not in ("BDMV", "VIDEO_TS") else root_p.parent
            eff = _effective_disc_path(root_p, kind)
            key = f"disc::{eff.resolve().as_posix().lower()}"
            if key not in seen_paths:
                seen_paths.add(key)
                if category is None:
                    anomalies += 1
                    log_anomaly(logger, item_root, f"{kind.upper()}-Struktur außerhalb der erwarteten Struktur ('movies'/'tv')")
                sources.append({
                    "kind": "file",
                    "path": root_p,
                    "effective_path": eff,
                    "category": category,
                    "display": item_root.name,
                    "item_root": item_root,
                })

    # Abschluss
    log_subsection(logger, "SCAN Ergebnis")
    logger.info(f"Quellen gefunden: {len(sources)}")
    logger.info(f"Anomalien: {anomalies}")
    return sources
