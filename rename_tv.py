# -*- coding: utf-8 -*-
from __future__ import annotations
import re, shutil, logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from config import CONFIG
from probe import probe_duration_seconds
from naming import parse_name_year
from utils import ensure_dir

def _extract_title_index(fname: str) -> int:
    m = re.search(r"[^\d](\d{1,3})\.mkv$", fname)
    if m: return int(m.group(1))
    m = re.search(r"_t(\d{1,3})\.mkv$", fname, re.IGNORECASE)
    if m: return int(m.group(1))
    m = re.search(r"(\d{1,3})\.mkv$", fname)
    return int(m.group(1)) if m else 9999

def _durations_for_files(files: List[Path], log: logging.Logger) -> Dict[Path, float]:
    d: Dict[Path, float] = {}
    for f in files:
        dur = probe_duration_seconds(f, log)
        d[f] = dur if dur is not None else -1.0
        try:
            size = f.stat().st_size
        except FileNotFoundError:
            size = -1
        log.debug(f"Dauer {f.name}: {d[f]} s  | Größe: {size} B")
    return d

def _median(values: List[float]) -> float:
    s = sorted(values); n = len(s)
    if n == 0: return 0.0
    mid = n // 2
    return (s[mid-1] + s[mid]) / 2.0 if n % 2 == 0 else s[mid]

def _near(value: float, target: float, tol_abs_min: float, tol_abs_max: float) -> bool:
    base_tol = max(tol_abs_min, min(tol_abs_max, target * 0.12))
    return abs(value - target) <= base_tol

def _is_playall(dur: float, ep_med: float, remaining_total: Optional[int]) -> bool:
    if ep_med <= 0 or dur <= 0: 
        return False
    if dur >= CONFIG["BEHAVIOR"]["PLAYALL_FACTOR_MIN"] * ep_med:
        return True
    if remaining_total is not None and remaining_total > 4 and dur >= CONFIG["BEHAVIOR"]["PLAYALL_FACTOR_SOFT"] * ep_med:
        return True
    for k in (3, 4, 5, 6, 7, 8):
        if _near(dur, k * ep_med, CONFIG["BEHAVIOR"]["PLAYALL_MULT_TOL_MIN"], CONFIG["BEHAVIOR"]["PLAYALL_MULT_TOL_MAX"]):
            if remaining_total is None or remaining_total >= k:
                return True
    return False

def rename_and_move_tv(
    tmp_out: Path,
    dest_base: Path,
    base_display: str,
    season_no: Optional[int],
    start_episode_no: int,
    expected_total_eps: Optional[int],
    is_last_disc: bool,
    log: logging.Logger,
) -> Tuple[bool, int]:
    files = sorted(tmp_out.glob("*.mkv"), key=lambda p: (_extract_title_index(p.name), p.name))
    if not files:
        log.error(f"Keine MKVs in {tmp_out}.")
        return False, start_episode_no

    name, year, version = parse_name_year(base_display)
    ensure_dir(dest_base)

    durations = _durations_for_files(files, log)
    TR   = CONFIG["BEHAVIOR"]["TRAILER_MAX"]
    EP_MIN = CONFIG["BEHAVIOR"]["EPISODE_MIN"]
    EP_MAX = CONFIG["BEHAVIOR"]["EPISODE_MAX"]
    TINY  = CONFIG["BEHAVIOR"]["TINY_FILE_BYTES"]
    tol   = CONFIG["BEHAVIOR"]["EPISODE_TOLERANCE"]
    dtol  = CONFIG["BEHAVIOR"]["DOUBLE_EP_TOL"]
    size_tol = CONFIG["BEHAVIOR"]["SIZE_TOLERANCE"]

    sizes = {f: (f.stat().st_size if f.exists() else -1) for f in files}

    candidates = [durations[f] for f in files
                  if durations.get(f, -1.0) >= EP_MIN and durations.get(f, -1.0) <= EP_MAX
                  and sizes.get(f, -1) >= TINY]
    ep_med = _median(candidates) if candidates else 0.0
    lo, hi = (ep_med*(1.0 - tol), ep_med*(1.0 + tol)) if ep_med > 0 else (0.0, 0.0)

    size_candidates = [sizes[f] for f in files if sizes.get(f, -1) >= TINY]
    size_med = float(_median(size_candidates)) if size_candidates else 0.0
    slo, shi = (size_med*(1.0 - size_tol), size_med*(1.0 + size_tol)) if size_med > 0 else (0.0, 0.0)

    remaining_total = None
    if expected_total_eps is not None:
        remaining_total = max(0, expected_total_eps - (start_episode_no - 1))

    log.info(
        f"Episoden-Median: {ep_med:.1f}s | Fenster: [{lo:.1f}, {hi:.1f}] | "
        f"Größen-Median: {size_med/1024/1024/1024:.2f} GiB | Fenster: [{slo/1024/1024/1024:.2f}, {shi/1024/1024/1024:.2f}] GiB | "
        f"Start-Episode: {start_episode_no:02d} | Erwartet gesamt: {expected_total_eps} | "
        f"Verbleibend: {remaining_total} | Letzte Disc: {is_last_disc} | Modus: {'SIZE' if (ep_med<=0 or len(candidates)<max(1,len(files)//3)) else 'DURATION'}"
    )

    def mv(src: Path, dst: Path):
        ensure_dir(dst.parent)
        if CONFIG["BEHAVIOR"]["DRY_RUN"]:
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
        dur  = durations.get(f, -1.0)
        size = sizes.get(f, -1)
        tiny = size >= 0 and size < TINY

        # 1) Trailer-Erkennung
        is_trailer = (dur >= 0 and dur <= TR) or (tiny and dur > 0 and dur <= EP_MIN*0.6)

        if use_size_fallback:
            # 2) Größenbasiert
            is_episode   = (not tiny) and (size_med > 0) and (size >= slo and size <= shi)
            is_double_ep = (not tiny) and (size_med > 0) and (size >= (2.0 - dtol) * size_med and size <= (2.0 + dtol) * size_med)
            playall      = (not tiny) and (size_med > 0) and (size >= CONFIG["BEHAVIOR"]["PLAYALL_FACTOR_MIN"] * size_med)
        else:
            # 2) Dauerbasiert
            is_episode   = (dur >= lo and dur <= hi) and not tiny
            is_double_ep = not tiny and dur > hi and dur >= (2.0 - dtol) * ep_med and dur <= (2.0 + dtol) * ep_med
            playall      = _is_playall(dur, ep_med, remaining_total)

        # Letzte Disc: Doppel-Folgen bevorzugen, kein Play-All, wenn <=4 fehlen
        if is_last_disc and remaining_total is not None and remaining_total <= 4:
            if is_double_ep:
                playall = False

        log.debug(
            f"Classify: {f.name} | dur={dur:.1f}s | size={size} | tiny={tiny} | "
            f"episode={is_episode} | double={is_double_ep} | trailer={is_trailer} | playall?={playall}"
        )

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
        if not CONFIG["BEHAVIOR"]["DRY_RUN"]:
            shutil.rmtree(tmp_out, ignore_errors=True)
    except Exception:
        pass

    return success_any, ep_no
