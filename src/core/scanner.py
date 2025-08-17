# -*- coding: utf-8 -*-
"""
Scanner: findet ISO/BDMV/VIDEO_TS unterhalb des Transcode-Roots
und liefert strukturierte Einträge, u. a.:
{
  "kind": "iso" | "file",
  "path": Path(...),          # bei "file": Pfad auf BDMV/VIDEO_TS
  "item_root": Path(...),     # Anzeigebasis (Elternordner der Disc-Struktur)
  "category": "movies" | "tv" | None,
  "disc_type": "bdmv" | "dvd" | None,
  "display": "...",
  "season": Optional[int],
  "disc": Optional[int],
  "note": Optional[str],
}
"""

from __future__ import annotations
import os
import re
from pathlib import Path
from typing import Dict, List, Optional


def _sanitize(name: str) -> str:
    import re
    name = name.strip()
    name = re.sub(r"[\\/:\*\?\"<>\|\x00-\x1F]", "_", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip().rstrip("._")


def _is_disc_folder(p: Path) -> Optional[str]:
    # Erkenne BDMV/VIDEO_TS sowohl als Kind-Ordner als auch direkt
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
    # "Staffel 4", "Season 4", "S4"
    m = re.search(r"[Ss](?:taffel|eason)?\s*[_\-\.\s]?(\d{1,2})", s)
    if m:
        return int(m.group(1))
    m = re.search(r"\bS(\d{1,2})\b", s)
    return int(m.group(1)) if m else None


def _extract_disc_no(s: str) -> Optional[int]:
    s = s.replace("_", " ")
    pats = [
        r"\bdisc\s*(\d{1,2})\b", r"\bdisk\s*(\d{1,2})\b", r"\bd\s*(\d{1,2})\b",
        r"\bD(\d{1,2})\b", r"\bCD\s*(\d{1,2})\b", r"\bS\d{1,2}D(\d{1,2})\b",
        r"\bDisc(\d{1,2})\b", r"\bDisk(\d{1,2})\b",
        r"\bDvD\s*(\d{1,2})\b", r"\bDVD\s*(\d{1,2})\b",
    ]
    for pat in pats:
        m = re.search(pat, s, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
    return None


def find_sources(transcode_root: Path, log) -> List[Dict]:
    log.info(f"Scan: {transcode_root}")
    sources: List[Dict] = []

    for root, dirs, files in os.walk(transcode_root):
        root_p = Path(root)

        # Kategorie aus Pfadteilen
        rel = root_p.relative_to(transcode_root) if root_p != transcode_root else Path("")
        parts = [p.lower() for p in rel.parts]
        category = "movies" if "movies" in parts else ("tv" if "tv" in parts else None)

        # 1) ISOs
        for f in files:
            if f.lower().endswith(".iso"):
                p = root_p / f
                base_disp = _sanitize(p.stem)
                sources.append({
                    "kind": "iso",
                    "path": p,
                    "item_root": p.parent,
                    "category": category,
                    "disc_type": None,
                    "display": base_disp,
                    "season": _extract_season(p.stem),
                    "disc": _extract_disc_no(p.stem) or _extract_disc_no(str(p.parent)),
                    "note": None,
                })
                log.debug(f"ISO: {p}")

        # 2) Disc-Ordner (BDMV/VIDEO_TS)
        disc_type_here = _is_disc_folder(root_p)
        if disc_type_here:
            if root_p.name.upper() in ("BDMV", "VIDEO_TS"):
                item_root = root_p.parent
                eff_path = root_p      # direkt auf BDMV/VIDEO_TS zeigen
                note = None
            else:
                # BDMV/VIDEO_TS liegt als Kind – Anzeige = Eltern
                item_root = root_p
                eff_path = root_p / ("BDMV" if disc_type_here == "bdmv" else "VIDEO_TS")
                note = "UNERWARTETE_STRUKTUR: DVD/BD-Dateien in Unterordner; benutze Elternordner als Display"

            display = _sanitize(item_root.name)
            sources.append({
                "kind": "file",
                "path": eff_path,
                "item_root": item_root,
                "category": category,
                "disc_type": disc_type_here,
                "display": display,
                "season": _extract_season(item_root.name),
                "disc": _extract_disc_no(item_root.name) or _extract_disc_no(str(item_root.parent)),
                "note": note,
            })
            log.debug(f"Disc: type={disc_type_here} | eff_path={eff_path} | item_root={item_root} | cat={category} | note={note}")

    # Deduplizieren (z. B. doppelte Aufzählungen)
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
