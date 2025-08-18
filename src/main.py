#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
import sys

from core.loader import (
    load_config,
    setup_phase_logger,
    write_pipeline_index,
    now_stamp,
)
from core.scanner import find_sources


def main():
    # Repo-Root: …/src/main.py -> eine Ebene hoch
    repo_root = Path(__file__).resolve().parents[1]
    cfg_path = repo_root / "config" / "config.yaml"

    cfg = load_config(cfg_path)

    # Log-Zeitstempel für alle Dateien dieser Runde vereinheitlichen
    ts = now_stamp()
    auslesen_log, auslesen_log_path = setup_phase_logger("AUSLESEN", cfg["paths"]["logs_dir"], ts)

    auslesen_log.info("=== START: Testlauf Logger + Scanner ===")
    auslesen_log.info(f"Base Root     : {cfg['paths']['base_root']}")
    auslesen_log.info(f"Transcode Dir : {cfg['paths']['transcode_dir']}")
    auslesen_log.info(f"Remux Dir     : {cfg['paths']['remux_dir']}")
    auslesen_log.info(f"Logs Dir      : {cfg['paths']['logs_dir']}")
    auslesen_log.info(f"Dry-Run       : {cfg['app']['dry_run']}")
    auslesen_log.info(f"TMDb enabled  : {cfg['tmdb']['enabled']}")

    transcode_root = cfg["paths"]["transcode_dir"]
    if not transcode_root.exists():
        auslesen_log.error(f"Transcode-Verzeichnis existiert nicht: {transcode_root}")
        auslesen_log.info("=== ENDE: Keine Quellen ===")
        # Pipeline-Index trotzdem schreiben
        pipeline = write_pipeline_index(cfg["paths"]["logs_dir"], ts, [("AUSLESEN", auslesen_log_path)])
        auslesen_log.info(f"(Gesamte Pipeline-Logs in: {pipeline})")
        sys.exit(3)

    # Scannen
    sources = find_sources(transcode_root, auslesen_log)
    auslesen_log.info(f"Gefundene Quellen: {len(sources)}")

    # Ausgabe der ersten Liste in menschenlesbarer Form (wie zuvor)
    for i, s in enumerate(sources, 1):
        cat = s.get("category") or "-"
        kind = s.get("kind")
        disc_type = s.get("disc_type") or "-"
        path = s.get("path")
        disp = s.get("display")
        season = s.get("season")
        disc = s.get("disc")
        note = s.get("note")
        msg = (
            f"[{i:03d}] cat={cat} | kind={kind} | disc_type={disc_type} | "
            f"season={season} | disc={disc} | display='{disp}' | path={path}"
        )
        if note:
            msg += f" | note={note}"
        auslesen_log.info(msg)

    auslesen_log.info("=== ENDE: Testlauf Logger + Scanner ===")

    pipeline = write_pipeline_index(cfg["paths"]["logs_dir"], ts, [("AUSLESEN", auslesen_log_path)])
    auslesen_log.info(f"(Gesamte Pipeline-Logs in: {pipeline})")


if __name__ == "__main__":
    main()
