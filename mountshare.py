# -*- coding: utf-8 -*-
from __future__ import annotations
import os, re, shlex, subprocess, shutil, logging
from pathlib import Path
from typing import Optional, Tuple
from config import CONFIG
from utils import ensure_dir, is_windows

def parse_unc(unc: str) -> Tuple[str, str]:
    m = re.match(r"^\\\\([^\\]+)\\([^\\]+)", unc)
    if not m:
        raise ValueError(f"Ungültiger UNC-Root: {unc}")
    return m.group(1), m.group(2)

def mount_windows(unc_root: str, drive: str, user: str, pwd: str, log: logging.Logger) -> Optional[Path]:
    drive = drive.rstrip("\\/")
    try:
        subprocess.run(["net", "use", drive, "/delete", "/y"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
        cmd = ["net", "use", drive, unc_root, pwd, "/user:"+user, "/persistent:no"]
        if CONFIG["BEHAVIOR"]["DRY_RUN"]:
            log.info(f"[DRY-RUN] net use: {' '.join(cmd)}")
        else:
            log.info(f"Mappe Netzlaufwerk: {' '.join(cmd)}")
            res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if res.returncode != 0:
                log.error(f"net use fehlgeschlagen ({res.returncode}): {res.stdout}\n{res.stderr}")
                return None
        return Path(drive + "\\")
    except Exception as e:
        log.exception(f"Windows Netzlaufwerk Fehler: {e}")
        return None

def mount_linux(unc_root: str, mount_point: str, user: str, pwd: str, log: logging.Logger) -> Optional[Path]:
    server, share = parse_unc(unc_root)
    mp = Path(mount_point); ensure_dir(mp)
    opts = CONFIG["NETWORK"]["LINUX_CIFS_OPTS"]
    uid, gid = os.getuid(), os.getgid()
    opt_str = f"username={user},password={pwd},{opts},uid={uid},gid={gid}"
    cmd = ["mount", "-t", "cifs", f"//{server}/{share}", str(mp), "-o", opt_str]
    if CONFIG["BEHAVIOR"]["DRY_RUN"]:
        log.info(f"[DRY-RUN] mount CIFS: {' '.join(shlex.quote(x) for x in cmd)}"); return mp
    log.info(f"Mount CIFS: {' '.join(shlex.quote(x) for x in cmd)}")
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        log.error(f"mount fehlgeschlagen ({res.returncode}): {res.stdout}\n{res.stderr}")
        return None
    return mp

def get_share_root(log: logging.Logger) -> Optional[Path]:
    net = CONFIG["NETWORK"]
    if not net["ENABLE_MOUNT"]:
        return Path(net["UNC_ROOT"]) if is_windows() else Path(net["LINUX_MOUNT_POINT"])
    if is_windows():
        return mount_windows(net["UNC_ROOT"], net["WIN_DRIVE_LETTER"], net["USERNAME"], net["PASSWORD"], log)
    return mount_linux(net["UNC_ROOT"], net["LINUX_MOUNT_POINT"], net["USERNAME"], net["PASSWORD"], log)
