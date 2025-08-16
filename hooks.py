# -*- coding: utf-8 -*-
from __future__ import annotations
import shutil, shlex, subprocess, logging, re
from pathlib import Path
from typing import Optional
from config import CONFIG
from utils import sanitize_filename
from logui import ConsoleUI

def run_mkv_match(show_dir: Path, season_no: Optional[int], series_name: Optional[str],
                  log: logging.Logger, ui: Optional[ConsoleUI] = None) -> bool:
    hk = CONFIG.get("HOOKS", {}).get("MKV_MATCH", {})
    if not hk or not hk.get("ENABLED", False):
        return False
    bin_name = hk.get("BINARY", "mkv-match")
    if not shutil.which(bin_name):
        log.info("mkv-match nicht gefunden (nicht im PATH) – Hook wird übersprungen.")
        return False

    args = [bin_name, "--show-dir", str(show_dir)]
    if season_no is not None:
        args += ["--season", str(season_no)]
    api = CONFIG["TMDB"].get("API_KEY")
    if api:
        args += ["--tmdb-api-key", api]
    extra = hk.get("EXTRA_ARGS", []) or []
    args.extend(extra)

    log.info(f"[HOOK] mkv-match: {' '.join(shlex.quote(x) for x in args)}")
    if ui is None:
        ui = ConsoleUI(True)

    if CONFIG["BEHAVIOR"].get("DRY_RUN", False):
        log.info("[DRY-RUN] mkv-match nicht ausgeführt.")
        return True

    try:
        with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace", bufsize=1) as proc:
            for line in proc.stdout or []:
                if ui: ui.spin(f"mkv-match: {show_dir.name}")
                log.debug(f"mkv-match | {line.rstrip()}")
            rc = proc.wait()
        ui.done()
        if rc != 0:
            log.warning(f"mkv-match Returncode {rc} – evtl. kein Match/Teilerfolg.")
            return False
        return True
    except Exception as e:
        ui.done()
        log.exception(f"mkv-match Fehler: {e}")
        return False

def normalize_mkv_match_naming(show_dir: Path, series_base: Optional[str],
                               season_no: Optional[int], log: logging.Logger) -> None:
    """Benennt Dateien in 'Serienname – SxxExx - Episodentitel.mkv' um (nur wenn S/E vorhanden)."""
    base = series_base or show_dir.parent.name
    series_name = sanitize_filename(base)

    def make_unique(dst: Path) -> Path:
        if not dst.exists(): return dst
        stem, ext = dst.stem, dst.suffix
        i = 1
        while True:
            cand = dst.with_name(f"{stem} ({i}){ext}")
            if not cand.exists(): return cand
            i += 1

    pat = re.compile(r"(?i)S(\d{1,2})E(\d{2})(?:[-_ ]?E(\d{2}))?")

    for f in sorted(show_dir.glob("*.mkv")):
        m = pat.search(f.name)
        if not m: continue
        s  = int(m.group(1))
        e1 = int(m.group(2))
        e2 = m.group(3)
        title = pat.sub("", f.stem)
        title = re.sub(r"^[\s\-_.]+|[\s\-_.]+$", "", title)
        title = title.replace("_", " ").replace(".", " ")
        title = re.sub(r"\s+", " ", title).strip()
        title = sanitize_filename(title) if title else None

        if season_no is not None and s != season_no:
            pass  # nicht hart umbenennen, aber erlauben

        if e2:
            new_name = f"{series_name} – S{s:02d}E{e1:02d}-E{int(e2):02d}"
        else:
            new_name = f"{series_name} – S{s:02d}E{e1:02d}"
        if title:
            new_name += f" - {title}"
        new_path = make_unique(f.with_name(new_name + f.suffix))

        if CONFIG["BEHAVIOR"].get("DRY_RUN", False):
            log.info(f"[DRY-RUN] Rename: {f.name} -> {new_path.name}")
        else:
            try:
                f.rename(new_path)
                log.info(f"Rename: {f.name} -> {new_path.name}")
            except Exception as e:
                log.warning(f"Rename fehlgeschlagen für {f.name}: {e}")
