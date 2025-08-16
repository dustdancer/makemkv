# -*- coding: utf-8 -*-
from __future__ import annotations
import os, re, logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from utils import sanitize_filename

def is_disc_folder(p: Path) -> Optional[str]:
    if (p / "BDMV").is_dir(): return "bdmv"
    if (p / "VIDEO_TS").is_dir(): return "dvd"
    if p.name.upper() == "BDMV": return "bdmv"
    if p.name.upper() == "VIDEO_TS": return "dvd"
    return None

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
            try: return int(m.group(1))
            except: pass
    return None

def find_sources(transcode_root: Path, log: logging.Logger) -> List[Dict]:
    log.info(f"Scan: {transcode_root}")
    sources: List[Dict] = []
    for root, dirs, files in os.walk(transcode_root):
        root_p = Path(root)
        rel = root_p.relative_to(transcode_root) if root_p != transcode_root else Path("")
        parts = [p.lower() for p in rel.parts]
        category = "movies" if "movies" in parts else ("tv" if "tv" in parts else None)

        # ISOs
        for f in files:
            if f.lower().endswith(".iso"):
                p = root_p / f
                base_disp = sanitize_filename(p.stem)
                sources.append({
                    "kind": "iso",
                    "path": p,
                    "category": category,
                    "display": base_disp,
                    "item_root": p.parent,
                    "season": extract_season(p.stem),
                    "disc": extract_disc_no(p.stem) or extract_disc_no(str(p.parent)),
                })

        # Disc-Ordner
        kind_here = is_disc_folder(root_p)
        if kind_here:
            item_root = root_p if root_p.name.upper() not in ("BDMV","VIDEO_TS") else root_p.parent
            eff_path = root_p if root_p.name.upper() in ("BDMV","VIDEO_TS") else (root_p / ("BDMV" if kind_here=="bdmv" else "VIDEO_TS"))
            base_disp = sanitize_filename(item_root.name)
            sources.append({
                "kind": "file",
                "path": eff_path,
                "category": category,
                "display": base_disp,
                "item_root": item_root,
                "season": extract_season(item_root.name),
                "disc": extract_disc_no(item_root.name) or extract_disc_no(str(item_root.parent)),
            })

    # Deduplizieren
    deduped: List[Dict] = []
    seen = set()
    for s in sources:
        key = (s.get("kind"), str(s.get("path")).lower())
        if key in seen: continue
        seen.add(key)
        deduped.append(s)

    if len(deduped) != len(sources):
        log.info(f"Duplikate entfernt: {len(sources) - len(deduped)}")
    log.info(f"Scan fertig: {len(deduped)} Quelle(n)")

    # Übersicht
    movies = [d for d in deduped if d.get("category") != "tv"]
    tvs    = [d for d in deduped if d.get("category") == "tv"]
    if movies:
        log.info("Erkannte Movies:")
        for m in movies:
            log.info(f"  • {m['display']} ({m['kind']}) -> {m['path']}")
    if tvs:
        log.info("Erkannte TV-Discs:")
        for t in tvs:
            log.info(f"  • {t['display']} (S={t.get('season')}, D={t.get('disc')}) -> {t['path']}")

    return deduped
