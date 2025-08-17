# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Optional
import os, re

def sanitize(name: str) -> str:
    # defensives Sanitizing fürs Display
    name = name.strip()
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1F]", "_", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip().rstrip("._")

def _is_disc_folder(p: Path) -> Optional[str]:
    # Liefert 'dvd' oder 'bdmv' wenn Ordner eine Scheibenstruktur enthält
    if (p / "VIDEO_TS").is_dir() or p.name.upper() == "VIDEO_TS":
        return "dvd"
    if (p / "BDMV").is_dir() or p.name.upper() == "BDMV":
        return "bdmv"
    return None

def _extract_season(s: str) -> Optional[int]:
    m = re.search(r"[Ss](?:eason)?\s*[_\-\.\s]?(\d{1,2})", s)
    if m:
        return int(m.group(1))
    m = re.search(r"\bS(\d{1,2})\b", s)
    return int(m.group(1)) if m else None

def _extract_disc_no(s: str) -> Optional[int]:
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

def _category_for(root_p: Path, transcode_root: Path) -> Optional[str]:
    try:
        rel = root_p.relative_to(transcode_root)
    except Exception:
        return None
    parts = [p.lower() for p in rel.parts]
    if "tv" in parts: return "tv"
    if "movies" in parts: return "movies"
    return None

def find_sources(transcode_root: Path, log) -> List[Dict]:
    log.info(f"Scan: {transcode_root}")
    sources: List[Dict] = []

    for root, dirs, files in os.walk(transcode_root):
        root_p = Path(root)

        # ISOs
        for f in files:
            if f.lower().endswith(".iso"):
                p = root_p / f
                cat = _category_for(root_p, transcode_root)
                base_disp = sanitize(p.stem)
                src = {
                    "kind": "iso",
                    "disc_type": "iso",
                    "path": p,
                    "category": cat,
                    "display": base_disp,
                    "item_root": p.parent,
                    "season": _extract_season(p.stem),
                    "disc": _extract_disc_no(p.stem) or _extract_disc_no(str(p.parent)),
                }
                sources.append(src)

        # Disc-Ordner (DVD/BDMV)
        disc_type = _is_disc_folder(root_p)
        if disc_type:
            # Wenn root_p die eigentliche Struktur enthält (VIDEO_TS/BDMV in Unterordner):
            # path -> der Ordner, der VIDEO_TS/BDMV enthält (wie in deinem Log)
            has_child = (root_p / "VIDEO_TS").is_dir() or (root_p / "BDMV").is_dir()
            eff_path = root_p
            # "item_root" soll der "anzeigbare" Elternordner sein, falls die Struktur in Unterordnern steckt
            item_root = root_p if root_p.name.upper() in ("VIDEO_TS", "BDMV") else root_p.parent
            if root_p.name.upper() in ("VIDEO_TS", "BDMV"):
                # z.B. ...\Titel\VIDEO_TS -> item_root = Titel
                eff_path = root_p.parent
            note = None
            if has_child and item_root != root_p:
                # z.B. ...\Titel\STDSNS1D2\VIDEO_TS → eff_path = ...\Titel\STDSNS1D2
                # und Display soll "Titel" sein
                note = "UNERWARTETE_STRUKTUR: DVD-Dateien in Unterordner; benutze Elternordner als Display"

            cat = _category_for(root_p, transcode_root)
            base_disp = sanitize(item_root.name)

            src = {
                "kind": "file",
                "disc_type": disc_type,
                "path": eff_path,
                "category": cat,
                "display": base_disp,
                "item_root": item_root,
                "season": _extract_season(item_root.name),
                "disc": _extract_disc_no(item_root.name) or _extract_disc_no(str(item_root.parent)),
            }
            if note:
                src["note"] = note
            sources.append(src)

    # Dedupe
    deduped: List[Dict] = []
    seen = set()
    for s in sources:
        key = (s.get("kind"), str(s.get("path")).lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(s)

    log.info(f"Scan fertig: {len(deduped)} Quelle(n)")
    return deduped
