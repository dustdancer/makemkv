# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import re
from pathlib import Path
from typing import List, Dict, Optional
import logging


DVD_FILE_HINTS = (".ifo", ".vob", ".bup")


def sanitize(name: str) -> str:
    name = name.strip()
    name = re.sub(r"[\\/:\*\?\"<>\|\x00-\x1F]", "_", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip().rstrip("._")


def extract_season(s: str) -> Optional[int]:
    m = re.search(r"[Ss](?:taffel|eason)?\s*[_\-\.\s]?(\d{1,2})", s)
    if m:
        return int(m.group(1))
    m = re.search(r"\bS(\d{1,2})\b", s)
    return int(m.group(1)) if m else None


def extract_disc_no(s: str) -> Optional[int]:
    s2 = s.replace("_", " ")
    patterns = [
        r"\bdisc\s*(\d{1,2})\b", r"\bdisk\s*(\d{1,2})\b",
        r"\bd\s*(\d{1,2})\b", r"\bD(\d{1,2})\b",
        r"\bCD\s*(\d{1,2})\b", r"\bS\d{1,2}D(\d{1,2})\b",
        r"\bDvD\s*(\d{1,2})\b", r"\bDVD\s*(\d{1,2})\b",
    ]
    for pat in patterns:
        m = re.search(pat, s2, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
    return None


def _category_from_rel_parts(parts: List[str]) -> Optional[str]:
    # robust: nimm erstes Auftreten von 'tv' oder 'movies'
    for p in parts:
        lp = p.lower()
        if lp in ("tv", "series", "shows"):
            return "tv"
        if lp in ("movies", "film", "movie"):
            return "movies"
    return None


def _folder_contains_dvd_files(p: Path) -> bool:
    try:
        for f in p.iterdir():
            if f.is_file() and f.suffix.lower() in DVD_FILE_HINTS:
                return True
    except Exception:
        pass
    return False


def find_sources(transcode_root: Path, log: logging.Logger) -> List[Dict]:
    log.info(f"Scan: {transcode_root}")
    sources: List[Dict] = []

    for root, dirs, files in os.walk(transcode_root):
        root_p = Path(root)

        # relative Teile -> Kategorie
        if root_p == transcode_root:
            rel_parts = []
        else:
            rel_parts = list(root_p.relative_to(transcode_root).parts)
        category = _category_from_rel_parts([p.lower() for p in rel_parts])

        # --- ISOs ---
        for f in files:
            if f.lower().endswith(".iso"):
                p = root_p / f
                stem = sanitize(p.stem)
                src = {
                    "kind": "iso",
                    "disc_type": "iso",
                    "path": p,
                    "item_root": p.parent,
                    "category": category,
                    "display": stem,
                    "season": extract_season(stem) or extract_season(p.parent.name),
                    "disc": extract_disc_no(stem) or extract_disc_no(p.parent.name),
                }
                log.debug(f"ISO: path={p} | cat={category}")
                sources.append(src)

        # --- BDMV/VIDEO_TS normal ---
        if (root_p / "BDMV").is_dir():
            item_root = root_p
            eff_path = root_p / "BDMV"
            disp = sanitize(item_root.name)
            src = {
                "kind": "file",
                "disc_type": "bdmv",
                "path": eff_path,
                "item_root": item_root,
                "category": category,
                "display": disp,
                "season": extract_season(item_root.name),
                "disc": extract_disc_no(item_root.name) or extract_disc_no(eff_path.name),
            }
            log.debug(f"Disc: type=bdmv | eff_path={eff_path} | item_root={item_root} | cat={category}")
            sources.append(src)

        if (root_p / "VIDEO_TS").is_dir():
            item_root = root_p
            eff_path = root_p / "VIDEO_TS"
            disp = sanitize(item_root.name)
            src = {
                "kind": "file",
                "disc_type": "dvd",
                "path": eff_path,
                "item_root": item_root,
                "category": category,
                "display": disp,
                "season": extract_season(item_root.name),
                "disc": extract_disc_no(item_root.name) or extract_disc_no(eff_path.name),
            }
            log.debug(f"Disc: type=dvd | eff_path={eff_path} | item_root={item_root} | cat={category}")
            sources.append(src)

        # --- Fälle, in denen *der Ordner selbst* BDMV/VIDEO_TS heißt ---
        base_name = root_p.name.upper()
        if base_name in ("BDMV", "VIDEO_TS"):
            item_root = root_p.parent
            eff_path = root_p
            disp = sanitize(item_root.name)
            src = {
                "kind": "file",
                "disc_type": "bdmv" if base_name == "BDMV" else "dvd",
                "path": eff_path,
                "item_root": item_root,
                "category": category,
                "display": disp,
                "season": extract_season(item_root.name),
                "disc": extract_disc_no(item_root.name) or extract_disc_no(eff_path.name),
            }
            log.debug(f"Disc (named folder): type={src['disc_type']} | eff_path={eff_path} | item_root={item_root} | cat={category}")
            sources.append(src)

        # --- WICHTIG: DVD-Dateien in *Unterordnern* ohne VIDEO_TS (z.B. …\DvD 2\STDSNS1D2\*.IFO) ---
        # Erkenne solche Ordner und nutze den Elternordner als Display.
        # Eff_path = der Unterordner mit den IFO/VOB-Dateien.
        if _folder_contains_dvd_files(root_p) and base_name not in ("BDMV", "VIDEO_TS"):
            parent = root_p.parent
            # Vermeiden, dass wir den *Hauptordner* doppelt erfassen, wenn darüber schon VIDEO_TS existiert.
            if not (parent / "VIDEO_TS").is_dir():
                src = {
                    "kind": "file",
                    "disc_type": "dvd",
                    "path": root_p,            # dort liegen die Dateien
                    "item_root": parent,       # der schöne Anzeigename liegt eine Ebene höher
                    "category": category,
                    "display": sanitize(parent.name),
                    "season": extract_season(parent.name) or extract_season(root_p.name),
                    "disc": extract_disc_no(parent.name) or extract_disc_no(root_p.name),
                    "note": "UNERWARTETE_STRUKTUR: DVD-Dateien in Unterordner; benutze Elternordner als Display",
                }
                log.debug(f"Disc: type=dvd | eff_path={root_p} | item_root={parent} | cat={category} | note=unterordner-dvd")
                sources.append(src)

    # --- Deduplizieren (falls z.B. BDMV + benannter BDMV-Ordner doppelt auftauchen) ---
    deduped: List[Dict] = []
    seen = set()
    for s in sources:
        key = (s.get("kind"), str(Path(s.get("path")).resolve()).lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(s)

    log.info(f"Scan fertig: {len(deduped)} Quelle(n)")
    return deduped
