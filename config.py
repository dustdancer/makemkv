# -*- coding: utf-8 -*-
from __future__ import annotations
import os
from pathlib import Path
from typing import Dict

def _load_secrets_file() -> Dict[str, str]:
    """
    Liest eine optionale secrets.txt im gleichen Ordner wie main/config.
    Format: key=value; erlaubte Keys (case-insensitive):
      - user/username, pass/password, apikey/tmdb/tmdb_api_key
    """
    secrets: Dict[str, str] = {}
    try:
        here = Path(__file__).resolve().parent
        sec = here / "secrets.txt"
        if not sec.exists():
            return secrets
        for raw in sec.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            key = k.strip().lower()
            val = v.strip()
            if (len(val) >= 2) and (val[0] == val[-1]) and val[0] in ("'", '"'):
                val = val[1:-1]
            if key in ("username",): key = "user"
            if key in ("password",): key = "pass"
            if key in ("tmdb", "tmdb_api_key"): key = "apikey"
            secrets[key] = val
    except Exception:
        pass
    return secrets

CONFIG = {
    "NETWORK": {
        "ENABLE_MOUNT": True,
        "UNC_ROOT": r"\\blickfeldData\downloads",
        "WIN_DRIVE_LETTER": "K:",
        "LINUX_MOUNT_POINT": "/mnt/blickfeldData",
        "LINUX_CIFS_OPTS": "vers=3.0,iocharset=utf8,dir_mode=0775,file_mode=0664",
        # Platzhalter; werden unten aus secrets/env überschrieben
        "USERNAME": "user",
        "PASSWORD": "password",
    },
    "PATHS": {
        "TRANSCODE_REL": r"data\usenet\complete\iso\transcode",
        "REMUX_REL":     r"data\usenet\complete\iso\remux",
        "LOGS_REL":      r"data\usenet\complete\iso\logs",
    },
    "MAKEMKV": {
        "WIN_PATHS": [
            r"C:\Program Files (x86)\MakeMKV\makemkvcon64.exe",
            r"C:\Program Files\MakeMKV\makemkvcon64.exe",
            r"C:\Program Files (x86)\MakeMKV\makemkvcon.exe",
            r"C:\Program Files\MakeMKV\makemkvcon.exe",
        ],
        "LINUX_PATH": "makemkvcon",
        "EXTRA_OPTS": ["--robot"],  # z.B. '--minlength=60'
    },
    "PROBE": {
        "PREFER_FFPROBE": True,
        "FFPROBE_PATH": "ffprobe",
        "MEDIAINFO_PATH": "mediainfo",
    },
    "BEHAVIOR": {
        "DELETE_ORIGINALS": True,
        "DRY_RUN": False,
        "LOG_RETENTION_DAYS": 14,
        "TRAILER_MAX": 240,             # <= 4min Trailer
        "EPISODE_MIN": 18*60,
        "EPISODE_MAX": 65*60,
        "TINY_FILE_BYTES": 100 * 1024 * 1024,    # 100MB
        "EPISODE_TOLERANCE": 0.15,      # ±15%
        "DOUBLE_EP_TOL": 0.12,          # ±12% um 2×Median
        "PLAYALL_MULT_TOL_MIN": 240,    # 4min
        "PLAYALL_MULT_TOL_MAX": 480,    # 8min
        "PLAYALL_FACTOR_MIN": 3.0,      # >=3×Median
        "PLAYALL_FACTOR_SOFT": 2.7,     # ab 2.7×Median ggf. Play-All
        "SIZE_TOLERANCE": 0.22,         # ±22% um Größen-Median (Fallback)
    },
    "TMDB": {
        "API_KEY": "",
        "LANG": "de-DE",
        "TIMEOUT": 8,
    },
    "HOOKS": {
        "MKV_MATCH": {
            "ENABLED": True,
            "BINARY": "mkv-match",
            "EXTRA_ARGS": [],
            "RENAME_TO_SCHEMA": True,
        }
    }
}

# --- Secrets & ENV anwenden: secrets.txt < ENV (ENV gewinnt) ---
_SEC = _load_secrets_file()
if _SEC.get("user"):   CONFIG["NETWORK"]["USERNAME"] = _SEC["user"]
if _SEC.get("pass"):   CONFIG["NETWORK"]["PASSWORD"] = _SEC["pass"]
if _SEC.get("apikey"): CONFIG["TMDB"]["API_KEY"]     = _SEC["apikey"]

_env_user = os.environ.get("BLICKFELD_SMB_USER")
_env_pass = os.environ.get("BLICKFELD_SMB_PASS")
_env_tmdb = os.environ.get("TMDB_API_KEY")
if _env_user: CONFIG["NETWORK"]["USERNAME"] = _env_user
if _env_pass: CONFIG["NETWORK"]["PASSWORD"] = _env_pass
if _env_tmdb: CONFIG["TMDB"]["API_KEY"]     = _env_tmdb
