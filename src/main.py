#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Lokale Module
from core.loader import load_config, setup_stage_loggers
from core.scanner import find_sources

# ---------------------------
# Hilfsfunktionen (allg.)
# ---------------------------

def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def sanitize_filename(name: str) -> str:
    name = name.strip()
    name = re.sub(r"[\\/:\*\?\"<>\|\x00-\x1F]", "_", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip().rstrip("._")

# ---------------------------
# MakeMKV
# ---------------------------

def find_makemkvcon(win_candidates: List[str], linux_name: str, log: logging.Logger) -> Optional[str]:
    if os.name == "nt":
        for p in win_candidates:
            if Path(p).exists():
                log.info(f"MakeMKV gefunden: {p}")
                return p
        log.error("MakeMKV CLI nicht gefunden. Prüfe 'makemkv.win_paths' in der config.")
        return None
    # Linux / macOS (CLI muss im PATH liegen oder absoluter Pfad)
    exe = shutil.which(linux_name) or linux_name
    if shutil.which(exe) or Path(exe).exists():
        log.info(f"MakeMKV gefunden: {exe}")
        return exe
    log.error("makemkvcon nicht gefunden (LINUX_PATH).")
    return None


def run_makemkv(makemkv: str, source_kind: str, source_path: Path, out_dir: Path,
                extra_opts: List[str], dry_run: bool, log: logging.Logger) -> bool:
    """
    Führt MakeMKV im Robot-Modus aus. source_kind: 'iso' oder 'file'
    """
    ensure_dir(out_dir)
    input_spec = f"iso:{source_path}" if source_kind == "iso" else f"file:{source_path}"
    cmd = [makemkv, "mkv"] + (extra_opts or []) + [input_spec, "all", str(out_dir)]
    log.info(f"MakeMKV: {' '.join(shlex.quote(x) for x in cmd)}")
    if dry_run:
        log.info("[DRY-RUN] MakeMKV nicht ausgeführt.")
        return True
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace")
        # Ausgabe in Debug kippen (viel Text)
        if res.stdout:
            for line in res.stdout.splitlines():
                log.debug(line)
        if res.returncode != 0:
            log.error(f"MakeMKV Returncode {res.returncode} – Quelle: {source_path}")
            return False
        return True
    except Exception as e:
        log.exception(f"Fehler beim MakeMKV-Aufruf: {e}")
        return False

# ---------------------------
# Probe (Dauer via ffprobe/mediainfo)
# ---------------------------

def _probe_ffprobe(ffprobe_path: str, f: Path, log: logging.Logger) -> Optional[float]:
    exe = shutil.which(ffprobe_path) or ffprobe_path
    if not shutil.which(exe) and not Path(exe).exists():
        return None
    try:
        res = subprocess.run([exe, "-v", "error", "-show_entries", "format=duration",
                              "-of", "default=nw=1:nk=1", str(f)],
                             capture_output=True, text=True, timeout=30,
                             encoding="utf-8", errors="replace")
        if res.returncode == 0 and res.stdout.strip():
            return float(res.stdout.strip())
    except Exception as e:
        log.debug(f"ffprobe Fehler {f}: {e}")
    return None


def _probe_mediainfo(mediainfo_path: str, f: Path, log: logging.Logger) -> Optional[float]:
    exe = shutil.which(mediainfo_path) or mediainfo_path
    if not shutil.which(exe) and not Path(exe).exists():
        return None
    try:
        res = subprocess.run([exe, "--Inform=General;%Duration%"], capture_output=True,
                             text=True, timeout=30, encoding="utf-8", errors="replace")
        # Falls ohne Datei-Argument kompiliert wurde, alternativer JSON-Aufruf:
        if res.returncode != 0:
            res = subprocess.run([exe, "--Output=JSON", str(f)], capture_output=True,
                                 text=True, timeout=30, encoding="utf-8", errors="replace")
        else:
            # normaler Aufruf braucht die Datei:
            res = subprocess.run([exe, "--Output=JSON", str(f)], capture_output=True,
                                 text=True, timeout=30, encoding="utf-8", errors="replace")

        if res.returncode == 0 and res.stdout.strip():
            import json
            data = json.loads(res.stdout)
            tracks = data.get("media", {}).get("track", [])
            for t in tracks:
                if t.get("@type") == "General":
                    dur = t.get("Duration")
                    if dur:
                        val = float(dur)
                        return val/1000.0 if val > 10000 else val
    except Exception as e:
        log.debug(f"mediainfo Fehler {f}: {e}")
    return None


def probe_duration_seconds(ffprobe_path: str, mediainfo_path: str, prefer_ffprobe: bool,
                           f: Path, log: logging.Logger) -> Optional[float]:
    if prefer_ffprobe:
        d = _probe_ffprobe(ffprobe_path, f, log)
        return d if d is not None else _probe_mediainfo(mediainfo_path, f, log)
    d = _probe_mediainfo(mediainfo_path, f, log)
    return d if d is not None else _probe_ffprobe(ffprobe_path, f, log)

# ---------------------------
# Zielpfade (Movies/TV)
# ---------------------------

def _parse_name_year(base: str) -> Tuple[str, Optional[str]]:
    name = base
    m = re.search(r"\((\d{4})\)", base)
    year = m.group(1) if m else None
    if m:
        name = re.sub(r"\s*\(\d{4}\)\s*", " ", name).strip()
    return sanitize_filename(name), year

def destination_for_movie(remux_root: Path, base: str) -> Path:
    name, year = _parse_name_year(base)
    dir_name = f"{name} ({year})" if year else name
    return remux_root / "movies" / dir_name

def destination_for_tv(remux_root: Path, series_base: str, season_no: Optional[int]) -> Path:
    name, year = _parse_name_year(series_base)
    series_dir = f"{name} ({year})" if year else name
    return remux_root / "tv" / series_dir / (f"season {season_no:02d}" if season_no else "season ??")

# ---------------------------
# Rename/Move – Movies
# ---------------------------

def _durations_for_files(files: List[Path], ffprobe: str, mediainfo: str, prefer_ffprobe: bool,
                         log: logging.Logger) -> Dict[Path, float]:
    d: Dict[Path, float] = {}
    for f in files:
        dur = probe_duration_seconds(ffprobe, mediainfo, prefer_ffprobe, f, log)
        d[f] = dur if dur is not None else -1.0
        try:
            size = f.stat().st_size
        except FileNotFoundError:
            size = -1
        log.debug(f"Dauer {f.name}: {d[f]} s  | Größe: {size} B")
    return d


def rename_and_move_movie(tmp_out: Path, dest_base: Path, base_display: str,
                          trailer_max: int, cfg_probe, dry_run: bool, log: logging.Logger) -> bool:
    files = sorted(tmp_out.glob("*.mkv"))
    if not files:
        log.error(f"Keine MKVs in {tmp_out}.")
        return False

    name, _ = _parse_name_year(base_display)
    ensure_dir(dest_base)

    durations = _durations_for_files(files, cfg_probe.ffprobe_path, cfg_probe.mediainfo_path,
                                     cfg_probe.prefer_ffprobe, log)
    # Sortierung: längste (oder unbekannt) zuerst
    files_sorted = sorted(files, key=lambda p: (durations.get(p, -1.0), p.name), reverse=True)

    main_done = False
    trailer_counter = 1
    bonus_counter = 1
    ok = False

    def mv(src: Path, dst: Path):
        ensure_dir(dst.parent)
        if dry_run:
            log.info(f"[DRY-RUN] Move: {src} -> {dst}")
        else:
            shutil.move(str(src), str(dst))
            log.info(f"Verschoben: {src.name} -> {dst}")

    for idx, f in enumerate(files_sorted):
        dur = durations.get(f, -1.0)
        is_trailer = dur >= 0 and dur <= trailer_max
        if not main_done and (idx == 0) and (dur < 0 or dur >= 45*60):
            mv(f, dest_base / f"{name}.mkv")
            main_done = True
            ok = True
        elif is_trailer:
            suffix = f"-{trailer_counter}" if trailer_counter > 1 else ""
            mv(f, dest_base / f"{name}_trailer{suffix}.mkv")
            trailer_counter += 1
            ok = True
        else:
            mv(f, dest_base / f"{name} [bonusmaterial] - extra{bonus_counter:02d}.mkv")
            bonus_counter += 1
            ok = True

    if not main_done:
        log.warning("Kein plausibler Hauptfilm – Fallback trackNN.")
        for idx, f in enumerate(files_sorted):
            mv(f, dest_base / f"{name} track{idx+1:02d}.mkv")
            ok = True

    # tmp löschen
    if not dry_run:
        shutil.rmtree(tmp_out, ignore_errors=True)
    return ok

# ---------------------------
# Rename/Move – TV
# ---------------------------

@dataclass
class TvHeuristics:
    trailer_max: int
    ep_min: int
    ep_max: int
    tiny_file_bytes: int
    episode_tol: float       # ± Anteil um Median
    double_ep_tol: float     # ± Anteil um 2×Median

def _median(values: List[float]) -> float:
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    return (s[mid-1] + s[mid]) / 2.0 if n % 2 == 0 else s[mid]

def extract_title_index(fname: str) -> int:
    m = re.search(r"[^\d](\d{1,3})\.mkv$", fname)
    if m:
        return int(m.group(1))
    m = re.search(r"_t(\d{1,3})\.mkv$", fname, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d{1,3})\.mkv$", fname)
    return int(m.group(1)) if m else 9999

def rename_and_move_tv(
    tmp_out: Path,
    dest_base: Path,
    series_base: str,
    season_no: Optional[int],
    start_episode_no: int,
    heur: TvHeuristics,
    cfg_probe,
    dry_run: bool,
    log: logging.Logger,
) -> Tuple[bool, int]:
    files = sorted(tmp_out.glob("*.mkv"), key=lambda p: (extract_title_index(p.name), p.name))
    if not files:
        log.error(f"Keine MKVs in {tmp_out}.")
        return False, start_episode_no

    series_name, _ = _parse_name_year(series_base)
    ensure_dir(dest_base)

    durations = _durations_for_files(files, cfg_probe.ffprobe_path, cfg_probe.mediainfo_path,
                                     cfg_probe.prefer_ffprobe, log)

    # Kandidaten für Median
    sizes = {f: (f.stat().st_size if f.exists() else -1) for f in files}
    candidates = [
        durations[f] for f in files
        if heur.ep_min <= durations.get(f, -1.0) <= heur.ep_max and sizes.get(f, -1) >= heur.tiny_file_bytes
    ]
    ep_med = _median(candidates) if candidates else (heur.ep_min + heur.ep_max) / 2.0
    lo, hi = ep_med * (1.0 - heur.episode_tol), ep_med * (1.0 + heur.episode_tol)

    log.info(f"Episoden-Median: {ep_med:.1f}s | Fenster: [{lo:.1f}, {hi:.1f}] | Start-Episode: {start_episode_no:02d}")

    def mv(src: Path, dst: Path):
        ensure_dir(dst.parent)
        if dry_run:
            log.info(f"[DRY-RUN] Move: {src} -> {dst}")
        else:
            shutil.move(str(src), str(dst))
            log.info(f"Verschoben: {src.name} -> {dst}")

    ep_no = start_episode_no
    trailer_counter = 1
    bonus_counter = 1
    success_any = False

    for f in files:
        dur = durations.get(f, -1.0)
        try:
            size = f.stat().st_size
        except FileNotFoundError:
            size = -1
        tiny = 0 <= size < heur.tiny_file_bytes

        is_trailer = (0 <= dur <= heur.trailer_max) or (tiny and 0 < dur <= heur.ep_min * 0.6)
        is_episode = (lo <= dur <= hi) and not tiny
        is_double_ep = (dur > hi) and (abs(dur - 2 * ep_med) <= heur.double_ep_tol * 2 * ep_med) and not tiny

        log.debug(
            f"Classify: {f.name} | dur={dur:.1f}s | size={size} | tiny={tiny} | "
            f"episode={is_episode} | double={is_double_ep} | trailer={is_trailer}"
        )

        if is_double_ep:
            if season_no is not None:
                tgt = dest_base / f"{series_name} – S{season_no:02d}E{ep_no:02d}-E{ep_no+1:02d}.mkv"
            else:
                tgt = dest_base / f"{series_name} – E{ep_no:02d}-E{ep_no+1:02d}.mkv"
            ep_no += 2
            mv(f, tgt)
            success_any = True
            continue

        if is_episode:
            if season_no is not None:
                tgt = dest_base / f"{series_name} – S{season_no:02d}E{ep_no:02d}.mkv"
            else:
                tgt = dest_base / f"{series_name} – E{ep_no:02d}.mkv"
            ep_no += 1
            mv(f, tgt)
            success_any = True
        elif is_trailer:
            suffix = f"-{trailer_counter}" if trailer_counter > 1 else ""
            mv(f, dest_base / f"{series_name}_trailer{suffix}.mkv")
            trailer_counter += 1
            success_any = True
        else:
            mv(f, dest_base / f"{series_name} [bonusmaterial] - extra{bonus_counter:02d}.mkv")
            bonus_counter += 1
            success_any = True

    if (ep_no == start_episode_no) and not success_any:
        log.warning("Keine Episoden erkannt – Fallback trackNN.")
        idx = 1
        for f in files:
            mv(f, dest_base / f"{series_name} track{idx:02d}.mkv")
            idx += 1
            success_any = True

    if not dry_run:
        shutil.rmtree(tmp_out, ignore_errors=True)

    return success_any, ep_no

# ---------------------------
# Orchestrierung (main)
# ---------------------------

def series_key_for_grouping(display: str) -> str:
    s = display
    # Disc/Season-Indikatoren rauswerfen, damit Gruppierung stabil ist
    s = re.sub(r"\b[Ss](?:taffel|eason)?\s*\d{1,2}\b", "", s)
    s = re.sub(r"\b[Dd](?:isc|isk)?\s*\d{1,2}\b", "", s)
    s = re.sub(r"\bS\d{1,2}D\d{1,2}\b", "", s)
    s = re.sub(r"\s+", " ", s)
    return sanitize_filename(s).strip()

def main():
    cfg = load_config()

    # Logger initialisieren (AUSLESEN/REMUX/RENAME + Pipeline)
    auslesen_log, remux_log, rename_log, pipeline_path = setup_stage_loggers(
        cfg.paths.logs_dir, log_level=cfg.app.log_level
    )

    # Header
    auslesen_log.info("=== START: Testlauf Logger + Scanner ===")
    auslesen_log.info(f"Base Root     : {cfg.paths.base_root}")
    auslesen_log.info(f"Transcode Dir : {cfg.paths.transcode_dir}")
    auslesen_log.info(f"Remux Dir     : {cfg.paths.remux_dir}")
    auslesen_log.info(f"Logs Dir      : {cfg.paths.logs_dir}")
    auslesen_log.info(f"Dry-Run       : {cfg.app.dry_run}")
    auslesen_log.info(f"TMDb enabled  : {cfg.tmdb.enabled}")

    # 1) Scanner
    if not cfg.paths.transcode_dir.exists():
        auslesen_log.error(f"Transcode-Verzeichnis existiert nicht: {cfg.paths.transcode_dir}")
        auslesen_log.info("=== ENDE: Keine Quellen ===")
        auslesen_log.info(f"(Gesamte Pipeline-Logs in: {pipeline_path})")
        sys.exit(3)

    sources = find_sources(cfg.paths.transcode_dir, auslesen_log)
    auslesen_log.info(f"Gefundene Quellen: {len(sources)}")
    for i, s in enumerate(sources[:max(1, min(10, len(sources)))], 1):
        auslesen_log.info(
            f"[{i:03d}] cat={s.get('category','-')} | kind={s['kind']} | disc_type={s.get('disc_type','?')} | "
            f"season={s.get('season')} | disc={s.get('disc')} | display='{s['display']}' | path={s['path']}"
            + (f" | note={s.get('note')}" if s.get("note") else "")
        )
    auslesen_log.info("=== ENDE: Testlauf Logger + Scanner ===")
    auslesen_log.info(f"(Gesamte Pipeline-Logs in: {pipeline_path})")

    if not sources:
        return

    # 2) MakeMKV Pfad
    makemkv = find_makemkvcon(cfg.makemkv.win_paths, cfg.makemkv.linux_path, remux_log)
    if not makemkv:
        remux_log.error("Abbruch – MakeMKV CLI nicht gefunden.")
        remux_log.info(f"(Gesamte Pipeline-Logs in: {pipeline_path})")
        sys.exit(4)

    # 3) Filme/TV splitten
    movies = [s for s in sources if (s.get("category") != "tv")]
    tvs    = [s for s in sources if (s.get("category") == "tv")]

    # 4) Filme remuxen + umbenennen
    for src in movies:
        disp = src["display"]
        src_path: Path = src["path"]
        item_root: Path = src["item_root"]
        kind = src["kind"]  # iso|file

        remux_log.info("=" * 80)
        remux_log.info(f"[MOVIE] Quelle: {src_path} | {kind} | Bezeichner: {disp}")

        tmp_out = cfg.paths.remux_dir / "_tmp" / sanitize_filename(disp)
        ensure_dir(tmp_out)

        ok_rip = run_makemkv(
            makemkv, "iso" if kind == "iso" else "file", src_path, tmp_out,
            cfg.makemkv.extra_opts, cfg.app.dry_run, remux_log
        )
        if not ok_rip:
            remux_log.error(f"Remux FEHLGESCHLAGEN (Movie): {src_path}")
            if not cfg.app.dry_run:
                shutil.rmtree(tmp_out, ignore_errors=True)
            continue

        dest_base = destination_for_movie(cfg.paths.remux_dir, disp)
        ok_mv = rename_and_move_movie(
            tmp_out, dest_base, disp,
            cfg.behavior.trailer_max_seconds,
            cfg.probe, cfg.app.dry_run, remux_log
        )
        if not ok_mv:
            remux_log.warning(f"Movie-Ausgabe nicht verschoben: {disp}")
            continue

        if cfg.behavior.delete_originals:
            rename_log.info(f"Original löschen (Movie): {item_root}")
            if cfg.app.dry_run:
                rename_log.info(f"[DRY-RUN] Löschen: {item_root}")
            else:
                if item_root.is_dir():
                    shutil.rmtree(item_root, ignore_errors=True)
                else:
                    try:
                        item_root.unlink(missing_ok=True)
                    except Exception:
                        pass

    # 5) TV-Gruppierung (Serie/Season)
    def key_tuple(s: Dict) -> Tuple[str, Optional[int]]:
        return (series_key_for_grouping(s["display"]), s.get("season"))

    # Gruppen nach Serie/Season
    tv_groups: Dict[Tuple[str, Optional[int]], List[Dict]] = {}
    for s in tvs:
        tv_groups.setdefault(key_tuple(s), []).append(s)

    heur = TvHeuristics(
        trailer_max=cfg.behavior.trailer_max_seconds,
        ep_min=cfg.behavior.episode_min_seconds,
        ep_max=cfg.behavior.episode_max_seconds,
        tiny_file_bytes=100 * 1024 * 1024,  # 100 MB
        episode_tol=0.15,
        double_ep_tol=0.12,
    )

    for (series_base, season_no), discs in tv_groups.items():
        remux_log.info("=" * 80)
        remux_log.info(f"[TV] Serie='{series_base}' | Season={season_no} | Discs={len(discs)}")

        # Discs numerisch sortieren (wenn vorhanden), sonst Pfad
        discs_sorted = sorted(discs, key=lambda d: (d.get("disc") or 9999, str(d["path"])))
        next_ep = 1

        for d in discs_sorted:
            disp = d["display"]
            src_path: Path = d["path"]
            item_root: Path = d["item_root"]
            disc_no = d.get("disc")
            kind = d["kind"]

            remux_log.info("-" * 60)
            remux_log.info(f"Disc: {disc_no if disc_no else '?'} | Quelle: {src_path} | Bezeichner: {disp}")

            tmp_out = cfg.paths.remux_dir / "_tmp" / sanitize_filename(f"{series_base or disp}_S{(season_no or 0):02d}_D{(disc_no or 0):02d}")
            ensure_dir(tmp_out)

            ok_rip = run_makemkv(
                makemkv, "iso" if kind == "iso" else "file", src_path, tmp_out,
                cfg.makemkv.extra_opts, cfg.app.dry_run, remux_log
            )
            if not ok_rip:
                remux_log.error(f"Remux FEHLGESCHLAGEN (TV): {src_path}")
                if not cfg.app.dry_run:
                    shutil.rmtree(tmp_out, ignore_errors=True)
                continue

            dest_base = destination_for_tv(cfg.paths.remux_dir, series_base or disp, season_no)
            ok_mv, next_ep = rename_and_move_tv(
                tmp_out, dest_base, series_base or disp, season_no, next_ep,
                heur, cfg.probe, cfg.app.dry_run, rename_log
            )
            if not ok_mv:
                rename_log.warning(f"TV-Ausgabe nicht verschoben: {disp}")
                continue

            if cfg.behavior.delete_originals:
                rename_log.info(f"Original löschen (TV): {item_root}")
                if cfg.app.dry_run:
                    rename_log.info(f"[DRY-RUN] Löschen: {item_root}")
                else:
                    if item_root.is_dir():
                        shutil.rmtree(item_root, ignore_errors=True)
                    else:
                        try:
                            item_root.unlink(missing_ok=True)
                        except Exception:
                            pass

    remux_log.info("=" * 80)
    remux_log.info("Fertig – alle Quellen abgearbeitet.")
    remux_log.info(f"(Gesamte Pipeline-Logs in: {pipeline_path})")


if __name__ == "__main__":
    main()
