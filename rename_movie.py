# -*- coding: utf-8 -*-
from __future__ import annotations
import shutil, logging
from pathlib import Path
from typing import List, Dict
from config import CONFIG
from probe import probe_duration_seconds
from naming import parse_name_year
from utils import ensure_dir

def _durations_for_files(files: List[Path], log: logging.Logger) -> Dict[Path, float]:
    d: Dict[Path, float] = {}
    for f in files:
        dur = probe_duration_seconds(f, log)
        d[f] = dur if dur is not None else -1.0
        try:
            size = f.stat().st_size
        except FileNotFoundError:
            size = -1
        log.debug(f"Dauer {f.name}: {d[f]} s  | Größe: {size} B")
    return d

def rename_and_move_movie(tmp_out: Path, dest_base: Path, base_display: str, log: logging.Logger) -> bool:
    files = sorted(tmp_out.glob("*.mkv"))
    if not files:
        log.error(f"Keine MKVs in {tmp_out}.")
        return False

    name, year, version = parse_name_year(base_display)
    ensure_dir(dest_base)

    durations = _durations_for_files(files, log)
    # Sortierung: Dauer absteigend (unbekannt=-1 ans Ende), dann Größe absteigend, dann Name
    files_sorted = sorted(
        files,
        key=lambda p: (
            durations.get(p, -1.0) if durations.get(p, -1.0) >= 0 else float("-inf"),
            -p.stat().st_size if p.exists() else 0,
            p.name,
        ),
        reverse=True,
    )

    TR = CONFIG["BEHAVIOR"]["TRAILER_MAX"]
    main_done = False; trailer_counter = 1; bonus_counter = 1; ok = False

    def mv(src: Path, dst: Path):
        ensure_dir(dst.parent)
        if CONFIG["BEHAVIOR"]["DRY_RUN"]:
            log.info(f"[DRY-RUN] Move: {src} -> {dst}")
        else:
            shutil.move(str(src), str(dst))
            log.info(f"Verschoben: {src.name} -> {dst}")

    for idx, f in enumerate(files_sorted):
        dur = durations.get(f, -1.0)
        is_trailer = dur >= 0 and dur <= TR
        if not main_done and (idx == 0) and (dur < 0 or dur >= 45*60):
            tgt_name = f"{name}.mkv" if not version else f"{name} [{version}].mkv"
            mv(f, dest_base / tgt_name)
            main_done = True; ok = True
        elif is_trailer:
            mv(f, dest_base / f"{name}_trailer{('-' + str(trailer_counter)) if trailer_counter > 1 else ''}.mkv")
            trailer_counter += 1; ok = True
        else:
            mv(f, dest_base / f"{name} [bonusmaterial] - extra{bonus_counter:02d}.mkv")
            bonus_counter += 1; ok = True

    if not main_done:
        log.warning("Kein plausibler Hauptfilm – Fallback trackNN.")
        for idx, f in enumerate(files_sorted):
            mv(f, dest_base / f"{name} track{idx+1:02d}.mkv")
            ok = True

    try:
        if not CONFIG["BEHAVIOR"]["DRY_RUN"]:
            shutil.rmtree(tmp_out, ignore_errors=True)
    except Exception:
        pass
    return ok
