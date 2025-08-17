# -*- coding: utf-8 -*-
from __future__ import annotations

import shutil
import logging
from pathlib import Path
from typing import Dict, List, Tuple

from naming import parse_name_year


TRAILER_MAX = 240  # Sekunden


def _probe_duration_seconds(p: Path, log: logging.Logger) -> float:
    # ffprobe bevorzugt
    import subprocess, json, shutil as _sh
    ff = "ffprobe"
    if _sh.which(ff):
        try:
            res = subprocess.run(
                [ff, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(p)],
                capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace"
            )
            if res.returncode == 0 and res.stdout.strip():
                return float(res.stdout.strip())
        except Exception as e:
            log.debug(f"ffprobe Fehler {p}: {e}")
    mi = "mediainfo"
    if _sh.which(mi):
        try:
            res = subprocess.run([mi, "--Output=JSON", str(p)], capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace")
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                tracks = data.get("media", {}).get("track", [])
                for t in tracks:
                    if t.get("@type") == "General":
                        dur = t.get("Duration")
                        if dur:
                            val = float(dur)
                            return val/1000.0 if val > 10000 else val
        except Exception as e:
            log.debug(f"mediainfo Fehler {p}: {e}")
    return -1.0


def rename_and_move_movie(tmp_out: Path, dest_base: Path, base_display: str, log: logging.Logger, dry_run: bool = False) -> bool:
    files = sorted(tmp_out.glob("*.mkv"))
    if not files:
        log.error(f"Keine MKVs in {tmp_out}.")
        return False

    name, year, version = parse_name_year(base_display)
    dest_base.mkdir(parents=True, exist_ok=True)

    # Dauer messen
    durations: Dict[Path, float] = {f: _probe_duration_seconds(f, log) for f in files}
    # Längste zuerst (unbekannt=-1 ⇒ ans Ende)
    files_sorted = sorted(files, key=lambda p: durations.get(p, -1.0), reverse=True)

    main_done = False
    trailer_i = 1
    bonus_i   = 1
    moved     = False

    def mv(src: Path, dst: Path):
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dry_run:
            log.info(f"[DRY-RUN] Move: {src} -> {dst}")
        else:
            shutil.move(str(src), str(dst))
            log.info(f"Verschoben: {src.name} -> {dst}")

    for idx, f in enumerate(files_sorted):
        dur = durations.get(f, -1.0)
        is_trailer = (dur >= 0 and dur <= TRAILER_MAX)
        if not main_done and (idx == 0) and (dur < 0 or dur >= 45*60):
            tgt = f"{name}.mkv" if not version else f"{name} [{version}].mkv"
            mv(f, dest_base / tgt)
            main_done = True; moved = True
        elif is_trailer:
            mv(f, dest_base / (f"{name}_trailer" + (f"-{trailer_i}" if trailer_i > 1 else "") + ".mkv"))
            trailer_i += 1; moved = True
        else:
            mv(f, dest_base / f"{name} [bonusmaterial] - extra{bonus_i:02d}.mkv")
            bonus_i += 1; moved = True

    if not main_done:
        log.warning("Kein plausibler Hauptfilm – Fallback trackNN.")
        for idx, f in enumerate(files_sorted, start=1):
            mv(f, dest_base / f"{name} track{idx:02d}.mkv")
            moved = True

    # tmp Ordnung entfernen
    try:
        if not dry_run:
            shutil.rmtree(tmp_out, ignore_errors=True)
    except Exception:
        pass

    return moved
