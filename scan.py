# file: scan.py
from __future__ import annotations

import os
import re
import logging
from pathlib import Path
from typing import List, Optional, Dict, Tuple

# --- Sanitizer import (robust) ---
try:
    # funktioniert, wenn naming.py eine Funktion sanitize_filename exportiert
    from naming import sanitize_filename  # type: ignore
except Exception:
    # Fallback, falls naming.py keine solche Funktion hat
    def sanitize_filename(name: str) -> str:
        name = name.strip()
        name = re.sub(r"[\\/:\*\?\"<>\|\x00-\x1F]", "_", name)
        name = re.sub(r"\s+", " ", name)
        return name.strip().rstrip("._")


# -------------------------
# Disc-Erkennung & Parser
# -------------------------

def is_disc_folder(p: Path) -> Optional[str]:
    """
    Erkenne Disc-Struktur (BDMV/VIDEO_TS).
    Gibt "bdmv", "dvd" oder None zurück.
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


def extract_season(s: str) -> Optional[int]:
    """
    Extrahiere Staffelnummer aus Strings wie:
    - "S01", "Season 1", "season_02", "S 3", …
    """
    m = re.search(r"[Ss](?:eason)?\s*[_\-\.\s]?(\d{1,2})\b", s)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    m = re.search(r"\bS(\d{1,2})\b", s)
    return int(m.group(1)) if m else None


def extract_disc_no(s: str) -> Optional[int]:
    """
    Extrahiere Disc-Nummer aus Strings wie:
    - "Disc 1", "Disk2", "D3", "S01D02", "CD 1", …
    """
    s = s.replace("_", " ")
    patterns = [
        r"\bdisc\s*(\d{1,2})\b",
        r"\bdisk\s*(\d{1,2})\b",
        r"\bd\s*(\d{1,2})\b",
        r"\bD(\d{1,2})\b",
        r"\bCD\s*(\d{1,2})\b",
        r"\bS\d{1,2}D(\d{1,2})\b",
        r"\bDisc(\d{1,2})\b",
        r"\bDisk(\d{1,2})\b",
        r"\bPart\s*(\d{1,2})\b",
    ]
    for pat in patterns:
        m = re.search(pat, s, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
    return None


# -------------------------
# Source-Suche
# -------------------------

def find_sources(transcode_root: Path, log: logging.Logger) -> List[Dict]:
    """
    Durchsucht das Transcode-Verzeichnis nach Quellen:
    - ISO-Dateien
    - Disc-Ordner (BDMV/VIDEO_TS)

    Rückgabe: Liste von Dicts mit Schlüsseln:
      kind: "iso" | "file"
      path: Pfad zur eigentlichen Disc (z.B. …/BDMV)
      item_root: logischer Titelordner (über BDMV/VIDEO_TS)
      display: sauberer Anzeigename (aus item_root.name bzw. ISO-Stem)
      category: "movies" | "tv" | None
      season: int | None
      disc: int | None
    """
    log.info(f"Scan: {transcode_root}")
    sources: List[Dict] = []

    for root, dirs, files in os.walk(transcode_root):
        root_p = Path(root)
        # Kategorie aus Pfad ableiten (movies/tv in den Pfadteilen)
        rel = root_p.relative_to(transcode_root) if root_p != transcode_root else Path("")
        parts = [p.lower() for p in rel.parts]
        category = "movies" if "movies" in parts else ("tv" if "tv" in parts else None)

        # --- ISOs einsammeln ---
        for f in files:
            if f.lower().endswith(".iso"):
                p = root_p / f
                base_disp = sanitize_filename(p.stem)
                src = {
                    "kind": "iso",
                    "path": p,
                    "category": category,
                    "display": base_disp,
                    "item_root": p.parent,
                    "season": extract_season(p.stem),
                    "disc": extract_disc_no(p.stem) or extract_disc_no(str(p.parent)),
                }
                sources.append(src)
                log.debug(f"ISO: {p} (cat={category}, season={src['season']}, disc={src['disc']})")

        # --- Disc-Ordner (BDMV/VIDEO_TS) einsammeln ---
        kind_here = is_disc_folder(root_p)
        if kind_here:
            # Wenn wir bereits im BDMV/VIDEO_TS stehen, ist item_root der Parent
            item_root = root_p if root_p.name.upper() not in ("BDMV", "VIDEO_TS") else root_p.parent
            eff_path = (
                root_p if root_p.name.upper() in ("BDMV", "VIDEO_TS")
                else (root_p / ("BDMV" if kind_here == "bdmv" else "VIDEO_TS"))
            )
            base_disp = sanitize_filename(item_root.name)
            src = {
                "kind": "file",
                "path": eff_path,
                "category": category,
                "display": base_disp,
                "item_root": item_root,
                "season": extract_season(item_root.name),
                "disc": extract_disc_no(item_root.name) or extract_disc_no(str(item_root.parent)),
            }
            sources.append(src)
            log.debug(
                f"Disc-Ordner: {eff_path} "
                f"(cat={category}, season={src['season']}, disc={src['disc']})"
            )

    # --- Deduplizieren (z.B. wenn BDMV und Parent beide erkannt wurden) ---
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

    # --- Übersicht ausgeben: erkannte Filme & Serien/Staffeln ---
    try:
        _log_summary(deduped, log)
    except Exception as e:
        log.debug(f"Summary-Ausgabe übersprungen: {e}")

    return deduped


# -------------------------
# Summary-Helfer (nur Logs)
# -------------------------

def _log_summary(sources: List[Dict], log: logging.Logger) -> None:
    """Loggt eine kompakte Übersicht der erkannten Inhalte."""
    movies = [s for s in sources if s.get("category") != "tv"]
    tvs = [s for s in sources if s.get("category") == "tv"]

    if movies:
        log.info("Erkannt – Filme:")
        seen_titles = set()
        for s in sorted(movies, key=lambda x: (x["display"], str(x["item_root"]).lower())):
            disp = s["display"]
            if disp in seen_titles:
                continue
            seen_titles.add(disp)
            log.info(f"  • {disp}")
        log.info("")

    if tvs:
        log.info("Erkannt – Serien/Staffeln:")
        groups: Dict[Tuple[str, Optional[int]], List[Dict]] = {}
        for s in tvs:
            key = (s["display"], s.get("season"))
            groups.setdefault(key, []).append(s)

        for (disp, season), items in sorted(groups.items(), key=lambda x: (x[0][0], x[0][1] or 0)):
            discs = sorted([d for d in (i.get("disc") for i in items) if d is not None])
            season_str = f"Season {season:02d}" if season is not None else "Season ??"
            if discs:
                log.info(f"  • {disp} | {season_str} | Discs: {', '.join(f'{d}' for d in discs)}")
            else:
                log.info(f"  • {disp} | {season_str} | Discs: ?")
        log.info("")
