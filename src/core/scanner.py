# -*- coding: utf-8 -*-
"""
Scanner: findet ISO / BDMV / VIDEO_TS unterhalb des Transcode-Roots
und protokolliert zusätzlich "unerwartete" Strukturen, um die Heuristik
später nachschärfen zu können.

Rückgabe:
- sources: List[dict] mit Feldern:
    kind: "iso" | "file"
    path: Pfad zur Quelle (bei Ordnern der Disc-Ordner selbst, nicht die Index-Datei)
    item_root: oberster Ordner der Disc (z. B. der Ordner, der BDMV/VIDEO_TS enthält) bzw. ISO-Parent
    display: Name für Ziel/Anzeige (aus item_root / ISO-Stem)
    category: "movies" | "tv" | None  (aus Pfad-Teilen abgeleitet)
    season: Optional[int]  (aus Namen heuristisch)
    disc:   Optional[int]  (aus Namen heuristisch)
- anomalies: List[dict] mit Feldern:
    type, path, details

Hinweis: Keine externen Abhängigkeiten, nur stdlib.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# -------------------------
# Utilities (klein & lokal)
# -------------------------

def _sanitize_filename(name: str) -> str:
    # konservatives Sanitize für Anzeigenamen
    s = name.strip()
    s = re.sub(r"[\\/:*?\"<>|\x00-\x1F]", "_", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.rstrip("._")


def _is_disc_folder(p: Path) -> Optional[str]:
    """
    Erkennung reiner Disc-Ordner:
      - enthält BDMV   -> "bdmv"
      - enthält VIDEO_TS -> "dvd"
      - Ordner heißt direkt BDMV/VIDEO_TS -> entsprechend
    """
    if (p / "BDMV").is_dir():
        return "bdmv"
    if (p / "VIDEO_TS").is_dir():
        return "dvd"
    if p.name.upper() == "BDMV":
        return "bdmv"
    if p.name.upper() == "VIDEO_TS":
        return "dvd"
    return None


def _extract_season(s: str) -> Optional[int]:
    m = re.search(r"[Ss](?:eason)?\s*[_\-\.\s]?(\d{1,2})", s)
    if m:
        return int(m.group(1))
    m = re.search(r"\bS(\d{1,2})\b", s)
    return int(m.group(1)) if m else None


def _extract_disc_no(s: str) -> Optional[int]:
    s = s.replace("_", " ")
    patterns = [
        r"\bdisc\s*(\d{1,2})\b", r"\bdisk\s*(\d{1,2})\b", r"\bd\s*(\d{1,2})\b",
        r"\bD(\d{1,2})\b", r"\bCD\s*(\d{1,2})\b", r"\bS\d{1,2}D(\d{1,2})\b",
        r"\bDisc(\d{1,2})\b", r"\bDisk(\d{1,2})\b"
    ]
    for pat in patterns:
        m = re.search(pat, s, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
    return None


def _category_from_parts(rel_parts: Tuple[str, ...]) -> Optional[str]:
    parts = [p.lower() for p in rel_parts]
    if "movies" in parts:
        return "movies"
    if "tv" in parts:
        return "tv"
    return None


def _log_anomaly(anomalies: List[Dict], log: logging.Logger, a_type: str, path: Path, details: str):
    entry = {"type": a_type, "path": str(path), "details": details}
    anomalies.append(entry)
    log.warning(f"[ANOMALIE] {a_type} | {path} | {details}")


# -------------------------
# Scan
# -------------------------

def scan_sources(transcode_root: Path, log: logging.Logger) -> Tuple[List[Dict], List[Dict]]:
    """
    Durchsucht transcode_root rekursiv nach ISO/Disc-Ordnern.
    Erkennt und protokolliert dabei "unerwartete" Strukturen.

    Returns: (sources, anomalies)
    """
    log.info(f"Scan: {transcode_root}")
    sources: List[Dict] = []
    anomalies: List[Dict] = []

    if not transcode_root.exists():
        _log_anomaly(anomalies, log, "root_missing", transcode_root, "Transcode-Root existiert nicht.")
        return [], anomalies

    for root, dirs, files in os.walk(transcode_root):
        root_p = Path(root)

        # Kategorie aus dem relativen Pfad ableiten
        try:
            rel = root_p.relative_to(transcode_root)
            category = _category_from_parts(rel.parts)
        except Exception:
            category = None

        # -----------------
        # ISO-Dateien
        # -----------------
        iso_files = [f for f in files if f.lower().endswith(".iso")]
        for fname in iso_files:
            p = root_p / fname
            item_root = p.parent
            display = _sanitize_filename(p.stem)

            if category is None:
                _log_anomaly(
                    anomalies, log, "iso_without_category", p,
                    "ISO liegt nicht unter /movies oder /tv (oder Kategorie nicht ableitbar)."
                )

            sources.append({
                "kind": "iso",
                "path": p,
                "item_root": item_root,
                "display": display,
                "category": category,
                "season": _extract_season(p.stem),
                "disc": _extract_disc_no(p.stem) or _extract_disc_no(str(item_root)),
            })

        # -----------------------------------------
        # Disc-Ordner (BDMV/VIDEO_TS) erkennen
        # -----------------------------------------
        disc_kind = _is_disc_folder(root_p)
        if disc_kind:
            # "item_root" ist der Ordner, der BDMV/VIDEO_TS enthält
            item_root = root_p if root_p.name.upper() not in ("BDMV", "VIDEO_TS") else root_p.parent
            # effektiver Disc-Ordner (der Ordner, in dem index/ifo erwartet wird)
            eff_disc = (
                root_p if root_p.name.upper() in ("BDMV", "VIDEO_TS")
                else (root_p / ("BDMV" if disc_kind == "bdmv" else "VIDEO_TS"))
            )
            display = _sanitize_filename(item_root.name)

            # Kategorie prüfen
            try:
                rel_item = item_root.relative_to(transcode_root)
                cat_item = _category_from_parts(rel_item.parts)
            except Exception:
                cat_item = None

            if cat_item is None:
                _log_anomaly(
                    anomalies, log, "disc_without_category", item_root,
                    f"Disc-Ordner liegt nicht unter /movies oder /tv (erkannt: {disc_kind})."
                )

            # Struktur prüfen
            if disc_kind == "bdmv":
                idx = eff_disc / "index.bdmv"
                if not idx.exists():
                    _log_anomaly(anomalies, log, "bd_index_missing", eff_disc, "BDMV ohne index.bdmv.")
            elif disc_kind == "dvd":
                ifo = eff_disc / "VIDEO_TS.IFO"
                if not ifo.exists():
                    _log_anomaly(anomalies, log, "dvd_ifo_missing", eff_disc, "VIDEO_TS ohne VIDEO_TS.IFO.")

            # Tiefe prüfen (stark verschachtelt?)
            try:
                depth = len(eff_disc.relative_to(transcode_root).parts)
                if depth > 6:
                    _log_anomaly(
                        anomalies, log, "disc_deeply_nested", eff_disc,
                        f"Disc-Ordner ist ungewöhnlich tief verschachtelt (Tiefe={depth})."
                    )
            except Exception:
                pass

            sources.append({
                "kind": "file",
                "path": eff_disc,
                "item_root": item_root,
                "display": display,
                "category": cat_item,
                "season": _extract_season(item_root.name),
                "disc": _extract_disc_no(item_root.name) or _extract_disc_no(str(item_root.parent)),
            })

        # -----------------------------------------
        # Lose Disc-Dateien (unerwartet)
        # -----------------------------------------
        # Falls in einem Ordner *.m2ts / *.vob liegen, ohne dass dies ein korrekter Disc-Ordner ist.
        if not disc_kind:
            loose_bd = any(f.lower().endswith(".m2ts") for f in files)
            loose_dvd = any(f.lower().endswith((".vob", ".ifo", ".bup")) for f in files)
            if loose_bd or loose_dvd:
                _log_anomaly(
                    anomalies, log, "loose_media_files", root_p,
                    "Disc-Dateien gefunden, aber kein BDMV/VIDEO_TS-Ordner auf dieser Ebene."
                )

        # -----------------------------------------
        # Gemischte Medien in einem Item-Root
        # -----------------------------------------
        # Heuristik: Wenn ein Ordner sowohl ISO als auch einen Disc-Unterordner enthält → melden
        # (nur einfache Prüfung auf dieser Ebene)
        if iso_files and disc_kind:
            _log_anomaly(
                anomalies, log, "mixed_iso_and_disc", root_p,
                "ISO-Dateien und Disc-Ordner gleichzeitig in gleicher Ebene gefunden."
            )

    # Deduplizieren (falls BDMV/VIDEO_TS doppelt erfasst würde)
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
    if anomalies:
        log.info(f"Anomalien erkannt: {len(anomalies)} (siehe [ANOMALIE]-Einträge im Log)")

    return deduped, anomalies
