# -*- coding: utf-8 -*-
from __future__ import annotations
import sys, logging, shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from config import CONFIG
from utils import ensure_dir, is_windows
from logui import ConsoleUI, setup_loggers
from mountshare import get_share_root
from scan import find_sources
from makemkv import find_makemkvcon, run_makemkv
from naming import destination_for_movie, destination_for_tv, parse_name_year
from rename_movie import rename_and_move_movie
from rename_tv import rename_and_move_tv
from tmdb_client import tmdb_get_season_episode_count
from hooks import run_mkv_match, normalize_mkv_match_naming

def _delete_path(p: Path, log: logging.Logger):
    if CONFIG["BEHAVIOR"]["DRY_RUN"]:
        log.info(f"[DRY-RUN] Löschen: {p}")
        return
    if p.is_file() or p.is_symlink():
        p.unlink(missing_ok=True); log.info(f"Datei gelöscht: {p}")
    elif p.is_dir():
        shutil.rmtree(p, ignore_errors=True); log.info(f"Ordner gelöscht: {p}")

def _series_key(s: str) -> str:
    """Bereinigt typische Disc/Season Marker aus dem Anzeigenamen für Gruppierung."""
    import re
    s2 = re.sub(r"\b[Dd]isc\s*\d{1,2}\b", "", s)
    s2 = re.sub(r"\b[Dd](\d{1,2})\b", "", s2)
    s2 = re.sub(r"\b[Ss](?:eason)?\s*\d{1,2}\b", "", s2)
    s2 = re.sub(r"\bS\d{1,2}D\d{1,2}\b", "", s2)
    from utils import sanitize_filename
    return sanitize_filename(s2).strip()

def main():
    # Basis-Root bestimmen (Mount/Map falls aktiviert)
    dummy = logging.getLogger("dummy"); dummy.addHandler(logging.NullHandler())
    base_root = get_share_root(dummy) if CONFIG["NETWORK"]["ENABLE_MOUNT"] else None
    if not base_root:
        base_root = Path(CONFIG["NETWORK"]["WIN_DRIVE_LETTER"] + "\\") if is_windows() else Path(CONFIG["NETWORK"]["LINUX_MOUNT_POINT"])
        if not base_root.exists() and is_windows():
            base_root = Path(CONFIG["NETWORK"]["UNC_ROOT"])
    if not base_root or not base_root.exists():
        print(f"[FATAL] Basis-Root nicht gefunden: {base_root}")
        sys.exit(2)

    P = CONFIG["PATHS"]
    transcode_root = base_root / Path(P["TRANSCODE_REL"])
    remux_root     = base_root / Path(P["REMUX_REL"])
    logs_dir       = base_root / Path(P["LOGS_REL"])
    ensure_dir(remux_root); ensure_dir(logs_dir)

    auslesen_log, remux_log, _, _ = setup_loggers(logs_dir)
    ui = ConsoleUI(True)

    auslesen_log.info(f"Base: {base_root}")
    auslesen_log.info(f"Transcode: {transcode_root}")
    auslesen_log.info(f"Remux: {remux_root}")
    auslesen_log.info(f"Logs: {logs_dir}")

    if not transcode_root.exists():
        auslesen_log.error(f"Transcode-Verzeichnis existiert nicht: {transcode_root}")
        sys.exit(3)

    sources = find_sources(transcode_root, auslesen_log)
    if not sources:
        auslesen_log.info("Keine Quellen gefunden. Ende.")
        return

    makemkv = find_makemkvcon(remux_log)
    if not makemkv:
        remux_log.error("MakeMKV CLI nicht gefunden – Abbruch.")
        sys.exit(4)

    # Trennung Filme/TV
    movies = [s for s in sources if s.get("category") != "tv"]
    tvs    = [s for s in sources if s.get("category") == "tv"]

    # --- MOVIES ---
    for src in movies:
        disp = src["display"]; src_path = src["path"]; item_root = src["item_root"]
        remux_log.info("=" * 80)
        remux_log.info(f"[MOVIE] Quelle: {src_path} | {src['kind']} | Bezeichner: {disp}")

        tmp_out = remux_root / "_tmp" / disp
        ensure_dir(tmp_out)

        ok_run = run_makemkv(
            makemkv,
            "iso" if src["kind"] == "iso" else "file",
            src_path,
            tmp_out,
            remux_log,
            ui,
        )
        if not ok_run:
            remux_log.error(f"Remux FEHLGESCHLAGEN (Movie): {src_path}")
            _delete_path(tmp_out, remux_log)
            continue

        dest_base = destination_for_movie(remux_root, disp)
        ok = rename_and_move_movie(tmp_out, dest_base, disp, remux_log)
        if not ok:
            remux_log.warning(f"Movie-Ausgabe nicht verschoben: {disp}")
            continue

        if CONFIG["BEHAVIOR"]["DELETE_ORIGINALS"]:
            remux_log.info(f"Original löschen: {item_root}")
            _delete_path(item_root if item_root.is_dir() else src_path, remux_log)

    # --- TV gruppieren (Serie, Season) ---
    tv_groups: Dict[Tuple[str, Optional[int]], List[Dict]] = {}
    for s in tvs:
        key = (_series_key(s["display"]), s.get("season"))
        tv_groups.setdefault(key, []).append(s)

    for (series_base, season_no), discs in tv_groups.items():
        remux_log.info("=" * 80)
        remux_log.info(f"[TV] Serie='{series_base}' | Season={season_no} | Discs={len(discs)}")

        series_name, year_hint, _ = parse_name_year(series_base if series_base else "")
        expected_total_eps = tmdb_get_season_episode_count(series_name, year_hint, season_no)
        if expected_total_eps:
            remux_log.info(f"TMDb: erwartete Episoden (S{season_no}): {expected_total_eps}")
        else:
            remux_log.info("TMDb: keine Episodenanzahl verfügbar (API-Key nicht gesetzt oder kein Treffer).")

        discs_sorted = sorted(discs, key=lambda d: (d.get("disc") or 9999, str(d["path"])))
        next_ep = 1
        disc_total = len(discs_sorted)

        for idx, d in enumerate(discs_sorted, start=1):
            disp      = d["display"]
            src_path  = d["path"]
            item_root = d["item_root"]
            disc_no   = d.get("disc")
            is_last_disc = (idx == disc_total)

            remux_log.info("-" * 60)
            remux_log.info(f"Disc: {disc_no if disc_no else '?'} | Quelle: {src_path} | Bezeichner: {disp} | Letzte Disc: {is_last_disc}")

            tmp_out = remux_root / "_tmp" / f"{(series_name or disp)}_S{(season_no or 0):02d}_D{(disc_no or 0):02d}"
            ensure_dir(tmp_out)

            ok_run = run_makemkv(
                makemkv,
                "iso" if d["kind"] == "iso" else "file",
                src_path,
                tmp_out,
                remux_log,
                ui,
                disc_index=idx,
                disc_total=disc_total,
            )
            if not ok_run:
                remux_log.error(f"Remux FEHLGESCHLAGEN (TV): {src_path}")
                _delete_path(tmp_out, remux_log)
                continue

            dest_base = destination_for_tv(remux_root, series_name or disp, season_no)
            ok, next_ep = rename_and_move_tv(
                tmp_out, dest_base,
                series_name or disp,
                season_no, next_ep,
                expected_total_eps,
                is_last_disc,
                remux_log,
            )
            if not ok:
                remux_log.warning(f"TV-Ausgabe nicht verschoben: {disp}")
                continue

            # Optionaler Hook (Season-Ordner)
            if CONFIG.get("HOOKS", {}).get("MKV_MATCH", {}).get("ENABLED", False):
                season_dir = destination_for_tv(remux_root, series_name or series_base, season_no)
                try:
                    ran = run_mkv_match(season_dir, season_no, series_name or series_base, remux_log, ui)
                    if ran and CONFIG["HOOKS"]["MKV_MATCH"].get("RENAME_TO_SCHEMA", True):
                        normalize_mkv_match_naming(season_dir, series_name or series_base, season_no, remux_log)
                except Exception as e:
                    remux_log.warning(f"mkv-match Hook übersprungen/fehlerhaft: {e}")

            if CONFIG["BEHAVIOR"]["DELETE_ORIGINALS"]:
                remux_log.info(f"Original löschen: {item_root}")
                _delete_path(item_root if item_root.is_dir() else src_path, remux_log)

    remux_log.info("=" * 80)
    remux_log.info("Fertig – alle Quellen abgearbeitet.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAbgebrochen (Ctrl+C).")
