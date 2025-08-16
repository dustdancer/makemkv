# -*- coding: utf-8 -*-
from __future__ import annotations
import json, shutil, subprocess, logging
from pathlib import Path
from typing import Optional
from config import CONFIG

def _probe_ffprobe(path: Path, log: logging.Logger) -> Optional[float]:
    ff = CONFIG["PROBE"]["FFPROBE_PATH"]
    if not shutil.which(ff): return None
    try:
        res = subprocess.run(
            [ff, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace"
        )
        if res.returncode == 0 and res.stdout.strip():
            return float(res.stdout.strip())
    except Exception as e:
        log.debug(f"ffprobe Fehler {path}: {e}")
    return None

def _probe_mediainfo(path: Path, log: logging.Logger) -> Optional[float]:
    mi = CONFIG["PROBE"]["MEDIAINFO_PATH"]
    if not shutil.which(mi): return None
    try:
        res = subprocess.run([mi, "--Output=JSON", str(path)],
                             capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace")
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout)
            tracks = data.get("media", {}).get("track", [])
            for t in tracks:
                if t.get("@type") == "General":
                    dur = t.get("Duration")
                    if dur:
                        val = float(dur)
                        return val/1000.0 if val > 10000 else val
    except Exception as e:
        log.debug(f"mediainfo Fehler {path}: {e}")
    return None

def probe_duration_seconds(p: Path, log: logging.Logger) -> Optional[float]:
    if CONFIG["PROBE"]["PREFER_FFPROBE"]:
        d = _probe_ffprobe(p, log)
        return d if d is not None else _probe_mediainfo(p, log)
    d = _probe_mediainfo(p, log)
    return d if d is not None else _probe_ffprobe(p, log)
