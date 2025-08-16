# file: makemkv/rename_tv.py
from __future__ import annotations

"""
Umbenennen & Verschieben für TV-Staffeln/Discs.

Heuristik:
- Adaptive Episoden-Erkennung per Median + ±Toleranz (Dauer in Sekunden)
- Doppel-Episoden ≈ 2× Median (SxxExx-Eyy)
- "Play All" nur bei klaren Vielfachen (≥3× Median) bzw. wenn noch viele verbleiben
- Fallback bei unbekannten Laufzeiten: Größen-Median (GiB) mit ±Toleranz
- Trailer: sehr kurz (<= TRAILER_MAX) oder sehr kleine Datei (TINY_FILE_BYTES)
- Bonus: alles, was nicht als Episode/Doppel/Trailer klassifiziert wird

API:
    rename_and_move_tv(
        tmp_out, dest_base, base_display, season_no, start_episode_no,
        expected_total_eps, is_last_disc, log, ui=None,
        current_disc_index=None, total_discs=None
    ) -> (moved_any: bool, next_episode_no: int)

Optional: `ui` kann ein Objekt mit `bar(prefix, current, total)` und `done()` sein
          (siehe logui.TextUI/ConsoleUI). Dann wird während des Umbenennens
          eine Fortschrittsanzeige mit verbleibenden Tracks/Discs angezeigt.
"""

import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import CONFIG
from .probe import durations_for_files
from .naming import parse_name_year, sanitize_filename
from .utils import ensure_dir


__all__ = ["rename_and_move_tv"]


# --------------------------
# Hilfsfunktionen
# --------------------------

def _sizes_for_files(files: List[Path]) -> Dict[Path, int]:
    sizes: Dict[Path, int] = {}
    for f in files:
        try:
            sizes[f] = f.stat().st_size
        except FileNotFoundError:
            sizes[f] = -1
    return sizes


def _unique_path(dst: Path) -> Path:
    """Hänge (n) an, falls Datei bereits existiert."""
    if not dst.exists():
        return dst
    stem, ext = dst.stem, dst.suffix
    i = 1
    while True:
        cand = dst.with_name(f"{stem} ({i}){ext}")
        if not cand.exists():
            return cand
        i += 1


def _mv(src: Path, dst: Path, log) -> None:
    ensure_dir(dst.parent)
    if CONFIG["BEHAVIOR"].get("DRY_RUN", False):
        log.info(f"[DRY-RUN] Move: {src} -> {dst}")
        return
    dst = _unique_path(dst)
    shutil.move(str(src), str(dst))
    log.info(f"Verschoben: {src.name} -> {dst}")


def _extract_title_index(fname: str) -> int:
    # typische MakeMKV-Namen: "*_tNN.mkv" oder "...NN.mkv"
    import re
    m = re.search(r"_t(\d{1,3})\.mkv$", fname, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d{1,3})\.mkv$", fname)
    return int(m.group(1)) if m else 9999


def _median(values: List[float]) -> float:
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    return (s[mid - 1] + s[mid]) / 2.0 if n % 2 == 0 else s[mid]


def _near(value: float, target: float, tol_abs_min: float, tol_abs_max: float) -> bool:
    # für Dauerbasierte k×Median-Vergleiche (mit absoluten Toleranzkorridoren)
    return abs(value - target) <= max(tol_abs_min, min(tol_abs_max, target * 0.12))


def _is_playall_by_duration(dur: float, ep_med: float, remaining_total: Optional[int]) -> bool:
    if ep_med <= 0 or dur <= 0:
        return False
    beh = CONFIG["BEHAVIOR"]
    if dur >= beh["PLAYALL_FACTOR_MIN"] * ep_med:
        return True
    if (remaining_total is not None) and remaining_total > 4 and dur >= beh["PLAYALL_FACTOR_SOFT"] * ep_med:
        return True
    # Prüfe k×Median mit absoluten Toleranzen (4–8 min Fenster)
    for k in (3, 4, 5, 6, 7, 8):
        if _near(dur, k * ep_med, beh["PLAYALL_MULT_TOL_MIN"], beh["PLAYALL_MULT_TOL_MAX"]):
            if remaining_total is None or remaining_total >= k:
                return True
    return False


# --------------------------
# Hauptfunktion
# --------------------------

def rename_and_move_tv(
    tmp_out: Path,
    dest_base: Path,
    base_display: str,
    season_no: Optional[int],
    start_episode_no: int,
    expected_total_eps: Optional[int],
    is_last_disc: bool,
    log,
    ui=None,
    current_disc_index: Optional[int] = None,  # 1-basiert
    total_discs: Optional[int] = None,
) -> Tuple[bool, int]:
    """
    Verschiebt alle MKVs aus tmp_out nach dest_base gemäß TV-Heuristik.

    :return: (mindestens_eine_datei_verschoben, nächste_ep_nummer)
    """
    files = sorted(tmp_out.glob("*.mkv"), key=lambda p: (_extract_title_index(p.name), p.name))
    if not files:
        log.error(f"Keine MKVs in {tmp_out}.")
        return False, start_episode_no

    series_name, year_hint, _ = parse_name_year(base_display)
    ensure_dir(dest_base)

    # Dauer & Größe sammeln
    durations = durations_for_files(files, log)  # -1.0, wenn unbekannt
    sizes = _sizes_for_files(files)

    beh = CONFIG["BEHAVIOR"]
    TR = beh["TRAILER_MAX"]
    EP_MIN = beh["EPISODE_MIN"]
    EP_MAX = beh["EPISODE_MAX"]
    TINY = beh["TINY_FILE_BYTES"]
    tol = beh["EPISODE_TOLERANCE"]
    dtol = beh["DOUBLE_EP_TOL"]
    size_tol = beh["SIZE_TOLERANCE"]

    # Kandidaten für Medianbildung (Dauer)
    dur_candidates = [
        d for f, d in durations.items()
        if (d is not None and d >= EP_MIN and d <= EP_MAX and sizes.get(f, -1) >= TINY)
    ]
    ep_med = _median(dur_candidates) if dur_candidates else 0.0
    lo, hi = (ep_med * (1.0 - tol), ep_med * (1.0 + tol)) if ep_med > 0 else (0.0, 0.0)

    # Größenbasierter Median (GiB)
    size_candidates = [sizes[f] for f in files if sizes.get(f, -1) >= TINY]
    size_med = float(_median(size_candidates)) if size_candidates else 0.0
    slo, shi = (size_med * (1.0 - size_tol), size_med * (1.0 + size_tol)) if size_med > 0 else (0.0, 0.0)

    remaining_total = None
    if expected_total_eps is not None:
        remaining_total = max(0, expected_total_eps - (start_episode_no - 1))

    log.info(
        "Episoden-Median: %.1fs | Fenster: [%.1f, %.1f] | "
        "Episoden-Median (Größe): %.3f GB | Fenster: [%.3f, %.3f] GB | "
        "Start-Episode: %02d | Erwartet gesamt: %s | Verbleibend: %s | Letzte Disc: %s | Modus: %s",
        ep_med, lo, hi,
        size_med / (1024**3), slo / (1024**3), shi / (1024**3),
        start_episode_no,
        str(expected_total_eps), str(remaining_total), str(is_last_disc),
        "SIZE" if (ep_med <= 0 or len(dur_candidates) < max(1, len(files)//3)) else "DURATION"
    )

    # Klassifikation & Move
    ep_no = start_episode_no
    success_any = False
    trailer_counter = 1
    bonus_counter = 1

    use_size_fallback = (ep_med <= 0) or (len(dur_candidates) < max(1, len(files)//3))

    total_tracks = len(files)
    discs_left = None
    if current_disc_index is not None and total_discs is not None:
        # Discs, die NACH dieser noch folgen:
        discs_left = max(0, total_discs - current_disc_index)

    for idx, f in enumerate(files, start=1):
        left_tracks = total_tracks - idx
        if ui is not None and hasattr(ui, "bar"):
            # Prefix enthält die Zusatzinfos, damit die Bar sie anzeigt
            prefix = f"Umbenennen: {series_name}"
            if current_disc_index and total_discs:
                prefix += f" (Disc {current_disc_index}/{total_discs})"
            if discs_left is not None:
                prefix += f" | Tracks übrig: {left_tracks} | Discs danach: {discs_left}"
            ui.bar(prefix, idx, total_tracks)

        dur = float(durations.get(f, -1.0))
        size = sizes.get(f, -1)
        tiny = size >= 0 and size < TINY

        # 1) Trailer-Erkennung
        is_trailer = (dur >= 0 and dur <= TR) or (tiny and 0 < dur <= EP_MIN * 0.6)

        if use_size_fallback:
            # 2) Größenbasierte Episode / Double
            is_episode = (not tiny) and (size_med > 0) and (size >= slo and size <= shi)
            is_double = (not tiny) and (size_med > 0) and (size >= (2.0 - dtol) * size_med and size <= (2.0 + dtol) * size_med)
            # 3) Größenbasierter Play-All
            is_playall = (not tiny) and (size_med > 0) and (size >= beh["PLAYALL_FACTOR_MIN"] * size_med)
        else:
            # 2) Dauerbasierte Episode / Double
            is_episode = (dur >= lo and dur <= hi) and not tiny
            is_double = (not tiny) and (dur > hi) and (dur >= (2.0 - dtol) * ep_med and dur <= (2.0 + dtol) * ep_med)
            # 3) Dauerbasierter Play-All
            is_playall = _is_playall_by_duration(dur, ep_med, remaining_total)

        # Letzte Disc: Bevorzuge Doppel-Episoden statt Play-All, wenn <=4 fehlen
        if is_last_disc and remaining_total is not None and remaining_total <= 4:
            if is_double:
                is_playall = False

        log.debug(
            "Classify: %s | dur=%.1fs | size=%d | tiny=%s | episode=%s | double=%s | trailer=%s | playall?=%s | mode=%s",
            f.name, dur, size, tiny, is_episode, is_double, is_trailer, is_playall,
            "SIZE" if use_size_fallback else "DURATION"
        )

        # Zielpfade
        if is_playall and not is_episode and not is_double:
            _mv(f, dest_base / f"{series_name} [bonusmaterial] - playall.mkv", log)
            success_any = True
            continue

        if is_double:
            if season_no is not None:
                tgt = dest_base / f"{series_name} – S{season_no:02d}E{ep_no:02d}-E{ep_no+1:02d}.mkv"
            else:
                tgt = dest_base / f"{series_name} – E{ep_no:02d}-E{ep_no+1:02d}.mkv"
            _mv(f, tgt, log)
            ep_no += 2
            success_any = True
            continue

        if is_episode:
            if season_no is not None:
                tgt = dest_base / f"{series_name} – S{season_no:02d}E{ep_no:02d}.mkv"
            else:
                tgt = dest_base / f"{series_name} – E{ep_no:02d}.mkv"
            _mv(f, tgt, log)
            ep_no += 1
            success_any = True
            continue

        if is_trailer:
            suffix = f"-{trailer_counter}" if trailer_counter > 1 else ""
            _mv(f, dest_base / f"{series_name}_trailer{suffix}.mkv", log)
            trailer_counter += 1
            success_any = True
        else:
            _mv(f, dest_base / f"{series_name} [bonusmaterial] - extra{bonus_counter:02d}.mkv", log)
            bonus_counter += 1
            success_any = True

    if ui is not None and hasattr(ui, "done"):
        ui.done()

    # Fallback: gar nichts erkannt
    if (ep_no == start_episode_no) and (success_any is False):
        log.warning("Keine Episoden erkannt – Fallback trackNN (Reihenfolge beibehalten).")
        for i, f in enumerate(files, 1):
            _mv(f, dest_base / f"{series_name} track{i:02d}.mkv", log)
            success_any = True

    # tmp-Ordner aufräumen (best effort)
    if not CONFIG["BEHAVIOR"].get("DRY_RUN", False):
        try:
            shutil.rmtree(tmp_out, ignore_errors=True)
        except Exception:
            pass

    return success_any, ep_no
