# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Diese Datei enthält NUR die Umbenenn-/Heuristik.
# Sie wird von main.py momentan NICHT automatisch aufgerufen,
# damit der Scanner stabil bleibt. Orchestrierung folgt erst auf Zuruf.

# ----------------- shared helpers -----------------

def sanitize_filename(name: str) -> str:
    name = name.strip()
    name = re.sub(r"[\\/:\*\?\"<>\|\x00-\x1F]", "_", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip().rstrip("._")

def parse_name_year(base: str) -> Tuple[str, Optional[str], Optional[str]]:
    name = base; version = None
    mver = re.search(r"\[(.+?)\]", base)
    if mver:
        version = mver.group(1).strip()
        name = re.sub(r"\s*\[.+?\]\s*", " ", name).strip()
    my = re.search(r"\((\d{4})\)", base)
    year = my.group(1) if my else None
    if my:
        name = re.sub(r"\s*\(\d{4}\)\s*", " ", name).strip()
    name = sanitize_filename(name)
    return name, year, version

# ----------------- probing (ffprobe/mediainfo) -----------------

def _probe_ffprobe(path: Path, ffprobe_path: str, log: logging.Logger) -> Optional[float]:
    if not shutil.which(ffprobe_path):
        return None
    try:
        res = subprocess.run(
            [ffprobe_path, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace"
        )
        if res.returncode == 0 and res.stdout.strip():
            return float(res.stdout.strip())
    except Exception as e:
        log.debug(f"ffprobe Fehler {path}: {e}")
    return None

def _probe_mediainfo(path: Path, mediainfo_path: str, log: logging.Logger) -> Optional[float]:
    if not shutil.which(mediainfo_path):
        return None
    try:
        res = subprocess.run(
            [mediainfo_path, "--Output=JSON", str(path)],
            capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace"
        )
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout)
            tracks = data.get("media", {}).get("track", [])
            for t in tracks:
                if t.get("@type") == "General":
                    dur = t.get("Duration")
                    if dur:
                        val = float(dur)
                        return val/1000.0 if val > 10000 else val
    except Exception as e:
        log.debug(f"mediainfo Fehler {path}: {e}")
    return None

def probe_duration_seconds(p: Path, prefer_ffprobe: bool, ffprobe_path: str, mediainfo_path: str, log: logging.Logger) -> Optional[float]:
    if prefer_ffprobe:
        d = _probe_ffprobe(p, ffprobe_path, log)
        return d if d is not None else _probe_mediainfo(p, mediainfo_path, log)
    d = _probe_mediainfo(p, mediainfo_path, log)
    return d if d is not None else _probe_ffprobe(p, ffprobe_path, log)

# ----------------- classification helpers -----------------

def extract_title_index(fname: str) -> int:
    m = re.search(r"[^\d](\d{1,3})\.mkv$", fname)
    if m:
        return int(m.group(1))
    m = re.search(r"_t(\d{1,3})\.mkv$", fname, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d{1,3})\.mkv$", fname)
    return int(m.group(1)) if m else 9999

def median(values: List[float]) -> float:
    s = sorted(values); n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    return (s[mid-1] + s[mid]) / 2.0 if n % 2 == 0 else s[mid]

def near(value: float, target: float, tol_abs_min: float, tol_abs_max: float) -> bool:
    base_tol = max(tol_abs_min, min(tol_abs_max, target * 0.12))
    return abs(value - target) <= base_tol

def is_playall(dur: float, ep_med: float, remaining_total: Optional[int],
               factor_min: float, factor_soft: float,
               tol_min: float, tol_max: float) -> bool:
    if ep_med <= 0 or dur <= 0:
        return False
    if dur >= factor_min * ep_med:
        return True
    if remaining_total is not None and remaining_total > 4 and dur >= factor_soft * ep_med:
        return True
    for k in (3, 4, 5, 6, 7, 8):
        if near(dur, k * ep_med, tol_min, tol_max):
            if remaining_total is None or remaining_total >= k:
                return True
    return False

# ----------------- movie rename -----------------

def rename_and_move_movie(
    tmp_out: Path,
    dest_base: Path,
    base_display: str,
    behavior: dict,
    probe_cfg: dict,
    log: logging.Logger
) -> bool:
    files = sorted(tmp_out.glob("*.mkv"))
    if not files:
        log.error(f"Keine MKVs in {tmp_out}.")
        return False

    name, year, version = parse_name_year(base_display)
    dest_base.mkdir(parents=True, exist_ok=True)

    durations: Dict[Path, float] = {}
    for f in files:
        d = probe_duration_seconds(
            f,
            prefer_ffprobe=probe_cfg.get("prefer_ffprobe", True),
            ffprobe_path=probe_cfg.get("ffprobe_path", "ffprobe"),
            mediainfo_path=probe_cfg.get("mediainfo_path", "mediainfo"),
            log=log
        )
        durations[f] = d if d is not None else -1.0

    files_sorted = sorted(
        files,
        key=lambda p: (durations.get(p, -1.0), p.name),
        reverse=True
    )

    TR = int(behavior.get("trailer_max_seconds", 240))
    dry_run = bool(behavior.get("dry_run", True))

    def mv(src: Path, dst: Path):
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dry_run:
            log.info(f"[DRY-RUN] Move: {src} -> {dst}")
        else:
            shutil.move(str(src), str(dst))
            log.info(f"Verschoben: {src.name} -> {dst}")

    main_done = False
    trailer_counter = 1
    bonus_counter = 1
    ok = False

    for idx, f in enumerate(files_sorted):
        dur = durations.get(f, -1.0)
        is_trailer = dur >= 0 and dur <= TR
        if not main_done and (idx == 0) and (dur < 0 or dur >= 45*60):
            tgt_name = f"{name}.mkv" if not version else f"{name} [{version}].mkv"
            mv(f, dest_base / tgt_name)
            main_done = True; ok = True
        elif is_trailer:
            mv(f, dest_base / f"{name}_trailer{('-' + str(trailer_counter)) if trailer_counter > 1 else ''}.mkv")
            trailer_counter += 1; ok = True
        else:
            mv(f, dest_base / f"{name} [bonusmaterial] - extra{bonus_counter:02d}.mkv")
            bonus_counter += 1; ok = True

    if not main_done:
        log.warning("Kein plausibler Hauptfilm – Fallback trackNN.")
        for idx, f in enumerate(files_sorted):
            mv(f, dest_base / f"{name} track{idx+1:02d}.mkv")
            ok = True

    try:
        if not dry_run:
            shutil.rmtree(tmp_out, ignore_errors=True)
    except Exception:
        pass
    return ok

# ----------------- tv rename -----------------

def rename_and_move_tv(
    tmp_out: Path,
    dest_base: Path,
    base_display: str,
    season_no: Optional[int],
    start_episode_no: int,
    expected_total_eps: Optional[int],
    is_last_disc: bool,
    behavior: dict,
    probe_cfg: dict,
    log: logging.Logger,
) -> Tuple[bool, int]:
    files = sorted(tmp_out.glob("*.mkv"), key=lambda p: (extract_title_index(p.name), p.name))
    if not files:
        log.error(f"Keine MKVs in {tmp_out}.")
        return False, start_episode_no

    name, year, version = parse_name_year(base_display)
    dest_base.mkdir(parents=True, exist_ok=True)

    prefer_ffprobe = probe_cfg.get("prefer_ffprobe", True)
    ffprobe_path   = probe_cfg.get("ffprobe_path", "ffprobe")
    mediainfo_path = probe_cfg.get("mediainfo_path", "mediainfo")

    durations: Dict[Path, float] = {}
    sizes: Dict[Path, int] = {}
    for f in files:
        d = probe_duration_seconds(f, prefer_ffprobe, ffprobe_path, mediainfo_path, log)
        durations[f] = d if d is not None else -1.0
        try:
            sizes[f] = f.stat().st_size
        except FileNotFoundError:
            sizes[f] = -1

    TR    = int(behavior.get("trailer_max_seconds", 240))
    EP_MIN = int(behavior.get("episode_min_seconds", 18*60))
    EP_MAX = int(behavior.get("episode_max_seconds", 65*60))
    TINY   = int(behavior.get("tiny_file_bytes", 100 * 1024 * 1024))
    tol    = float(behavior.get("episode_tolerance", 0.15))
    dtol   = float(behavior.get("double_ep_tol", 0.12))
    size_tol = float(behavior.get("size_tolerance", 0.22))
    dry_run = bool(behavior.get("dry_run", True))

    factor_min  = float(behavior.get("playall_factor_min", 3.0))
    factor_soft = float(behavior.get("playall_factor_soft", 2.7))
    tol_min     = float(behavior.get("playall_mult_tol_min", 240))
    tol_max     = float(behavior.get("playall_mult_tol_max", 480))

    # Median (Dauer)
    candidates = [durations[f] for f in files
                  if durations.get(f, -1.0) >= EP_MIN and durations.get(f, -1.0) <= EP_MAX
                  and sizes.get(f, -1) >= TINY]
    ep_med = median(candidates) if candidates else 0.0
    lo, hi = (ep_med*(1.0 - tol), ep_med*(1.0 + tol)) if ep_med > 0 else (0.0, 0.0)

    # Median (Größe)
    size_candidates = [sizes[f] for f in files if sizes.get(f, -1) >= TINY]
    size_med = float(median(size_candidates)) if size_candidates else 0.0
    slo, shi = (size_med*(1.0 - size_tol), size_med*(1.0 + size_tol)) if size_med > 0 else (0.0, 0.0)

    remaining_total = None
    if expected_total_eps is not None:
        remaining_total = max(0, expected_total_eps - (start_episode_no - 1))

    log.info(
        f"Episoden-Median: {ep_med:.1f}s | Fenster: [{lo:.1f}, {hi:.1f}] | "
        f"Größen-Median: {size_med/1024/1024/1024:.2f} GiB | Fenster: [{slo/1024/1024/1024:.2f}, {shi/1024/1024/1024:.2f}] GiB | "
        f"Start-Episode: {start_episode_no:02d} | Erwartet gesamt: {expected_total_eps} | "
        f"Verbleibend: {remaining_total} | Letzte Disc: {is_last_disc}"
    )

    def mv(src: Path, dst: Path):
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dry_run:
            log.info(f"[DRY-RUN] Move: {src} -> {dst}")
        else:
            shutil.move(str(src), str(dst))
            log.info(f"Verschoben: {src.name} -> {dst}")

    ep_no = start_episode_no
    trailer_counter = 1
    bonus_counter = 1
    success_any = False

    use_size_fallback = (ep_med <= 0) or (len(candidates) < max(1, len(files)//3))

    for f in files:
        dur = durations.get(f, -1.0)
        size = sizes.get(f, -1)
        tiny = size >= 0 and size < TINY

        # Trailer
        is_trailer = (dur >= 0 and dur <= TR) or (tiny and dur > 0 and dur <= EP_MIN*0.6)

        if use_size_fallback:
            is_episode = (not tiny) and (size_med > 0) and (size >= slo and size <= shi)
            is_double_ep = (not tiny) and (size_med > 0) and (size >= (2.0 - dtol) * size_med and size <= (2.0 + dtol) * size_med)
            playall_candidate = (not tiny) and (size_med > 0) and (size >= factor_min * size_med)
        else:
            is_episode = (dur >= lo and dur <= hi) and not tiny
            is_double_ep = not tiny and dur > hi and dur >= (2.0 - dtol) * ep_med and dur <= (2.0 + dtol) * ep_med
            playall_candidate = dur > 0 and is_playall(dur, ep_med, remaining_total, factor_min, factor_soft, tol_min, tol_max)

        if is_last_disc and remaining_total is not None and remaining_total <= 4:
            if is_double_ep:
                playall_candidate = False

        log.debug(
            f"Classify: {f.name} | dur={dur:.1f}s | size={size} | tiny={tiny} | "
            f"episode={is_episode} | double={is_double_ep} | trailer={is_trailer} | playall?={playall_candidate} | "
            f"mode={'SIZE' if use_size_fallback else 'DURATION'}"
        )

        if playall_candidate and not is_episode and not is_double_ep:
            mv(f, dest_base / f"{name} [bonusmaterial] - playall.mkv")
            success_any = True
            continue

        if is_double_ep:
            if season_no is not None:
                tgt = dest_base / f"{name} – S{season_no:02d}E{ep_no:02d}-E{ep_no+1:02d}.mkv"
            else:
                tgt = dest_base / f"{name} – E{ep_no:02d}-E{ep_no+1:02d}.mkv"
            ep_no += 2
            mv(f, tgt)
            success_any = True
            continue

        if is_episode:
            if season_no is not None:
                tgt = dest_base / f"{name} – S{season_no:02d}E{ep_no:02d}.mkv"
            else:
                tgt = dest_base / f"{name} – E{ep_no:02d}.mkv"
            ep_no += 1
            mv(f, tgt)
            success_any = True
        elif is_trailer:
            mv(f, dest_base / f"{name}_trailer{('-' + str(trailer_counter)) if trailer_counter > 1 else ''}.mkv")
            trailer_counter += 1
            success_any = True
        else:
            mv(f, dest_base / f"{name} [bonusmaterial] - extra{bonus_counter:02d}.mkv")
            bonus_counter += 1
            success_any = True

    if (ep_no == start_episode_no) and (success_any is False):
        log.warning("Keine Episoden erkannt – Fallback trackNN (Reihenfolge beibehalten).")
        idx = 1
        for f in files:
            mv(f, dest_base / f"{name} track{idx:02d}.mkv")
            idx += 1
            success_any = True

    try:
        if not dry_run:
            shutil.rmtree(tmp_out, ignore_errors=True)
    except Exception:
        pass

    return success_any, ep_no
