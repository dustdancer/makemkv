# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Tuple


def _now_stamp() -> str:
    # yyyy-mm-dd-hh-mm
    return datetime.now().astimezone().strftime("%Y-%m-%d-%H-%M")


def _make_logger(name: str, logfile: Path, console_level: int) -> logging.Logger:
    """
    Erstellt einen Logger mit FileHandler (DEBUG) und StreamHandler (console_level).
    Vorherige Handler werden entfernt, damit bei Re-Runs keine doppelten Logs entstehen.
    """
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File
    fh = logging.FileHandler(logfile, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # Console
    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(console_level)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    return logger


def _cleanup_old_logs(logs_dir: Path, keep_days: int, logger: logging.Logger) -> None:
    """
    Löscht .txt-Logs, deren mtime älter als keep_days ist.
    Fehler beim Löschen werden nur geloggt (nicht geworfen).
    """
    cutoff = timedelta(days=max(0, int(keep_days)))
    now = datetime.now().astimezone()

    for f in logs_dir.glob("*.txt"):
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime).astimezone()
            if now - mtime > cutoff:
                f.unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"Log-Cleanup Problem bei {f}: {e}")


def setup_loggers(
    logs_dir: Path,
    keep_days: int = 14,
    console_level: int = logging.INFO,
) -> Tuple[logging.Logger, logging.Logger, Path, Path]:
    """
    Legt zwei Log-Dateien mit Zeitstempel an und gibt passende Logger zurück.

    Rückgabe:
      (auslesen_logger, remux_logger, auslesen_log_path, remux_log_path)
    """
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = _now_stamp()

    auslesen_log_path = logs_dir / f"{ts}_auslesen.txt"
    remux_log_path = logs_dir / f"{ts}_remux.txt"

    auslesen_logger = _make_logger("auslesen", auslesen_log_path, console_level)
    remux_logger = _make_logger("remux", remux_log_path, console_level)

    # Ältere Logs aufräumen (Meldungen ins Remux-Logger, damit man es sieht)
    _cleanup_old_logs(logs_dir, keep_days, remux_logger)

    return auslesen_logger, remux_logger, auslesen_log_path, remux_log_path


__all__ = ["setup_loggers"]
