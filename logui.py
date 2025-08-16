# file: logui.py
from __future__ import annotations
import sys
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Tuple

# --- Projekt-Config laden: absolute zuerst, relativer Fallback ---
try:
    from config import CONFIG
except ImportError:  # wenn als Paket gestartet (python -m makemkv.main)
    from .config import CONFIG  # type: ignore

# --- winzige Helfer lokal (kein utils-Import nötig) ---
def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def now_stamp() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d-%H-%M")

class ConsoleUI:
    """Einfache Terminal-UI (Spinner + Fortschrittsbalken).
       Optionales 'extra' Feld für Zusatzinfos (z.B. Tracks/Discs)."""
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._last_len = 0
        self._spinner = ['|', '/', '-', '\\']
        self._si = 0

    def write(self, text: str) -> None:
        if not self.enabled:
            return
        try:
            sys.stdout.write('\r' + text + ' ' * max(0, self._last_len - len(text)))
            sys.stdout.flush()
            self._last_len = len(text)
        except Exception:
            pass

    def bar(self, prefix: str, current: int, total: int, width: int = 28, extra: str | None = None) -> None:
        if not self.enabled:
            return
        total = max(1, total)
        pct = max(0.0, min(1.0, current / total))
        filled = int(width * pct)
        bar = '[' + '#' * filled + '-' * (width - filled) + f'] {current}/{total} {pct*100:5.1f}%'
        suffix = f"  {extra}" if extra else ""
        self.write(f"{prefix} {bar}{suffix}")

    def spin(self, prefix: str, extra: str | None = None) -> None:
        if not self.enabled:
            return
        ch = self._spinner[self._si % len(self._spinner)]
        self._si += 1
        suffix = f"  {extra}" if extra else ""
        self.write(f"{prefix} {ch}{suffix}")

    def done(self) -> None:
        if not self.enabled:
            return
        try:
            sys.stdout.write('\n')
            sys.stdout.flush()
        except Exception:
            pass
        self._last_len = 0

def setup_loggers(logs_dir: Path) -> Tuple[logging.Logger, logging.Logger, Path, Path]:
    """Erzeugt Auslese- und Remux-Logger + Logrotation; gibt auch die Log-Dateipfade zurück."""
    ensure_dir(logs_dir)
    ts = now_stamp()
    auslesen_log_path = logs_dir / f"{ts}_auslesen.txt"
    remux_log_path    = logs_dir / f"{ts}_remux.txt"

    def mk(name: str, path: Path) -> logging.Logger:
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.setLevel(logging.DEBUG)
        fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", "%Y-%m-%d %H:%M:%S")
        fh = logging.FileHandler(path, encoding="utf-8")
        fh.setLevel(logging.DEBUG); fh.setFormatter(fmt)
        sh = logging.StreamHandler(sys.stdout)
        sh.setLevel(logging.INFO); sh.setFormatter(fmt)
        lg.addHandler(fh); lg.addHandler(sh)
        return lg

    auslesen_logger = mk("auslesen", auslesen_log_path)
    remux_logger    = mk("remux",    remux_log_path)

    # Logrotation
    keep_days = CONFIG["BEHAVIOR"].get("LOG_RETENTION_DAYS", 14)
    now = datetime.now().astimezone()
    for f in logs_dir.glob("*.txt"):
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime).astimezone()
            if (now - mtime) > timedelta(days=keep_days):
                f.unlink(missing_ok=True)
        except Exception as e:
            remux_logger.warning(f"Log-Cleanup Problem bei {f}: {e}")

    # Sichtbar protokollieren, ob secrets/env gegriffen haben
    user = CONFIG["NETWORK"].get("USERNAME", "")
    tmdb = CONFIG["TMDB"].get("API_KEY", "")
    auslesen_logger.info(f"SMB-User: {user}")
    if tmdb:
        mask = tmdb[:4] + ("*" * max(0, len(tmdb) - 6)) + (tmdb[-2:] if len(tmdb) >= 2 else "")
        auslesen_logger.info(f"TMDb: API-Key erkannt ({mask})")
    else:
        auslesen_logger.info("TMDb: kein API-Key geladen")

    return auslesen_logger, remux_logger, auslesen_log_path, remux_log_path
