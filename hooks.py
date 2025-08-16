# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import shutil
import logging
import subprocess
from pathlib import Path
from typing import Optional

from naming import parse_name_year, sanitize_filename


def run_mkv_match(show_dir: Path, season_no: Optional[int], series_name: Optional[str], log: logging.Logger, dry_run: bool = False) -> bool:
    bin_name = "mkv-match"
    if not shutil.which(bin_name):
        log.info("mkv-match nicht gefunden (im PATH) – Hook wird übersprungen.")
        return False
    args = [bin_name, "--show-dir", str(show_dir)]
    if season_no is not None:
        args += ["--season", str(season_no)]
    if dry_run:
        log.info(f"[DRY-RUN] mkv-match: {' '.join(args)}")
        return True
    log.info(f"[HOOK] mkv-match: {' '.join(args)}")
    try:
        rc = subprocess.call(args)
        if rc != 0:
            log.warning(f"mkv-match Returncode {rc}")
            return False
        return True
    except Exception as e:
        log.warning(f"mkv-match Fehler: {e}")
        return False


def normalize_mkv_match_naming(show_dir: Path, series_base: Optional[str], season_no: Optional[int], log: logging.Logger, dry_run: bool = False) -> None:
    base = series_base or show_dir.parent.name
    series_name, year_hint, _ = parse_name_year(base)

    pat = re.compile(r"(?i)S(\d{1,2})E(\d{2})(?:[-_ ]?E(\d{2}))?")

    def unique(dst: Path) -> Path:
        if not dst.exists():
            return dst
        i = 1
        while True:
            cand = dst.with_name(f"{dst.stem} ({i}){dst.suffix}")
            if not cand.exists():
                return cand
            i += 1

    for f in sorted(show_dir.glob("*.mkv")):
        m = pat.search(f.name)
        if not m:
            continue
        s = int(m.group(1))
        e1 = int(m.group(2))
        e2 = m.group(3)
        title = pat.sub("", f.stem)
        title = re.sub(r"^[\s\-_.]+|[\s\-_.]+$", "", title).replace("_", " ").replace(".", " ")
        title = re.sub(r"\s+", " ", title).strip()
        title = sanitize_filename(title) if title else None

        new_name = f"{series_name} – S{s:02d}E{e1:02d}" + (f"-E{int(e2):02d}" if e2 else "")
        if title:
            new_name += f" - {title}"
        new_path = unique(f.with_name(new_name + f.suffix))

        if dry_run:
            log.info(f"[DRY-RUN] Rename: {f.name} -> {new_path.name}")
        else:
            try:
                f.rename(new_path)
                log.info(f"Rename: {f.name} -> {new_path.name}")
            except Exception as e:
                log.warning(f"Rename fehlgeschlagen für {f.name}: {e}")
