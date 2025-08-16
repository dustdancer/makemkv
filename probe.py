# file: makemkv/probe.py
from __future__ import annotations

"""
Medien-Analyse (Dauer etc.) für MKV/MP4/TS – nutzt ffprobe oder mediainfo.

- probe_duration_seconds(path): Dauer in Sekunden (float) oder None, wenn unbekannt
- durations_for_files(files): Dict[Path, Dauer] (unbekannt = -1.0) + ausführliches Logging

Konfiguration:
  CONFIG['PROBE'] = {
      'PREFER_FFPROBE': True,
      'FFPROBE_PATH': 'ffprobe',
      'MEDIAINFO_PATH': 'mediainfo',
  }
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from .config import CONFIG

__all__ = [
    "probe_duration_seconds",
    "durations_for_files",
]


def _probe_ffprobe(path: Path, log) -> Optional[float]:
    """Versucht Dauer via ffprobe zu lesen (Sekunden)."""
    ff = CONFIG["PROBE"].get("FFPROBE_PATH", "ffprobe")
    if not shutil.which(ff):
        return None
    try:
        res = subprocess.run(
            [
                ff, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        out = (res.stdout or "").strip()
        if res.returncode == 0 and out:
            return float(out)
    except Exception as e:
        log.debug(f"ffprobe Fehler {path}: {e}")
    return None


def _probe_mediainfo(path: Path, log) -> Optional[float]:
    """Versucht Dauer via mediainfo zu lesen (Sekunden)."""
    mi = CONFIG["PROBE"].get("MEDIAINFO_PATH", "mediainfo")
    if not shutil.which(mi):
        return None
    try:
        res = subprocess.run(
            [mi, "--Output=JSON", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if res.returncode != 0:
            return None
        data = json.loads(res.stdout or "{}")
        tracks = data.get("media", {}).get("track", [])
        # mediainfo liefert Dauer entweder in ms oder s (abh. von Version/Container)
        for t in tracks:
            if t.get("@type") == "General":
                # Reihenfolge: Duration (float), sonst Duration/String (z.B. "1 h 3 min")
                if "Duration" in t:
                    val = float(t["Duration"])
                    # Heuristik: Werte > 10_000 sind sehr wahrscheinlich Millisekunden
                    return val / 1000.0 if val > 10000 else val
                # Fallback: parse Duration/String grob (nur Minuten/Sekunden)
                dstr = t.get("Duration/String") or t.get("Duration/String1")
                if dstr:
                    # sehr vereinfachtes Parsing: "1 h 2 min 3 s", "42 min", "90 s"
                    total = 0.0
                    import re as _re
                    m = _re.search(r"(\d+)\s*h", dstr)
                    if m:
                        total += int(m.group(1)) * 3600
                    m = _re.search(r"(\d+)\s*min", dstr)
                    if m:
                        total += int(m.group(1)) * 60
                    m = _re.search(r"(\d+)\s*s", dstr)
                    if m:
                        total += int(m.group(1))
                    if total > 0:
                        return total
    except Exception as e:
        log.debug(f"mediainfo Fehler {path}: {e}")
    return None


def probe_duration_seconds(path: Path, log) -> Optional[float]:
    """
    Liefert die Dauer in Sekunden (float) oder None, wenn nicht ermittelbar.
    Bevorzugt ffprobe, fällt zurück auf mediainfo (oder umgekehrt – je nach CONFIG).
    """
    prefer_ff = bool(CONFIG["PROBE"].get("PREFER_FFPROBE", True))
    if prefer_ff:
        d = _probe_ffprobe(path, log)
        if d is not None:
            return d
        return _probe_mediainfo(path, log)
    else:
        d = _probe_mediainfo(path, log)
        if d is not None:
            return d
        return _probe_ffprobe(path, log)


def durations_for_files(files: List[Path], log) -> Dict[Path, float]:
    """
    Ermittelt Dauern für mehrere Dateien.
    Rückgabe: Dict[Path, DauerSek] – unbekannt = -1.0
    Loggt zusätzlich die Dateigröße zur späteren Heuristik.
    """
    result: Dict[Path, float] = {}
    for f in files:
        d = probe_duration_seconds(f, log)
        dur = float(d) if d is not None else -1.0
        try:
            size = f.stat().st_size
        except FileNotFoundError:
            size = -1
        result[f] = dur
        log.debug(f"Dauer {f.name}: {dur:.1f} s | Größe: {size} B")
    return result
