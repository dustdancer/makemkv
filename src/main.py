#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import logging, sys
from datetime import datetime, timedelta
from pathlib import Path

from loader import load_config
from scanner import find_sources

# --------- Logging: eine gemeinsame Datei mit Kanal-Spalte ---------

class _StageFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Falls kein 'stage' gesetzt ist (z.B. aus stdlib), Standard setzen
        if not hasattr(record, "stage"):
            record.stage = "GEN"
        return True

def _mk_pipeline_logger(logs_dir: Path, level: int) -> tuple[logging.LoggerAdapter, logging.LoggerAdapter, logging.LoggerAdapter, Path]:
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    combined_path = logs_dir / f"{ts}_pipeline.txt"

    base = logging.getLogger("pipeline")
    base.handlers.clear()
    base.setLevel(level)

    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(stage)-7s | %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(combined_path, encoding="utf-8")
    fh.setLevel(level); fh.setFormatter(fmt); fh.addFilter(_StageFilter())

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(level); sh.setFormatter(fmt); sh.addFilter(_StageFilter())

    base.addHandler(fh)
    base.addHandler(sh)

    # Drei kanalierte LoggerAdapters
    auslesen = logging.LoggerAdapter(base, {"stage": "AUSLESEN"})
    remux    = logging.LoggerAdapter(base, {"stage": "REMUX"})
    rename   = logging.LoggerAdapter(base, {"stage": "RENAME"})
    return auslesen, remux, rename, combined_path

def _map_level(name: str) -> int:
    return {
        "CRITICAL": logging.CRITICAL,
        "ERROR": logging.ERROR,
        "WARNING": logging.WARNING,
        "INFO": logging.INFO,
        "DEBUG": logging.DEBUG,
        "NOTSET": logging.NOTSET,
    }.get(name.upper(), logging.INFO)

# --------- Main ---------

def main():
    cfg = load_config("config/config.yaml")

    # logger
    level = _map_level(cfg.app.log_level)
    auslesen_log, remux_log, rename_log, combined_path = _mk_pipeline_logger(cfg.paths.logs_dir, level)

    # Header
    auslesen_log.info("=== START: Testlauf Logger + Scanner ===")
    auslesen_log.info(f"Base Root     : {cfg.paths.base_root}")
    auslesen_log.info(f"Transcode Dir : {cfg.paths.transcode_dir}")
    auslesen_log.info(f"Remux Dir     : {cfg.paths.remux_dir}")
    auslesen_log.info(f"Logs Dir      : {cfg.paths.logs_dir}")
    auslesen_log.info(f"Dry-Run       : {cfg.app.dry_run}")
    auslesen_log.info(f"TMDb enabled  : {cfg.tmdb.enabled}")

    # prüfen, ob transcode existiert
    if not cfg.paths.transcode_dir.exists():
        auslesen_log.error(f"Transcode-Verzeichnis existiert nicht: {cfg.paths.transcode_dir}")
        auslesen_log.info("=== ENDE: Keine Quellen ===")
        return 3

    # Scannen
    sources = find_sources(cfg.paths.transcode_dir, auslesen_log)
    auslesen_log.info(f"Gefundene Quellen: {len(sources)}")

    # hübsche Auflistung
    for i, s in enumerate(sources, 1):
        cat = s.get("category") or "-"
        kind = s.get("kind")
        path = s.get("path")
        disp = s.get("display")
        season = s.get("season")
        disc = s.get("disc")
        disc_type = s.get("disc_type")
        note = s.get("note")
        line = (
            f"[{i:03d}] cat={cat} | kind={kind} | disc_type={disc_type} | "
            f"season={season} | disc={disc} | display='{disp}' | path={path}"
        )
        if note:
            line += f" | note={note}"
        auslesen_log.info(line)

    auslesen_log.info("=== ENDE: Testlauf Logger + Scanner ===")
    auslesen_log.info(f"(Gemeinsame Logdatei: {combined_path})")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAbgebrochen (Ctrl+C).", file=sys.stderr)
