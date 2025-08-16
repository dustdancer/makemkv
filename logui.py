# -*- coding: utf-8 -*-
from __future__ import annotations
import sys, logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Tuple
from config import CONFIG
from utils import ensure_dir, now_stamp, mask_key

class ConsoleUI:
    """
    Einfache Terminal-UI mit Spinner & Progressbar.
    Die Progressbar kann zusätzliche Labels anzeigen (z. B. Tracks/Discs).
    """
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._last_len = 0
        self._spinner = ['|', '/', '-', '\\']
        self._si = 0

    def write(self, text: str):
        if not self.enabled: return
        try:
            sys.stdout.write('\r' + text + ' ' * max(0, self._last_len - len(text)))
            sys.stdout.flush()
            self._last_len = len(text)
        except Exception:
            pass

    def bar(self, prefix: str, current: int, total: int, suffix: str = "", width: int = 28):
        if not self.enabled: return
        total = max(1, total)
        pct = max(0.0, min(1.0, current / total))
        filled = int(width * pct)
        bar = '[' + '#' * filled + '-' * (width - filled) + f'] {current}/{total} {pct*100:5.1f}%'
        label = f"{prefix} {bar}"
        if suffix:
            label += f" | {suffix}"
        self.write(label)

    def spin(self, prefix: str, suffix: str = ""):
        if not self.enabled: return
        ch = self._spinner[self._si % len(self._spinner)]
        self._si += 1
        label = f"{prefix} {ch}"
        if suffix:
            label += f" | {suffix}"
        self.write(label)

    def done(self):
        if not self.enabled: return
        try:
            sys.stdout.write('\n'); sys.stdout.flush()
        except Exception:
            pass
        self._last_len = 0


def setup_loggers(logs_dir: Path) -> Tuple[logging.Logger, logging.Logger, Path, Path]:
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

    # Logrotation alt > n Tage
    keep = CONFIG["BEHAVIOR"]["LOG_RETENTION_DAYS"]
    for f in logs_dir.glob("*.txt"):
        try:
            age = datetime.now().astimezone() - datetime.fromtimestamp(f.stat().st_mtime).astimezone()
            if age > timedelta(days=keep):
                f.unlink(missing_ok=True)
        except Exception as e:
            remux_logger.warning(f"Log-Cleanup Problem bei {f}: {e}")

    # Secrets / ENV sichtbar (maskiert)
    user = CONFIG["NETWORK"]["USERNAME"]
    tmdb = CONFIG["TMDB"]["API_KEY"]
    auslesen_logger.info(f"SMB-User: {user}")
    if tmdb:
        auslesen_logger.info(f"TMDb: API-Key erkannt ({mask_key(tmdb)})")
    else:
        auslesen_logger.info("TMDb: kein API-Key geladen")

    return auslesen_logger, remux_logger, auslesen_log_path, remux_log_path
