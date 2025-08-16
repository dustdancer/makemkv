#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# --- flache Importe (kein Paket nötig) ---
from config import CONFIG
from logui import ConsoleUI, setup_loggers
from mountshare import get_share_root
from scan import find_sources
from makemkv import find_makemkvcon, run_makemkv
from naming import destination_for_movie, destination_for_tv, parse_name_year
from rename_movie import rename_and_move_movie
from rename_tv import rename_and_move_tv
from hooks import run_mkv_match, normalize_mkv_match_naming
from tmdb_client import tmdb_is_enabled, tmdb_get_season_episode_count

# -------------------------
# kleine Utilities lokal
# -------------------------
def is_windows() -> bool:
    return sys.platform.startswith("win")

def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def delete_path(p: Path, log: logging.Logger) -> None:
    if CONFIG["BEHAVIOR"].get("DRY_RUN", False):
        log.info(f"[DRY-RUN] Löschen: {p}")
        return
    if p.is_file() or p.is_symlink():
        p.unlink(missing_ok=True)
        log.info(f"Datei gelöscht: {p}")
    elif p.is_dir():
        import shutil
        shutil.rmtree(p, ignore_errors=True)
        log.info(f"Ordner gelöscht: {p}")

# -------------------------
# Hilfen für Serien-Status
# -------------------------
class SeasonState:
    """Merkt sich den nächsten Episoden-Index je (Serie, Season)."""
    def __init__(self) -> None:
        self._state: Dict[Tuple[str, int], int] = {}

    def get_next(self, series_key: str, season_no: int, default_start: int = 1) -> int:
        return self._state.get((series_key, season_no), default_start)

    def update(self, series_key: str, season_no: int, next_ep: int) -> None:
        self._state[(series_key, season_no)] = next_ep

# -------------------------
# Ausgabe: Quellen-Übersicht
# -------------------------
def log_sources_summary(sources: List[Dict], log: logging.Logger) -> None:
    movies = [s for s in sources if s.get("category") != "tv"]
    tvs    = [s for s in sources if s.get("category") == "tv"]

    if movies:
        log.info("Erkannte FILME:")
        for i, s in enumerate(movies, 1):
            disp = s["display"]
            kind = s["kind"]
            src  = s["path"]
            log.info(f"  ({i}) [{kind}] {disp}  —  {src}")

    if tvs:
        log.info("Erkannte SERIEN/STAFFELN:")
        for i, s in enumerate(tvs, 1):
            disp = s["display"]
            sea  = s.get("season")
            disc = s.get("disc")
            kind = s["kind"]
            src  = s["path"]
            add  = []
            if sea is not None: add.append(f"S{sea:02d}")
            if disc is not None: add.append(f"D{disc:02d}")
            suffix = (" [" + " ".join(add) + "]") if add else ""
            log.info(f"  ({i}) [{kind}] {disp}{suffix}  —  {src}")

# -------------------------
# MAIN
# -------------------------
def main() -> None:
    # 1) Basis-Root bestimmen (Share mappen/mounten)
    dummy = logging.getLogger("dummy"); dummy.addHandler(logging.NullHandler())
    base_root = get_share_root(dummy) if CONFIG["NETWORK"].get("ENABLE_MOUNT", False) else None

    if not base_root:
        # Fallbacks: Laufwerksbuchstabe oder UNC/Mountpoint
        if is_windows():
            base_root = Path(CONFIG["NETWORK"]["WIN_DRIVE_LETTER"]).resolve()
            if not base_root.exists():
                base_root = Path(CONFIG["NETWORK"]["UNC_ROOT"])
        else:
            base_root = Path(CONFIG["NETWORK"]["LINUX_MOUNT_POINT"])

    if not base_root or not base_root.exists():
        print(f"[FATAL] Basis-Root nicht gefunden: {base_root}")
        sys.exit(2)

    # 2) Pfade auflösen und Logger einrichten
    paths = CONFIG["PATHS"]
    transcode_root = base_root / Path(paths["TRANSCODE_REL"])
    remux_root     = base_root / Path(paths["REMUX_REL"])
    logs_dir       = base_root / Path(paths["LOGS_REL"])
    ensure_dir(remux_root); ensure_dir(logs_dir)

    auslesen_log, remux_log, auslesen_logfile, remux_logfile = setup_loggers(logs_dir)
    ui = ConsoleUI(True)

    auslesen_log.info(f"Base: {base_root}")
    auslesen_log.info(f"Transcode: {transcode_root}")
    auslesen_log.info(f"Remux: {remux_root}")
    auslesen_log.info(f"Logs: {logs_dir}")

    if not transcode_root.exists():
        auslesen_log.error(f"Transcode-Verzeichnis existiert nicht: {transcode_root}")
        sys.exit(3)

    # 3) Quellen finden und zusammenfassen
    sources = find_sources(transcode_root, auslesen_log)
    if not sources:
        auslesen_log.info("Keine Quellen gefunden. Ende.")
        return

    # Übersichtsliste (gewünscht)
    log_sources_summary(sources, auslesen_log)

    # 4) MakeMKV auffinden
    makemkv_bin = find_makemkvcon(remux_log)
    if not makemkv_bin:
        remux_log.error("MakeMKV CLI nicht gefunden – Abbruch.")
        sys.exit(4)

    # in stabiler Reihenfolge abarbeiten: zuerst Filme, dann TV
    movies = [s for s in sources if s.get("category") != "tv"]
    tvs    = [s for s in sources if s.get("category") == "tv"]

    # 5) Filme verarbeiten
    for idx, src in enumerate(movies, 1):
        disp: str = src["display"]
        src_path: Path = src["path"]
        kind: str = src["kind"]
        item_root: Path = src["item_root"]

        remux_log.info("=" * 80)
        remux_log.info(f"[MOVIE] Quelle: {src_path} | {kind} | Bezeichner: {disp}")

        # tmp-Ausgabeordner
        tmp_dir = remux_root / "_tmp" / f"{disp}_MOVIE"
        ensure_dir(tmp_dir)

        # Disc-Zähler in UI
        ui.write(f"📀 Film {idx}/{len(movies)} starten: {disp}")
        ok = run_makemkv(makemkv_bin, "iso" if kind == "iso" else "file", src_path, tmp_dir, remux_log, ui)
        ui.done()
        if not ok:
            remux_log.error(f"Remux fehlgeschlagen: {disp}")
            continue

        dest_dir = destination_for_movie(remux_root, disp)
        ensure_dir(dest_dir)

        if not rename_and_move_movie(tmp_dir, dest_dir, disp, remux_log):
            remux_log.warning(f"Rename/Move (Film) hatte keine Dateien für: {disp}")

        # optional: Quelle aufräumen
        if CONFIG["BEHAVIOR"].get("DELETE_ORIGINALS", False):
            remux_log.info(f"Original löschen: {item_root}")
            delete_path(item_root, remux_log)

    # 6) TV verarbeiten (Season-State & TMDb-Info)
    season_state = SeasonState()

    for idx, src in enumerate(tvs, 1):
        disp: str = src["display"]
        src_path: Path = src["path"]
        kind: str = src["kind"]
        item_root: Path = src["item_root"]
        season_no: Optional[int] = src.get("season")
        disc_no: Optional[int] = src.get("disc")

        # Fallback für Season, damit kein ungültiger Pfad entsteht
        season_for_path = season_no if season_no is not None else 0

        # Serienname/Year für TMDb-Hints
        series_name, year_hint, _ = parse_name_year(disp)

        # erwartete Episoden (optional)
        expected_total: Optional[int] = None
        if tmdb_is_enabled():
            expected_total = tmdb_get_season_episode_count(series_name, year_hint, season_no, remux_log)
            if expected_total is not None:
                remux_log.info(f"TMDb: Season-Episoden erwartet: {expected_total}")
            else:
                remux_log.info("TMDb: keine Episodenanzahl verfügbar (API-Key nicht gesetzt oder kein Treffer).")
        else:
            remux_log.info("TMDb: keine Episodenanzahl verfügbar (API-Key nicht gesetzt oder kein Treffer).")

        # Disc-Status im Log
        remux_log.info("=" * 80)
        remux_log.info(f"[TV] Serie='{disp}' | Season={season_no} | Disc={disc_no}")
        remux_log.info("-" * 60)
        remux_log.info(f"Disc: {disc_no if disc_no is not None else '?'} | Quelle: {src_path} | Bezeichner: {disp} | Letzte Disc: {idx == len(tvs)}")

        tmp_dir = remux_root / "_tmp" / f"{disp}_S{season_for_path:02d}_D{(disc_no or 0):02d}"
        ensure_dir(tmp_dir)

        # Disc-Zähler in UI (Anforderung: „wie viele Discs folgen“)
        ui.write(f"📀 TV Disc {idx}/{len(tvs)}: {disp} (S{season_for_path:02d}{f' D{disc_no:02d}' if disc_no else ''})")
        ok = run_makemkv(makemkv_bin, "iso" if kind == "iso" else "file", src_path, tmp_dir, remux_log, ui)
        ui.done()
        if not ok:
            remux_log.error(f"Remux fehlgeschlagen: {disp}")
            continue

        dest_dir = destination_for_tv(remux_root, disp, season_for_path)
        ensure_dir(dest_dir)

        # Start-Episode je Serie+Season holen/setzen
        series_key = series_name.lower().strip()
        start_ep = season_state.get_next(series_key, season_for_path, default_start=1)

        # ist es die letzte Disc für diese Verarbeitung?
        is_last_disc = (idx == len(tvs))

        # umbenennen/verschieben
        ok, next_ep = rename_and_move_tv(
            tmp_out=tmp_dir,
            dest_base=dest_dir,
            base_display=disp,
            season_no=season_no,              # echtes Season-Meta (kann None sein → wird im Namen berücksichtigt)
            start_episode_no=start_ep,
            expected_total_eps=expected_total,
            is_last_disc=is_last_disc,
            log=remux_log,
        )
        # Season-Zähler aktualisieren
        if ok:
            season_state.update(series_key, season_for_path, next_ep)

        # optionaler Hook
        if ok and CONFIG.get("HOOKS", {}).get("MKV_MATCH", {}).get("ENABLED", False):
            # Hook ausführen
            run_mkv_match(dest_dir, season_no, series_name, remux_log, ui)
            # und anschließend (wenn gewünscht) ins Schema normalisieren
            if CONFIG["HOOKS"]["MKV_MATCH"].get("RENAME_TO_SCHEMA", True):
                normalize_mkv_match_naming(dest_dir, disp, season_no, remux_log)

        # optional: Quelle aufräumen
        if CONFIG["BEHAVIOR"].get("DELETE_ORIGINALS", False):
            remux_log.info(f"Original löschen: {item_root}")
            delete_path(item_root, remux_log)

    remux_log.info("Fertig. ✅")

# -------------------------
if __name__ == "__main__":
    main()
