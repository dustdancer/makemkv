# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import json
import shutil
import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from naming import parse_name_year


# Parameter
TRAILER_MAX      = 240
EPISODE_MIN      = 18*60
EPISODE_MAX      = 65*60
TINY_FILE_BYTES  = 100 * 1024 * 1024
EP_TOL           = 0.15
DOUBLE_TOL       = 0.12
PLAYALL_MIN_X    = 3.0
PLAYALL_SOFT_X   = 2.7
PLAYALL_TOL_MIN  = 240
PLAYALL_TOL_MAX  = 480
SIZE_TOL         = 0.22  # Fallback über Größe


def _probe_duration_seconds(p: Path, log: logging.Logger) -> float:
    ff = "ffprobe"
    if shutil.which(ff):
        try:
            res = subprocess.run(
                [ff, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(p)],
                capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace"
            )
            if res.returncode == 0 and res.stdout.strip():
                return float(res.stdout.strip())
        except Exception as e:
            log.debug(f"ffprobe Fehler {p}: {e}")
    mi = "mediainfo"
    if shutil.which(mi):
        try:
            res = subprocess.run([mi, "--Output=JSON", str(p)], capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace")
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
            log.debug(f"mediainfo Fehler {p}: {e}")
    return -1.0


def _median(values: List[float]) -> float:
    s = sorted(values); n = len(s)
    if n == 0: return 0.0
    m = n // 2
    return (s[m-1] + s[m]) / 2.0 if n % 2 == 0 else s[m]


def _near(value: float, target: float, tol_abs_min: float, tol_abs_max: float) -> bool:
    base_tol = max(tol_abs_min, min(tol_abs_max, target * 0.12))
    return abs(value - target) <= base_tol


def _is_playall(dur: float, ep_med: float, remaining_total: Optional[int]) -> bool:
    if ep_med <= 0 or dur <= 0:
        return False
    if dur >= PLAYALL_MIN_X * ep_med:
        return True
    if remaining_total is not None and remaining_total > 4 and dur >= PLAYALL_SOFT_X * ep_med:
        return True
    for k in (3, 4, 5, 6, 7, 8):
        if _near(dur, k * ep_med, PLAYALL_TOL_MIN, PLAYALL_TOL_MAX):
            if remaining_total is None or remaining_total >= k:
                return True
    return False


def _extract_title_index(fname: str) -> int:
    m = re.search(r"[^\d](\d{1,3})\.mkv$", fname)
    if m: return int(m.group(1))
    m = re.search(r"_t(\d{1,3})\.mkv$", fname, re.IGNORECASE)
    if m: return int(m.group(1))
    m = re.search(r"(\d{1,3})\.mkv$", fname)
    return int(m.group(1)) if m else 9999


def rename_and_move_tv(
    tmp_out: Path,
    dest_base: Path,
    base_display: str,
    season_no: Optional[int],
    start_episode_no: int,
    expected_total_eps: Optional[int],
    is_last_disc: bool,
    log: logging.Logger,
    dry_run: bool = False,
) -> Tuple[bool, int]:

    files = sorted(tmp_out.glob("*.mkv"), key=lambda p: (_extract_title_index(p.name), p.name))
    if not files:
        log.error(f"Keine MKVs in {tmp_out}.")
        return False, start_episode_no

    name, year, version = parse_name_year(base_display)
    dest_base.mkdir(parents=True, exist_ok=True)

    durations: Dict[Path, float] = {}
    sizes: Dict[Path, int] = {}
    for f in files:
        durations[f] = _probe_duration_seconds(f, log)
        try:
            sizes[f] = f.stat().st_size
        except Exception:
            sizes[f] = -1
        log.debug(f"Dauer {f.name}: {durations[f]} s | Größe: {sizes[f]} B")

    # Kandidaten für Dauer-Median
    candidates = [durations[f] for f in files if EPISODE_MIN <= durations.get(f, -1.0) <= EPISODE_MAX and sizes.get(f, -1) >= TINY_FILE_BYTES]
    ep_med = _median(candidates) if candidates else 0.0
    lo, hi = (ep_med*(1.0-EP_TOL), ep_med*(1.0+EP_TOL)) if ep_med > 0 else (0.0, 0.0)

    # Größen-Fallback
    size_candidates = [sizes[f] for f in files if sizes.get(f, -1) >= TINY_FILE_BYTES]
    size_med = float(_median(size_candidates)) if size_candidates else 0.0
    slo, shi = (size_med*(1.0-SIZE_TOL), size_med*(1.0+SIZE_TOL)) if size_med > 0 else (0.0, 0.0)

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
        tiny = size >= 0 and size < TINY_FILE_BYTES

        # 1) Trailer
        is_trailer = (dur >= 0 and dur <= TRAILER_MAX) or (tiny and dur > 0 and dur <= EPISODE_MIN*0.6)

        if use_size_fallback:
            # 2) Größenbasiert
            is_episode   = (not tiny) and (size_med > 0) and (slo <= size <= shi)
            is_double_ep = (not tiny) and (size_med > 0) and ((2.0-DOUBLE_TOL)*size_med <= size <= (2.0+DOUBLE_TOL)*size_med)
            playall      = (not tiny) and (size_med > 0) and (size >= PLAYALL_MIN_X * size_med)
        else:
            # 2) Dauerbasiert
            is_episode   = (lo <= dur <= hi) and not tiny
            is_double_ep = (not tiny) and dur > hi and ((2.0-DOUBLE_TOL)*ep_med <= dur <= (2.0+DOUBLE_TOL)*ep_med)
            playall      = _is_playall(dur, ep_med, remaining_total)

        if is_last_disc and remaining_total is not None and remaining_total <= 4 and is_double_ep:
            playall = False

        log.debug(f"Classify: {f.name} | dur={dur:.1f}s | size={size} | tiny={tiny} | episode={is_episode} | double={is_double_ep} | trailer={is_trailer} | playall?={playall} | mode={'SIZE' if use_size_fallback else 'DURATION'}")

        if playall and not is_episode and not is_double_ep:
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
