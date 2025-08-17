# -*- coding: utf-8 -*-
"""
Einzel-Log mit Abschnitts-Markern + Rotation.

- Eine Logdatei pro Run
- Abschnitts-Helfer: SCAN / REMUX / RENAME
- Anomalie-Logger: strukturfremde Funde etc.
"""

from __future__ import annotations

import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Tuple

from src.core.loader import AppConfig  # nutzt dein bestehendes Modell


SECTION_LINE = "=" * 78
SUB_LINE = "-" * 60


def _now_stamp() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d-%H-%M")


def setup_run_logger(cfg: AppConfig) -> Tuple[logging.Logger, Path]:
    """Erzeugt einen einzelnen Logger + Logdatei (mit Rotation nach Tagen)."""
    logs_dir = cfg.paths.logs_dir
    logs_dir.mkdir(parents=True, exist_ok=True)

    log_path = logs_dir / f"{_now_stamp()}_run.txt"

    logger = logging.getLogger("makemkv_run")
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", "%Y-%m-%d %H:%M:%S")

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(sh)

    # Rotate (lösche alte txt-Logs nach retention_days)
    keep_days = int(getattr(cfg.behavior, "log_retention_days", 14))
    for f in logs_dir.glob("*.txt"):
        try:
            age = datetime.now().astimezone() - datetime.fromtimestamp(f.stat().st_mtime).astimezone()
            if age > timedelta(days=keep_days):
                f.unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"Log-Cleanup Problem bei {f}: {e}")

    # Kopf
    logger.info(SECTION_LINE)
    logger.info("Start MakeMKV Auto-Run")
    logger.info(f"Logs: {log_path}")
    logger.info(f"Paths: base_root={cfg.paths.base_root} | transcode={cfg.paths.transcode_dir} | remux={cfg.paths.remux_dir}")
    logger.info(f"Behavior: dry_run={cfg.behavior.dry_run} | delete_originals={cfg.behavior.delete_originals}")
    logger.info(SECTION_LINE)

    return logger, log_path


def log_section(logger: logging.Logger, title: str) -> None:
    """Große Abschnittsüberschrift in den Log schreiben."""
    logger.info(SECTION_LINE)
    logger.info(title)
    logger.info(SECTION_LINE)


def log_subsection(logger: logging.Logger, title: str) -> None:
    """Kleine Abschnittsüberschrift (Unterkapitel)."""
    logger.info(SUB_LINE)
    logger.info(title)
    logger.info(SUB_LINE)


def log_anomaly(logger: logging.Logger, path: Path, reason: str) -> None:
    """Markiert Funde außerhalb der erwarteten Struktur (für spätere Heuristik-Anpassung)."""
    logger.warning(f"[ANOMALIE] {reason}: {path}")
