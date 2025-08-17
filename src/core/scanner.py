# -*- coding: utf-8 -*-
"""
Scanner für Quellmedien unterhalb des konfigurierten transcode_dir.

Fähigkeiten:
- Findet .iso Dateien
- Findet Disc-Ordner (DVD: VIDEO_TS[/VIDEO_TS.IFO], Blu-ray: BDMV[/index.bdmv])
- Normalisiert Eingaben (Returncode-10-Fix): liefert "effektiven" Pfad auf IFO oder index.bdmv,
  wenn vorhanden, ansonsten den Ordner selbst.
- Erkennt Kategorie "movies" oder "tv" (wenn im Relativpfad enthalten)
- Markiert und protokolliert "unerwartete Strukturen":
    * Quellen, die NICHT innerhalb von /movies oder /tv liegen
    * Disc-Layouts, bei denen VIDEO_TS/BDMV nicht am erwarteten Ort gefunden werden
- Liefert eine Liste strukturierter Quellen (SourceEntry)

Diese Datei ist NEU (v0.0.3).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Dict

from logging import Logger


# --------------------------
# Hilfsfunktionen & Modelle
# --------------------------

@dataclass
class SourceEntry:
    # Grunddaten
    kind: str                # "iso" oder "file"
    path: Path               # ursprünglicher Pfad (ISO-Datei, Disc-Ordner)
    eff_path: Path           # effektiv zu übergebender Pfad (IFO/index.bdmv oder Ordner)
    category: Optional[str]  # "movies" | "tv" | None
    display: str             # Anzeigename (meist abgeleitet aus item_root)
    item_root: Path          # Wurzel des Items (z. B. Ordner der Disc oder ISO-Parent)
    # Zusatzinfos
    season: Optional[int]    # staffelnummer, wenn erkennbar
    disc: Optional[int]      # disc-nummer, wenn erkennbar
    unexpected: bool         # markiert “unerwartete Struktur”


def _sanitize_display(name: str) -> str:
    n = re.sub(r"[\\/:\*\?\"<>\|\x00-\x1F]", "_", name.strip())
    n = re.sub(r"\s+", " ", n)
    return n.strip().rstrip("._")


def _extract_season(s: str) -> Optional[int]:
    m = re.search(r"[Ss](?:eason)?\s*[_\-\.\s]?(\d{1,2})", s)
    if m:
        return int(m.group(1))
    m = re.search(r"\bS(\d{1,2})\b", s)
    return int(m.group(1)) if m else None


def _extract_disc_no(s: str) -> Optional[int]:
    s2 = s.replace("_", " ")
    patterns = [
        r"\bdisc\s*(\d{1,2})\b", r"\bdisk\s*(\d{1,2})\b", r"\bd\s*(\d{1,2})\b",
        r"\bD(\d{1,2})\b", r"\bCD\s*(\d{1,2})\b", r"\bS\d{1,2}D(\d{1,2})\b",
        r"\bDisc(\d{1,2})\b", r"\bDisk(\d{1,2})\b"
    ]
    for pat in patterns:
        m = re.search(pat, s2, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
    return None


def _is_disc_folder(p: Path) -> Optional[str]:
    """
    Gibt "dvd" zurück, wenn VIDEO_TS existiert;
    gibt "bdmv" zurück, wenn BDMV existiert;
    sonst None.
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


def _effective_disc_path(root: Path, kind: str) -> Tuple[Path, bool]:
    """
    Ermittelt den effektiv zu übergebenden Pfad. Returncode-10-Fix:
    - DVD:  VIDEO_TS/VIDEO_TS.IFO
    - BD:   BDMV/index.bdmv
    Fällt zurück auf den Ordner selbst. Zweiter Rückgabewert "was_normalized"
    zeigt an, ob eine Normalisierung stattgefunden hat.
    """
    was_normalized = False
    if kind == "dvd":
        # falls wir direkt im VIDEO_TS stehen
        if root.name.upper() == "VIDEO_TS":
            if (root / "VIDEO_TS.IFO").exists():
                return root / "VIDEO_TS.IFO", True
            return root, False
        # ansonsten unterhalb root/VIDEO_TS/VIDEO_TS.IFO
        dvd_ifo = root / "VIDEO_TS" / "VIDEO_TS.IFO"
        if dvd_ifo.exists():
            return dvd_ifo, True
        # not found → fallback
        return root, False

    if kind == "bdmv":
        if root.name.upper() == "BDMV":
            if (root / "index.bdmv").exists():
                return root / "index.bdmv", True
            return root, False
        bd_idx = root / "BDMV" / "index.bdmv"
        if bd_idx.exists():
            return bd_idx, True
        return root, False

    # kein Disc-Ordner
    return root, False


# --------------------------
# Hauptscan
# --------------------------

def find_sources(transcode_root: Path, log: Logger) -> List[SourceEntry]:
    """
    durchsucht transcode_root rekursiv nach ISO/Disc-Ordnern
    und liefert eine deduplizierte Liste von SourceEntry.
    Protokolliert “unerwartete Strukturen” ins Log.
    """
    log.info(f"Scan: {transcode_root}")
    if not transcode_root.exists():
        log.error(f"Transcode-Verzeichnis existiert nicht: {transcode_root}")
        return []

    sources: List[SourceEntry] = []
    unexpected_hits: List[Path] = []

    for root, dirs, files in os.walk(transcode_root):
        root_p = Path(root)

        # Kategorie bestimmen (nur Heuristik)
        rel = root_p.relative_to(transcode_root) if root_p != transcode_root else Path("")
        parts = [p.lower() for p in rel.parts]
        category: Optional[str] = "movies" if "movies" in parts else ("tv" if "tv" in parts else None)

        # 1) ISOs
        for fn in files:
            if not fn.lower().endswith(".iso"):
                continue
            iso_path = root_p / fn
            display = _sanitize_display(iso_path.stem)
            item_root = iso_path.parent

            unexpected = category is None  # ISO liegt nicht unter /movies oder /tv
            if unexpected:
                unexpected_hits.append(iso_path)

            sources.append(
                SourceEntry(
                    kind="iso",
                    path=iso_path,
                    eff_path=iso_path,  # für ISO bleibt eff_path das ISO selbst
                    category=category,
                    display=display,
                    item_root=item_root,
                    season=_extract_season(iso_path.stem),
                    disc=_extract_disc_no(iso_path.stem) or _extract_disc_no(str(item_root)),
                    unexpected=unexpected,
                )
            )

        # 2) Disc-Ordner
        disc_kind = _is_disc_folder(root_p)
        if not disc_kind:
            continue

        # Ordnerstruktur normalisieren:
        # Wenn wir direkt in VIDEO_TS/BDMV sind, ist item_root = parent
        item_root = root_p if root_p.name.upper() not in ("BDMV", "VIDEO_TS") else root_p.parent
        eff_base = (
            root_p
            if root_p.name.upper() in ("BDMV", "VIDEO_TS")
            else (root_p / ("BDMV" if disc_kind == "bdmv" else "VIDEO_TS"))
        )

        eff, normalized = _effective_disc_path(item_root if eff_base == item_root else eff_base, disc_kind)
        display = _sanitize_display(item_root.name)

        unexpected = category is None
        # Zusätzlich als "unerwartet" markieren, wenn kein IFO/index gefunden wurde (kein normalized)
        # und wir somit den Ordner selbst remuxen müssten → kann zu RC=10 führen.
        if not normalized:
            unexpected = True
            unexpected_hits.append(eff_base)

        sources.append(
            SourceEntry(
                kind="file",
                path=eff_base,
                eff_path=eff,
                category=category,
                display=display,
                item_root=item_root,
                season=_extract_season(item_root.name),
                disc=_extract_disc_no(item_root.name) or _extract_disc_no(str(item_root.parent)),
                unexpected=unexpected,
            )
        )

    # Deduplizieren: key = (kind, eff_path.lower())
    deduped: List[SourceEntry] = []
    seen = set()
    for s in sources:
        key = (s.kind, str(s.eff_path).lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(s)

    if len(deduped) != len(sources):
        log.info(f"Duplikate entfernt: {len(sources) - len(deduped)}")

    log.info(f"Scan fertig: {len(deduped)} Quelle(n)")

    # Unerwartete Strukturen melden (kompakt)
    if unexpected_hits:
        log.info("Unerwartete Strukturen erkannt (zur Heuristik-Anpassung):")
        for p in sorted(set(unexpected_hits)):
            log.info(f"  * {p}")

    return deduped
