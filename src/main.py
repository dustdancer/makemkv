#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re
import sys
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from mountshare import get_share_root, is_windows, ensure_dir, delete_path
from makemkv import find_makemkvcon, run_makemkv
from scan import find_sources
from naming import (
    sanitize_filename, parse_name_year,
    destination_for_movie, destination_for_tv,
)
from rename_movie import rename_and_move_movie
from rename_tv import rename_and_move_tv
from tmdb import tmdb_is_enabled, tmdb_get_season_episode_count
from hooks import run_mkv_match, normalize_mkv_match_naming


# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

CONFIG: Dict = {
    "NETWORK": {
        "ENABLE_MOUNT": True,
        "UNC_ROOT": r"\\blickfeldData\downloads",
        "WIN_DRIVE_LETTER": "K:",
        "LINUX_MOUNT_POINT": "/mnt/blickfeldData",
        "USERNAME": "user",   # wird unten durch secrets/env überschrieben
        "PASSWORD": "pass",
    },
    "PATHS": {
        "TRANSCODE_REL": r"data\usenet\complete\iso\transcode",
        "REMUX_REL":     r"data\usenet\complete\iso\remux",
        "LOGS_REL":      r"data\usenet\complete\iso\logs",
    },
    "BEHAVIOR": {
        "DRY_RUN": False,
        "DELETE_ORIGINALS": True,
        "LOG_RETENTION_DAYS": 14,
    },
    "HOOKS": {
        "MKV_MATCH": {
            "ENABLED": False,          # Optional, auf True setzen wenn installiert
            "RENAME_TO_SCHEMA": True,  # Danach in "Serie – SxxExx - Titel" umbenennen
        }
    },
    "TMDB": {
        "API_KEY": "",        # wird über secrets/env gesetzt
        "LANG": "de-DE",
        "TIMEOUT": 8,
    },
}


# ---------------------------------------------------------------------------
# Secrets laden (neben main.py) + ENV drüber
# ---------------------------------------------------------------------------

def _load_secrets_file() -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        sec = Path(__file__).resolve().parent / "secrets.txt"
        if not sec.exists():
            return out
        for raw in sec.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith(";") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            key = k.strip().lower()
            val = v.strip().strip('"').strip("'")
            if key in ("username",): key = "user"
            if key in ("password",): key = "pass"
            if key in ("tmdb", "tmdb_api_key"): key = "apikey"
            out[key] = val
    except Exception:
        pass
    return out


_SECRETS = _load_secrets_file()
if _SECRETS.get("user"):
    CONFIG["NETWORK"]["USERNAME"] = _SECRETS["user"]
if _SECRETS.get("pass"):
    CONFIG["NETWORK"]["PASSWORD"] = _SECRETS["pass"]
if _SECRETS.get("apikey"):
    CONFIG["TMDB"]["API_KEY"] = _SECRETS["apikey"]

if os.environ.get("BLICKFELD_SMB_USER"):
    CONFIG["NETWORK"]["USERNAME"] = os.environ["BLICKFELD_SMB_USER"]
if os.environ.get("BLICKFELD_SMB_PASS"):
    CONFIG["NETWORK"]["PASSWORD"] = os.environ["BLICKFELD_SMB_PASS"]
if os.environ.get("TMDB_API_KEY"):
    CONFIG["TMDB"]["API_KEY"] = os.environ["TMDB_API_KEY"]


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _now_stamp() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d-%H-%M")


def setup_loggers(logs_dir: Path) -> Tuple[logging.Logger, logging.Logger]:
    ensure_dir(logs_dir)
    ts = _now_stamp()
    auslesen_log_path = logs_dir / f"{ts}_auslesen.txt"
    remux_log_path    = logs_dir / f"{ts}_remux.txt"

    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", "%Y-%m-%d %H:%M:%S")

    auslesen = logging.getLogger("auslesen")
    auslesen.handlers.clear()
    auslesen.setLevel(logging.DEBUG)
    fh1 = logging.FileHandler(auslesen_log_path, encoding="utf-8")
    fh1.setFormatter(fmt); fh1.setLevel(logging.DEBUG)
    sh1 = logging.StreamHandler(sys.stdout)
    sh1.setFormatter(fmt); sh1.setLevel(logging.INFO)
    auslesen.addHandler(fh1); auslesen.addHandler(sh1)

    remux = logging.getLogger("remux")
    remux.handlers.clear()
    remux.setLevel(logging.DEBUG)
    fh2 = logging.FileHandler(remux_log_path, encoding="utf-8")
    fh2.setFormatter(fmt); fh2.setLevel(logging.DEBUG)
    sh2 = logging.StreamHandler(sys.stdout)
    sh2.setFormatter(fmt); sh2.setLevel(logging.INFO)
    remux.addHandler(fh2); remux.addHandler(sh2)

    # Logrotation
    keep_days = CONFIG["BEHAVIOR"]["LOG_RETENTION_DAYS"]
    for f in logs_dir.glob("*.txt"):
        try:
            age = datetime.now().astimezone() - datetime.fromtimestamp(f.stat().st_mtime).astimezone()
            if age > timedelta(days=keep_days):
                f.unlink(missing_ok=True)
        except Exception:
            pass

    # Sichtbare Startzeile
    auslesen.info(f"SMB-User: {CONFIG['NETWORK']['USERNAME']}")
    api = CONFIG["TMDB"]["API_KEY"]
    if api:
        auslesen.info(f"TMDb: API-Key erkannt ({api[:4]}…)")
    else:
        auslesen.info("TMDb: kein API-Key geladen")

    return auslesen, remux


# ---------------------------------------------------------------------------
# Haupt
# ---------------------------------------------------------------------------

def main() -> None:
    # Basis ermitteln (Netzlaufwerk mounten/mappen)
    dummy = logging.getLogger("dummy")
    dummy.addHandler(logging.NullHandler())

    base_root = get_share_root(
        dummy,
        enable_mount=CONFIG["NETWORK"]["ENABLE_MOUNT"],
        unc_root=CONFIG["NETWORK"]["UNC_ROOT"],
        win_drive_letter=CONFIG["NETWORK"]["WIN_DRIVE_LETTER"],
        linux_mount_point=CONFIG["NETWORK"]["LINUX_MOUNT_POINT"],
        username=CONFIG["NETWORK"]["USERNAME"],
        password=CONFIG["NETWORK"]["PASSWORD"],
        dry_run=CONFIG["BEHAVIOR"]["DRY_RUN"],
    )
    if not base_root or not base_root.exists():
        # Fallbacks (direkter Pfad)
        base_root = Path(CONFIG["NETWORK"]["WIN_DRIVE_LETTER"] + "\\") if is_windows() else Path(CONFIG["NETWORK"]["LINUX_MOUNT_POINT"])
        if not base_root.exists() and is_windows():
            base_root = Path(CONFIG["NETWORK"]["UNC_ROOT"])

    if not base_root or not base_root.exists():
        print(f"[FATAL] Basis-Root nicht gefunden: {base_root}")
        sys.exit(2)

    transcode_root = base_root / Path(CONFIG["PATHS"]["TRANSCODE_REL"])
    remux_root     = base_root / Path(CONFIG["PATHS"]["REMUX_REL"])
    logs_dir       = base_root / Path(CONFIG["PATHS"]["LOGS_REL"])
    ensure_dir(remux_root); ensure_dir(logs_dir)

    auslesen_log, remux_log = setup_loggers(logs_dir)
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

    # Filme
    movies = [s for s in sources if s.get("category") != "tv"]
    for src in movies:
        disp      = src["display"]
        src_path  = src["path"]
        item_root = src["item_root"]
        remux_log.info("\n" + "="*80)
        remux_log.info(f"[MOVIE] Quelle: {src_path} | {src['kind']} | Bezeichner: {disp}")

        tmp_out = remux_root / "_tmp" / sanitize_filename(disp)
        ensure_dir(tmp_out)

        ok = run_makemkv(makemkv, src_path, tmp_out, remux_log, dry_run=CONFIG["BEHAVIOR"]["DRY_RUN"])
        if not ok:
            remux_log.error(f"Remux FEHLGESCHLAGEN (Movie): {src_path}")
            delete_path(tmp_out, remux_log, dry_run=CONFIG["BEHAVIOR"]["DRY_RUN"])
            continue

        dest_base = destination_for_movie(remux_root, disp)
        moved = rename_and_move_movie(tmp_out, dest_base, disp, remux_log, dry_run=CONFIG["BEHAVIOR"]["DRY_RUN"])
        if not moved:
            remux_log.warning(f"Movie-Ausgabe nicht verschoben: {disp}")
            continue

        if CONFIG["BEHAVIOR"]["DELETE_ORIGINALS"]:
            remux_log.info(f"Original löschen: {item_root}")
            delete_path(item_root if item_root.is_dir() else src_path, remux_log, dry_run=CONFIG["BEHAVIOR"]["DRY_RUN"])

    # TV – pro Serie/Season gruppieren
    tvs = [s for s in sources if s.get("category") == "tv"]

    def series_key(s: str) -> str:
        s2 = re.sub(r"\b[Dd]isc\s*\d{1,2}\b", "", s)
        s2 = re.sub(r"\b[Dd](\d{1,2})\b", "", s2)
        s2 = re.sub(r"\b[Ss](?:eason)?\s*\d{1,2}\b", "", s2)
        s2 = re.sub(r"\bS\d{1,2}D\d{1,2}\b", "", s2)
        return sanitize_filename(s2).strip()

    groups: Dict[Tuple[str, Optional[int]], List[Dict]] = {}
    for s in tvs:
        key = (series_key(s["display"]), s.get("season"))
        groups.setdefault(key, []).append(s)

    for (series_base, season_no), discs in groups.items():
        remux_log.info("\n" + "="*80)
        remux_log.info(f"[TV] Serie='{series_base}' | Season={season_no} | Discs={len(discs)}")

        series_name, year_hint, _ = parse_name_year(series_base if series_base else "")
        expected_total_eps = tmdb_get_season_episode_count(series_name, year_hint, season_no, CONFIG["TMDB"], remux_log) if tmdb_is_enabled(CONFIG["TMDB"]) else None
        if expected_total_eps:
            remux_log.info("TMDb: Episodenzahl erkannt.")
        else:
            remux_log.info("TMDb: keine Episodenanzahl verfügbar.")

        discs_sorted = sorted(discs, key=lambda d: (d.get("disc") or 9999, str(d["path"])))
        next_ep = 1

        for idx, d in enumerate(discs_sorted):
            disp       = d["display"]
            src_path   = d["path"]
            item_root  = d["item_root"]
            disc_no    = d.get("disc")
            is_last    = (idx == len(discs_sorted)-1)

            remux_log.info("-"*60)
            remux_log.info(f"Disc: {disc_no if disc_no else '?'} | Quelle: {src_path} | Bezeichner: {disp} | Letzte Disc: {is_last}")

            tmp_out = remux_root / "_tmp" / sanitize_filename(f"{series_name or disp}_S{season_no or 0:02d}_D{disc_no or 0:02d}")
            ensure_dir(tmp_out)

            ok = run_makemkv(makemkv, src_path, tmp_out, remux_log, dry_run=CONFIG["BEHAVIOR"]["DRY_RUN"])
            if not ok:
                remux_log.error(f"Remux FEHLGESCHLAGEN (TV): {src_path}")
                delete_path(tmp_out, remux_log, dry_run=CONFIG["BEHAVIOR"]["DRY_RUN"])
                continue

            dest_base = destination_for_tv(remux_root, series_name or disp, season_no)
            moved, next_ep = rename_and_move_tv(
                tmp_out, dest_base, series_name or disp, season_no,
                next_ep, expected_total_eps, is_last, remux_log,
                dry_run=CONFIG["BEHAVIOR"]["DRY_RUN"]
            )
            if not moved:
                remux_log.warning(f"TV-Ausgabe nicht verschoben: {disp}")
                continue

            if CONFIG["HOOKS"]["MKV_MATCH"]["ENABLED"]:
                season_dir = destination_for_tv(remux_root, series_name or series_base, season_no)
                try:
                    ran = run_mkv_match(season_dir, season_no, series_name or series_base, remux_log, dry_run=CONFIG["BEHAVIOR"]["DRY_RUN"])
                    if ran and CONFIG["HOOKS"]["MKV_MATCH"]["RENAME_TO_SCHEMA"]:
                        normalize_mkv_match_naming(season_dir, series_name or series_base, season_no, remux_log, dry_run=CONFIG["BEHAVIOR"]["DRY_RUN"])
                except Exception as e:
                    remux_log.warning(f"mkv-match Hook übersprungen/fehlerhaft: {e}")

            if CONFIG["BEHAVIOR"]["DELETE_ORIGINALS"]:
                remux_log.info(f"Original löschen: {item_root}")
                delete_path(item_root if item_root.is_dir() else src_path, remux_log, dry_run=CONFIG["BEHAVIOR"]["DRY_RUN"])

    remux_log.info("\n" + "="*80)
    remux_log.info("Fertig – alle Quellen abgearbeitet.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAbgebrochen (Ctrl+C).")
