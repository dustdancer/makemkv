# file: makemkv/rename_movie.py
from __future__ import annotations

"""
Umbenennen & Verschieben für Filme.

Heuristik:
- Hauptfilm = längste (bekannte) Laufzeit; bei unbekannter Laufzeit: größte Datei
- Trailer = Dauer <= TRAILER_MAX (Standard 240s) ODER sehr kleine Datei (TINY_FILE_BYTES)
- Rest → Bonusmaterial (extra01/extra02/…)
- Optionales Suffix in Klammern (Version/Edition) wird in den Hauptfilm-Namen übernommen.

API:
    rename_and_move_movie(tmp_out, dest_base, base_display, log) -> bool
"""

import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import CONFIG
from .probe import durations_for_files
from .naming import parse_name_year, sanitize_filename
from .utils import ensure_dir  # erwartet ensure_dir(Path) in utils.py


__all__ = ["rename_and_move_movie"]


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


def _move(src: Path, dst: Path, log) -> None:
    ensure_dir(dst.parent)
    if CONFIG["BEHAVIOR"].get("DRY_RUN", False):
        log.info(f"[DRY-RUN] Move: {src} -> {dst}")
        return
    dst = _unique_path(dst)
    shutil.move(str(src), str(dst))
    log.info(f"Verschoben: {src.name} -> {dst}")


def rename_and_move_movie(tmp_out: Path, dest_base: Path, base_display: str, log) -> bool:
    """
    Verschiebt alle MKVs aus tmp_out nach dest_base gemäß Movie-Heuristik.

    :param tmp_out:   temporärer MakeMKV-Ausgabeordner (enthält *.mkv)
    :param dest_base: endgültiger Zielordner (z. B. …/remux/movies/<Titel (Jahr)>)
    :param base_display: Anzeigename/Quelle (z. B. Ordner-/ISO-Name)
    :param log:       Logger
    :return: True, wenn etwas verschoben wurde
    """
    files = sorted(tmp_out.glob("*.mkv"))
    if not files:
        log.error(f"Keine MKVs in {tmp_out}.")
        return False

    # Zielordner anlegen
    ensure_dir(dest_base)

    # Titelmetadaten aus dem Anzeigenamen ableiten
    name, year, version = parse_name_year(base_display)
    title_base = name  # Jahr wird im Ordner geführt, nicht im Dateinamen
    main_name = f"{title_base}.mkv" if not version else f"{title_base} [{version}].mkv"

    # Laufzeiten & Größen ermitteln
    durations = durations_for_files(files, log)  # -1.0, wenn unbekannt
    sizes = _sizes_for_files(files)

    # Sortierschlüssel: 1) bekannte Dauer absteigend, 2) Größe absteigend, 3) Name
    def sort_key(p: Path) -> Tuple[float, int, str]:
        d = durations.get(p, -1.0)
        d_key = d if d is not None and d >= 0 else -1.0  # unbekannt = -1
        s_key = sizes.get(p, -1)
        return (d_key, s_key, p.name)

    files_sorted = sorted(files, key=sort_key, reverse=True)

    # Schwellwerte
    TR = CONFIG["BEHAVIOR"]["TRAILER_MAX"]             # Sekunden
    TINY = CONFIG["BEHAVIOR"]["TINY_FILE_BYTES"]       # Bytes

    moved_any = False
    main_done = False
    trailer_counter = 1
    bonus_counter = 1

    # Kandidat für Hauptfilm ist immer das erste Element der sortierten Liste
    # (längste bekannte Laufzeit; sonst größte Datei)
    for idx, f in enumerate(files_sorted):
        dur = float(durations.get(f, -1.0))
        size = sizes.get(f, -1)
        is_tiny = size >= 0 and size < TINY
        is_trailer = (dur >= 0 and dur <= TR) or (is_tiny and 0 < dur <= TR * 2)

        if not main_done and idx == 0:
            # Hauptfilm
            _move(f, dest_base / main_name, log)
            main_done = True
            moved_any = True
            continue

        if is_trailer:
            # Trailer
            suffix = f"-{trailer_counter}" if trailer_counter > 1 else ""
            _move(f, dest_base / f"{title_base}_trailer{suffix}.mkv", log)
            trailer_counter += 1
            moved_any = True
        else:
            # Bonusmaterial
            _move(f, dest_base / f"{title_base} [bonusmaterial] - extra{bonus_counter:02d}.mkv", log)
            bonus_counter += 1
            moved_any = True

    # Falls unser "Hauptfilm" nicht plausibel war (z. B. einziger Track extrem klein)
    # → Fallback: trackNN für alle (Reihenfolge beibehalten)
    if not main_done:
        log.warning("Kein plausibler Hauptfilm – Fallback trackNN.")
        for i, f in enumerate(files_sorted, 1):
            _move(f, dest_base / f"{title_base} track{i:02d}.mkv", log)
            moved_any = True

    # tmp-Ordner aufräumen (best effort)
    if not CONFIG["BEHAVIOR"].get("DRY_RUN", False):
        try:
            shutil.rmtree(tmp_out, ignore_errors=True)
        except Exception:
            pass

    return moved_any
