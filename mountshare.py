# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import shlex
import shutil
import logging
import subprocess
from pathlib import Path
from typing import Optional


def is_windows() -> bool:
    return os.name == "nt"


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _parse_unc(unc: str) -> tuple[str, str]:
    # \\server\share
    if not unc.startswith("\\\\"):
        raise ValueError(f"Ungültiger UNC-Root: {unc}")
    parts = unc.strip("\\").split("\\", 2)
    if len(parts) < 2:
        raise ValueError(f"Ungültiger UNC-Root: {unc}")
    return parts[0], parts[1]


def _mount_windows(unc_root: str, drive: str, user: str, pwd: str, log: logging.Logger, dry_run: bool) -> Optional[Path]:
    drive = drive.rstrip("\\/")
    try:
        subprocess.run(["net", "use", drive, "/delete", "/y"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    except Exception:
        pass
    cmd = ["net", "use", drive, unc_root, pwd, "/user:" + user, "/persistent:no"]
    if dry_run:
        log.info(f"[DRY-RUN] net use: {' '.join(cmd)}")
        return Path(drive + "\\")
    log.info(f"Mappe Netzlaufwerk: {' '.join(cmd)}")
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        log.error(f"net use fehlgeschlagen ({res.returncode}): {res.stdout}\n{res.stderr}")
        return None
    return Path(drive + "\\")  # K:\


def _mount_linux(unc_root: str, mount_point: str, user: str, pwd: str, log: logging.Logger, dry_run: bool) -> Optional[Path]:
    server, share = _parse_unc(unc_root)
    mp = Path(mount_point); ensure_dir(mp)
    opts = f"username={user},password={pwd},vers=3.0,iocharset=utf8,dir_mode=0775,file_mode=0664"
    cmd = ["mount", "-t", "cifs", f"//{server}/{share}", str(mp), "-o", opts]
    if dry_run:
        log.info(f"[DRY-RUN] mount CIFS: {' '.join(shlex.quote(x) for x in cmd)}")
        return mp
    log.info(f"Mount CIFS: {' '.join(shlex.quote(x) for x in cmd)}")
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        log.error(f"mount fehlgeschlagen ({res.returncode}): {res.stdout}\n{res.stderr}")
        return None
    return mp


def get_share_root(
    log: logging.Logger,
    enable_mount: bool,
    unc_root: str,
    win_drive_letter: str,
    linux_mount_point: str,
    username: str,
    password: str,
    dry_run: bool = False,
) -> Optional[Path]:
    if enable_mount:
        return _mount_windows(unc_root, win_drive_letter, username, password, log, dry_run) if is_windows() \
            else _mount_linux(unc_root, linux_mount_point, username, password, log, dry_run)
    return Path(win_drive_letter + "\\") if is_windows() else Path(linux_mount_point)


def delete_path(p: Path, log: logging.Logger, dry_run: bool = False) -> None:
    if dry_run:
        log.info(f"[DRY-RUN] Löschen: {p}")
        return
    try:
        if p.is_file() or p.is_symlink():
            p.unlink(missing_ok=True)
            log.info(f"Datei gelöscht: {p}")
        elif p.is_dir():
            import shutil
            shutil.rmtree(p, ignore_errors=True)
            log.info(f"Ordner gelöscht: {p}")
    except Exception as e:
        log.warning(f"Konnte {p} nicht löschen: {e}")
