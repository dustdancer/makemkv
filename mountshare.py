# -*- coding: utf-8 -*-
"""
Hilfsfunktionen für das Arbeiten mit dem Netzlaufwerk/Share.

Stellt die Funktionen bereit, die in main.py importiert werden:
- is_windows()
- ensure_dir(Path)
- get_share_root(logger)  -> Path | None
- delete_path(Path, logger)

Environment-Variablen (optional):
- BLICKFELD_UNC_ROOT      z.B. \\\\blickfeldData\\downloads
- BLICKFELD_WIN_DRIVE     z.B. K:   (Default: K:)
- BLICKFELD_LINUX_MOUNT   z.B. /mnt/blickfeldData (Default: /mnt/blickfeldData)
- BLICKFELD_SMB_USER
- BLICKFELD_SMB_PASS
- BLICKFELD_MAP           "1" => unter Windows per `net use` verbinden (wenn UNC+Creds da sind)
"""

from __future__ import annotations
import os
import shutil
import subprocess
import logging
from pathlib import Path
from typing import Optional, Tuple


def is_windows() -> bool:
    return os.name == "nt"


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


# ---- interne Helfer ---------------------------------------------------------

def _parse_unc(unc: str) -> Tuple[str, str]:
    unc = unc.strip().lstrip("\\")
    parts = unc.split("\\")
    if len(parts) < 2:
        raise ValueError(f"Ungültiger UNC-Pfad: {unc!r}")
    return parts[0], parts[1]


def _net_use_map(drive: str, unc: str, user: str, pwd: str, log: logging.Logger) -> Optional[Path]:
    """Versucht unter Windows das Netzlaufwerk zu mappen."""
    drive = drive.rstrip("\\/")
    try:
        # Altes Mapping entfernen (ignorieren, wenn nicht vorhanden)
        subprocess.run(
            ["net", "use", drive, "/delete", "/y"],
            capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        cmd = ["net", "use", drive, unc, pwd, "/user:" + user, "/persistent:no"]
        log.info(f"Mappe Netzlaufwerk: {' '.join(cmd)}")
        res = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        if res.returncode != 0:
            log.error(f"net use fehlgeschlagen ({res.returncode}): {res.stdout}\n{res.stderr}")
            return None
        return Path(drive + "\\")
    except Exception as e:
        log.exception(f"Windows Netzlaufwerk Fehler: {e}")
        return None


# ---- Public API -------------------------------------------------------------

def get_share_root(log: logging.Logger) -> Optional[Path]:
    """
    Liefert die Basis des Shares zurück.

    Logik:
    - Windows:
        - Wenn BLICKFELD_MAP == "1" und UNC + USER + PASS vorhanden ⇒ `net use` Mapping versuchen.
        - Sonst nur das Laufwerk zurückgeben (Default K:\).
    - Linux:
        - Gibt den Mountpoint zurück (Default /mnt/blickfeldData). Ein automatisches Mounten
          wird hier NICHT versucht.
    """
    unc = os.environ.get("BLICKFELD_UNC_ROOT", r"\\blickfeldData\downloads")
    win_drive = os.environ.get("BLICKFELD_WIN_DRIVE", "K:")
    linux_mp = os.environ.get("BLICKFELD_LINUX_MOUNT", "/mnt/blickfeldData")
    want_map = os.environ.get("BLICKFELD_MAP", "0") == "1"

    if is_windows():
        base = Path(win_drive + "\\")
        if want_map:
            user = os.environ.get("BLICKFELD_SMB_USER")
            pwd = os.environ.get("BLICKFELD_SMB_PASS")
            if user and pwd and unc:
                mapped = _net_use_map(win_drive, unc, user, pwd, log)
                if mapped:
                    return mapped
        # Fallback: nur Laufwerk zurückgeben
        return base
    else:
        return Path(linux_mp)


def delete_path(p: Path, log: logging.Logger) -> None:
    """
    Löscht Datei/Link/Ordner rekursiv. Existiert der Pfad nicht, wird geloggt und beendet.
    """
    try:
        if not p.exists():
            log.info(f"Löschen übersprungen – Pfad existiert nicht: {p}")
            return
        if p.is_file() or p.is_symlink():
            p.unlink(missing_ok=True)
            log.info(f"Datei gelöscht: {p}")
        elif p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
            log.info(f"Ordner gelöscht: {p}")
        else:
            # Unbekannter Typ – trotzdem versuchen
            try:
                p.unlink(missing_ok=True)
                log.info(f"Pfad gelöscht: {p}")
            except Exception:
                shutil.rmtree(p, ignore_errors=True)
                log.info(f"Pfad rekursiv gelöscht: {p}")
    except Exception as e:
        log.exception(f"Löschen fehlgeschlagen für {p}: {e}")
