# -*- coding: utf-8 -*-
from __future__ import annotations

import shlex
import shutil
import logging
import subprocess
from pathlib import Path
from typing import Optional


_WIN_PATHS = [
    r"C:\Program Files (x86)\MakeMKV\makemkvcon64.exe",
    r"C:\Program Files\MakeMKV\makemkvcon64.exe",
    r"C:\Program Files (x86)\MakeMKV\makemkvcon.exe",
    r"C:\Program Files\MakeMKV\makemkvcon.exe",
]


def find_makemkvcon(log: logging.Logger) -> Optional[str]:
    # Windows
    for p in _WIN_PATHS:
        if Path(p).exists():
            log.info(f"MakeMKV gefunden: {p}")
            return p
    # Unix
    p = shutil.which("makemkvcon") or "makemkvcon"
    if shutil.which(p) or Path(p).exists():
        log.info(f"MakeMKV gefunden: {p}")
        return p
    log.warning("MakeMKV-CLI nicht gefunden.")
    return None


def run_makemkv(makemkv: str, source_path: Path, out_dir: Path, log: logging.Logger, dry_run: bool = False) -> bool:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [makemkv, "mkv", "--robot", f"file:{str(source_path)}", "all", str(out_dir)]
    log.info(f"MakeMKV: {' '.join(shlex.quote(x) for x in cmd)}")

    if dry_run:
        log.info("[DRY-RUN] MakeMKV nicht ausgeführt.")
        return True

    try:
        with subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1
        ) as proc:
            for line in proc.stdout or []:
                log.debug(line.rstrip("\r\n"))
            rc = proc.wait()
        if rc != 0:
            # Häufig: 10 = ungültiger Pfad (kein VIDEO_TS/BDMV oder keine ISO)
            if rc == 10:
                log.error("MakeMKV Returncode 10 – Prüfe bitte, ob auf einen gültigen Disc-Ordner (BDMV/VIDEO_TS) oder eine .iso-Datei verwiesen wird.")
            else:
                log.error(f"MakeMKV Returncode {rc} – Quelle: {source_path}")
            return False
        return True
    except Exception as e:
        log.exception(f"Fehler beim MakeMKV-Aufruf: {e}")
        return False
