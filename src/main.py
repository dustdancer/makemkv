#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Main-Teststarter für Logger + Scanner.

- Lädt config/config.yaml (über core.loader.load_config)
- Richtet Logging ein (utils.logger.setup_loggers)
- Führt einen Scan auf transcode_dir aus (core.scanner.find_sources)
- Protokolliert gefundene Quellen sauber in den Logs

Start:
  python -m src.main
oder (zur Not):
  python src/main.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Tuple
import logging

# ---- robuste Importe (direkt vs. -m) ----------------------------------------
try:
    # Wenn du mit `python -m src.main` startest
    from core.loader import load_config
    from core.scanner import find_sources
    from utils.logger import setup_loggers
except ImportError:
    # Falls du `python src/main.py` direkt startest
    THIS_DIR = Path(__file__).resolve().parent
    if str(THIS_DIR) not in sys.path:
        sys.path.append(str(THIS_DIR))
    from core.loader import load_config
    from core.scanner import find_sources
    from utils.logger import setup_loggers
# -----------------------------------------------------------------------------

def _unpack_loggers(ret: Any) -> Tuple[logging.Logger, logging.Logger]:
    """
    Unterstützt beide Varianten:
      - ein gemeinsamer Logger
      - zwei Logger (auslesen, remux) + evtl. Pfad-Rückgaben
    """
    if isinstance(ret, logging.Logger):
        return ret, ret
    if isinstance(ret, tuple):
        # häufig: (auslesen_logger, remux_logger, auslesen_log_path, remux_log_path)
        if len(ret) >= 2 and isinstance(ret[0], logging.Logger) and isinstance(ret[1], logging.Logger):
            return ret[0], ret[1]
        # fallback: erster Logger für alles verwenden
        for x in ret:
            if isinstance(x, logging.Logger):
                return x, x
    # letzter Fallback: Root-Logger
    return logging.getLogger("root"), logging.getLogger("root")


def main() -> int:
    # 1) Konfiguration laden (legt Logs/Remux-Verzeichnisse NICHT automatisch an)
    cfg = load_config(create_missing_dirs=True, check_path_existence=False)

    # 2) Logger einrichten
    ret = setup_loggers(cfg.paths.logs_dir)
    auslesen_log, remux_log = _unpack_loggers(ret)

    # Laufzeitkontext protokollieren
    auslesen_log.info("=== START: Testlauf Logger + Scanner ===")
    auslesen_log.info(f"Base Root     : {cfg.paths.base_root}")
    auslesen_log.info(f"Transcode Dir : {cfg.paths.transcode_dir}")
    auslesen_log.info(f"Remux Dir     : {cfg.paths.remux_dir}")
    auslesen_log.info(f"Logs Dir      : {cfg.paths.logs_dir}")
    auslesen_log.info(f"Dry-Run       : {cfg.behavior.dry_run}")
    auslesen_log.info(f"TMDb enabled  : {cfg.tmdb.enabled}")

    # 3) Scanner starten
    if not cfg.paths.transcode_dir.exists():
        auslesen_log.error(f"Transcode-Verzeichnis existiert nicht: {cfg.paths.transcode_dir}")
        auslesen_log.info("=== ENDE: Keine Quellen ===")
        return 3

    sources = find_sources(cfg.paths.transcode_dir, auslesen_log)

    auslesen_log.info(f"Gefundene Quellen: {len(sources)}")
    for i, s in enumerate(sources, 1):
        cat = s.get("category") or "-"
        kind = s.get("kind")
        path = s.get("path")
        disp = s.get("display")
        season = s.get("season")
        disc = s.get("disc")
        auslesen_log.info(
            f"[{i:03d}] cat={cat} | {kind} | season={season} | disc={disc} | "
            f"display='{disp}' | path={path}"
        )

    auslesen_log.info("=== ENDE: Testlauf Logger + Scanner ===")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nAbgebrochen (Ctrl+C).")
