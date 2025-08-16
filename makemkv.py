# -*- coding: utf-8 -*-
from __future__ import annotations
import shutil, shlex, logging, subprocess, re
from pathlib import Path
from typing import Optional, Tuple
from config import CONFIG
from logui import ConsoleUI

def find_makemkvcon(log: logging.Logger) -> Optional[str]:
    import os
    if os.name == "nt":
        for p in CONFIG["MAKEMKV"]["WIN_PATHS"]:
            if Path(p).exists():
                log.info(f"MakeMKV gefunden: {p}")
                return p
        log.warning("MakeMKV-CLI nicht gefunden (Windows). Pfade in CONFIG prüfen.")
        return None
    p = shutil.which(CONFIG["MAKEMKV"]["LINUX_PATH"]) or CONFIG["MAKEMKV"]["LINUX_PATH"]
    if shutil.which(p) or Path(p).exists():
        log.info(f"MakeMKV gefunden: {p}")
        return p
    log.warning("makemkvcon nicht im PATH (Linux). CONFIG['MAKEMKV']['LINUX_PATH'] setzen.")
    return None

def _parse_prgv(line: str) -> Optional[Tuple[int, int]]:
    """PRGV:<job>,<cur>,<total> → (cur,total)"""
    if not line.startswith("PRGV:"): return None
    try:
        parts = line.strip().split(":")[1].split(",")
        if len(parts) >= 3:
            return int(parts[1]), int(parts[2])
    except Exception:
        pass
    return None

def _parse_total_titles(line: str) -> Optional[int]:
    """
    MSG:5014,...,"5 Titel werden in Verzeichnis file://... gespeichert"
    """
    m = re.search(r'MSG:5014[^"]*"(\d+)\s+Titel', line)
    if m:
        try: return int(m.group(1))
        except: return None
    return None

def run_makemkv(
    makemkv: str,
    source_kind: str,
    source_path: Path,
    out_dir: Path,
    log: logging.Logger,
    ui: Optional[ConsoleUI] = None,
    disc_index: Optional[int] = None,
    disc_total: Optional[int] = None,
) -> bool:
    out_dir.mkdir(parents=True, exist_ok=True)
    if ui is None:
        ui = ConsoleUI(True)
    extra = CONFIG["MAKEMKV"]["EXTRA_OPTS"] or []
    input_spec = f"iso:{str(source_path)}" if source_kind == "iso" else f"file:{str(source_path)}"
    cmd = [makemkv, "mkv"] + extra + [input_spec, "all", str(out_dir)]
    log.info(f"MakeMKV: {' '.join(shlex.quote(x) for x in cmd)}")
    if CONFIG["BEHAVIOR"]["DRY_RUN"]:
        log.info("[DRY-RUN] MakeMKV nicht ausgeführt.")
        return True

    track_total: Optional[int] = None
    last_bar_cur, last_bar_total = 0, 0
    try:
        with subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1
        ) as proc:
            while True:
                line = proc.stdout.readline() if proc.stdout else ""
                if not line:
                    break
                s = line.rstrip("\r\n")
                log.debug(s)

                # total tracks?
                if track_total is None:
                    maybe = _parse_total_titles(s)
                    if maybe:
                        track_total = maybe

                # progress?
                pr = _parse_prgv(s)
                if pr:
                    last_bar_cur, last_bar_total = pr
                    # bereits erzeugte MKVs zählen
                    done_tracks = len(list(out_dir.glob("*.mkv")))
                    suffix = []
                    if track_total is not None:
                        suffix.append(f"Tracks {done_tracks}/{track_total}")
                    if disc_index is not None and disc_total is not None:
                        suffix.append(f"Disc {disc_index}/{disc_total}")
                    ui.bar(f"Remux: {source_path.name}", pr[0], pr[1], " | ".join(suffix))
                else:
                    # spinner mit den selben infos
                    done_tracks = len(list(out_dir.glob("*.mkv")))
                    suffix = []
                    if track_total is not None:
                        suffix.append(f"Tracks {done_tracks}/{track_total}")
                    if disc_index is not None and disc_total is not None:
                        suffix.append(f"Disc {disc_index}/{disc_total}")
                    ui.spin(f"Remux läuft: {source_path.name}", " | ".join(suffix))

            rc = proc.wait()
        ui.done()
        if rc != 0:
            log.error(f"MakeMKV Returncode {rc} – Quelle: {source_path}")
            return False
        # falls nie PRGV kam, trotzdem “Done” visualisiert
        if last_bar_total == 0:
            ui.done()
        return True
    except Exception as e:
        ui.done()
        log.exception(f"Fehler beim MakeMKV-Aufruf: {e}")
        return False
