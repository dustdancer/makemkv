# -*- coding: utf-8 -*-
"""
Zentraler Logger für einen Run.
- Ein Logfile pro Run (Timestamp im Namen)
- Konsolen-Ausgabe (INFO), Datei (DEBUG)
- Einfache "Abschnitt"-Header (SCAN / REMUX / RENAME / REPORT)
- Logrotation nach retention_days

Diese Datei ist NEU (v0.0.3).
"""

from __future__ import annotations

import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Tuple


LOG_FMT = "%(asctime)s | %(levelname)-8s | %(message)s"
LOG_DATE = "%Y-%m-%d %H:%M:%S"


def _timestamp() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d-%H-%M-%S")


def rotate_logs(log_dir: Path, retention_days: int) -> None:
    """Löscht alte .log/.txt Dateien älter als retention_days (best effort)."""
    if retention_days <= 0:
        return
    try:
        for p in log_dir.glob("*"):
            if p.suffix.lower() not in (".log", ".txt"):
                continue
            try:
                age = datetime.now().astimezone() - datetime.fromtimestamp(p.stat().st_mtime).astimezone()
                if age > timedelta(days=retention_days):
                    p.unlink(missing_ok=True)
            except Exception:
                # Keine harten Fehler beim Aufräumen
                pass
    except Exception:
        pass


def init_run_logger(logs_dir: Path, retention_days: int = 14) -> Tuple[logging.Logger, Path]:
    """
    Erstellt EIN Logger-Objekt + Logfile-Pfad.
    - Datei-Level: DEBUG
    - Console-Level: INFO
    - Rotiert alte Logs
    """
    logs_dir.mkdir(parents=True, exist_ok=True)
    rotate_logs(logs_dir, retention_days)

    log_path = logs_dir / f"{_timestamp()}_run.txt"

    logger = logging.getLogger("run")
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)

    # File
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(LOG_FMT, LOG_DATE))
    logger.addHandler(fh)

    # Console
    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(logging.Formatter(LOG_FMT, LOG_DATE))
    logger.addHandler(sh)

    # Kurzer Header
    logger.info("=" * 79)
    logger.info("RUN START")
    logger.info("=" * 79)

    return logger, log_path


def section(logger: logging.Logger, title: str) -> None:
    """
    Schreibt einen klaren Abschnitts-Header ins Log, z. B.:
      -------- SCAN: Quellverzeichnisse --------
    """
    sep = "-" * 10
    logger.info("")
    logger.info(f"{sep} {title} {sep}")


def footer(logger: logging.Logger) -> None:
    """Run-Ende-Block."""
    logger.info("=" * 79)
    logger.info("RUN ENDE")
    logger.info("=" * 79)
