# file: mountshare.py
from __future__ import annotations
import os
import re
import shlex
import shutil
import logging
import subprocess
from pathlib import Path
from typing import Optional, Tuple

# --- Config laden: absolut zuerst, relativer Fallback ---
try:
    from config import CONFIG
except ImportError:  # wenn via "python -m makemkv.main" gestartet
    from .config import CONFIG  # type: ignore

__all__ = ["get_share_root", "mount_windows", "mount_linux", "parse_unc"]

# --- kleine Helfer, kein utils-Import nötig ---
def is_windows() -> bool:
    return os.name == "nt"

def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

# --- UNC parsen ---
def parse_unc(unc: str) -> Tuple[str, str]:
    """
    Erwartet z.B. \\\\SERVER\\Freigabe
    Rückgabe: ("SERVER", "Freigabe")
    """
    m = re.match(r"^\\\\([^\\]+)\\([^\\]+)", unc)
    if not m:
        raise ValueError(f"Ungültiger UNC-Root: {unc!r}")
    return m.group(1), m.group(2)

# --- Windows: Netzlaufwerk mappen ---
def mount_windows(unc_root: str, drive: str, user: str, pwd: str, log: logging.Logger) -> Optional[Path]:
    drive = drive.rstrip("\\/")  # "K:" ohne Slash
    # ggf. vorhandene Zuordnung entfernen (ignoriert Fehler)
    try:
        subprocess.run(
            ["net", "use", drive, "/delete", "/y"],
            capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
    except Exception:
        pass

    cmd = ["net", "use", drive, unc_root, pwd, "/user:" + user, "/persistent:no"]
    if CONFIG["BEHAVIOR"].get("DRY_RUN", False):
        log.info(f"[DRY-RUN] net use: {' '.join(cmd)}")
        return Path(drive + "\\")
    log.info(f"Mappe Netzlaufwerk: {' '.join(cmd)}")
    res = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if res.returncode != 0:
        log.error(f"net use fehlgeschlagen ({res.returncode}): {res.stdout}\n{res.stderr}")
        return None
    return Path(drive + "\\")

# --- Linux: CIFS mounten ---
def mount_linux(unc_root: str, mount_point: str, user: str, pwd: str, log: logging.Logger) -> Optional[Path]:
    server, share = parse_unc(unc_root)
    mp = Path(mount_point)
    ensure_dir(mp)
    opts = CONFIG["NETWORK"].get("LINUX_CIFS_OPTS", "vers=3.0,iocharset=utf8,dir_mode=0775,file_mode=0664")
    uid, gid = os.getuid(), os.getgid()
    opt_str = f"username={user},password={pwd},{opts},uid={uid},gid={gid}"
    cmd = ["mount", "-t", "cifs", f"//{server}/{share}", str(mp), "-o", opt_str]

    if CONFIG["BEHAVIOR"].get("DRY_RUN", False):
        log.info(f"[DRY-RUN] mount CIFS: {' '.join(shlex.quote(x) for x in cmd)}")
        return mp

    log.info(f"Mount CIFS: {' '.join(shlex.quote(x) for x in cmd)}")
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        log.error(f"mount fehlgeschlagen ({res.returncode}): {res.stdout}\n{res.stderr}")
        return None
    return mp

# --- Root der Freigabe beschaffen (oder mappen/mounten) ---
def get_share_root(log: logging.Logger) -> Optional[Path]:
    net = CONFIG["NETWORK"]
    unc_root = net["UNC_ROOT"]
    if net.get("ENABLE_MOUNT", True):
        if is_windows():
            return mount_windows(unc_root, net["WIN_DRIVE_LETTER"], net["USERNAME"], net["PASSWORD"], log)
        else:
            return mount_linux(unc_root, net["LINUX_MOUNT_POINT"], net["USERNAME"], net["PASSWORD"], log)
    # Mount ist deaktiviert: direkten Pfad benutzen
    if is_windows():
        # wenn das Laufwerk bereits gemappt ist, z.B. "K:\"
        p = Path(net["WIN_DRIVE_LETTER"] + "\\")
        return p if p.exists() else Path(unc_root)
    else:
        return Path(net["LINUX_MOUNT_POINT"])
