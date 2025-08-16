# file: makemkv/hooks.py
from __future__ import annotations

"""
Hook-Module

Aktuell enthalten:
- mkv-match Hook (optional): Führt nach dem Remux einen externen Matcher aus
  und kann die erzeugten Dateien anschließend in ein einheitliches Schema
  umbenennen:
    "Serienname – SxxExx - Episodentitel.mkv"
"""

import logging
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .config import CONFIG
from .logui import ConsoleUI
from .utils import sanitize_filename

__all__ = [
    "run_mkv_match",
    "normalize_mkv_match_naming",
    "call_hook_if_configured",
]


def _make_unique(dst: Path) -> Path:
    """Erzeugt einen eindeutigen Dateinamen, falls `dst` schon existiert."""
    if not dst.exists():
        return dst
    stem, ext = dst.stem, dst.suffix
    i = 1
    while True:
        cand = dst.with_name(f"{stem} ({i}){ext}")
        if not cand.exists():
            return cand
        i += 1


def run_mkv_match(
    show_dir: Path,
    season_no: Optional[int],
    series_name: Optional[str],
    log: logging.Logger,
    ui: Optional[ConsoleUI] = None,
) -> bool:
    """
    Führt den externen `mkv-match`-Prozess aus, wenn vorhanden.
    Rückgabe: True bei (versuchtem) Erfolg, False bei hartem Fehler.

    Nutzt folgende CONFIG-Pfade:
      CONFIG["HOOKS"]["MKV_MATCH"] = {
          "ENABLED": True|False,
          "BINARY": "mkv-match",
          "EXTRA_ARGS": [...],
          "RENAME_TO_SCHEMA": True|False,
      }
      CONFIG["TMDB"]["API_KEY"]
    """
    hk = CONFIG.get("HOOKS", {}).get("MKV_MATCH", {})
    if not hk or not hk.get("ENABLED", False):
        return False

    bin_name = hk.get("BINARY", "mkv-match")
    # Prüfen, ob das Binary verfügbar ist (voller Pfad oder im PATH)
    resolved = shutil.which(bin_name) or bin_name
    if not shutil.which(resolved) and not Path(resolved).exists():
        log.info("mkv-match nicht gefunden (nicht im PATH) – Hook wird übersprungen.")
        return False

    args = [resolved, "--show-dir", str(show_dir)]
    if season_no is not None:
        args += ["--season", str(season_no)]
    api = CONFIG.get("TMDB", {}).get("API_KEY") or ""
    if api:
        args += ["--tmdb-api-key", api]
    extra = hk.get("EXTRA_ARGS", []) or []
    args.extend(extra)

    if ui is None:
        ui = ConsoleUI(True)

    log.info(f"[HOOK] mkv-match: {' '.join(shlex.quote(x) for x in args)}")
    if CONFIG.get("BEHAVIOR", {}).get("DRY_RUN", False):
        log.info("[DRY-RUN] mkv-match nicht ausgeführt.")
        return True

    try:
        with subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        ) as proc:
            for line in proc.stdout or []:
                s = line.rstrip("\r\n")
                ui.spin(f"mkv-match: {show_dir.name}")
                log.debug(f"mkv-match | {s}")
            rc = proc.wait()
        ui.done()
        if rc != 0:
            log.warning(f"mkv-match Returncode {rc} – evtl. kein Match/Teilerfolg.")
            return False
        return True
    except FileNotFoundError:
        ui.done()
        log.info("mkv-match nicht gefunden – Hook wird übersprungen.")
        return False
    except Exception as e:
        ui.done()
        log.exception(f"mkv-match Fehler: {e}")
        return False


def normalize_mkv_match_naming(
    show_dir: Path,
    series_base: Optional[str],
    season_no: Optional[int],
    log: logging.Logger,
) -> None:
    """
    Benennt Dateien in `show_dir` in das Schema
      'Serienname – SxxExx - Episodentitel.mkv' um, sofern passende
    S/E-Muster im Dateinamen enthalten sind.

    Hinweise:
    - Lässt Staffel-Mismatch (s != season_no) bewusst durch, um Mehr-Staffel-
      Discs nicht hart zu blockieren. Bei Bedarf hier auf strikte Gleichheit prüfen.
    - Doppelfolgen 'SxxEyy-Ezz' werden zusammengefasst.
    """
    base = series_base or show_dir.parent.name
    # Serienname ggf. "gesäubert" (Jahreszahlen/Tags darf dein Namings-Modul übernehmen).
    series_name = sanitize_filename(base)

    pat = re.compile(r"(?i)\bS(\d{1,2})E(\d{2})(?:[-_ ]?E(\d{2}))?\b")

    any_renamed = False
    for f in sorted(show_dir.glob("*.mkv")):
        m = pat.search(f.name)
        if not m:
            continue

        s = int(m.group(1))
        e1 = int(m.group(2))
        e2 = m.group(3)
        # Titelteil = Rest ohne S/E-Tag, aufräumen
        title = pat.sub("", f.stem)
        title = re.sub(r"^[\s\-_.]+|[\s\-_.]+$", "", title)
        title = title.replace("_", " ").replace(".", " ")
        title = re.sub(r"\s+", " ", title).strip()
        title = sanitize_filename(title) if title else None

        # Optional, falls zwingend gleiche Staffel gewünscht:
        # if season_no is not None and s != season_no:
        #     continue

        if e2:
            new_stem = f"{series_name} – S{s:02d}E{e1:02d}-E{int(e2):02d}"
        else:
            new_stem = f"{series_name} – S{s:02d}E{e1:02d}"
        if title:
            new_stem += f" - {title}"

        dst = f.with_name(new_stem + f.suffix)
        dst = _make_unique(dst)

        if CONFIG.get("BEHAVIOR", {}).get("DRY_RUN", False):
            log.info(f"[DRY-RUN] Rename: {f.name} -> {dst.name}")
        else:
            try:
                f.rename(dst)
                log.info(f"Rename: {f.name} -> {dst.name}")
                any_renamed = True
            except Exception as e:
                log.warning(f"Rename fehlgeschlagen für {f.name}: {e}")

    if not any_renamed:
        log.info("mkv-match-Normalisierung: Keine passenden S/E-Muster gefunden – nichts umbenannt.")


def call_hook_if_configured(
    show_dir: Path,
    season_no: Optional[int],
    series_name: Optional[str],
    log: logging.Logger,
    ui: Optional[ConsoleUI] = None,
) -> None:
    """
    Bequemer Wrapper:
    - prüft CONFIG["HOOKS"]["MKV_MATCH"]["ENABLED"]
    - ruft `run_mkv_match(...)` auf
    - wendet optional `normalize_mkv_match_naming(...)` an, wenn
      CONFIG["HOOKS"]["MKV_MATCH"]["RENAME_TO_SCHEMA"] True ist.
    """
    hk = CONFIG.get("HOOKS", {}).get("MKV_MATCH", {})
    if not hk or not hk.get("ENABLED", False):
        return

    ok = run_mkv_match(show_dir, season_no, series_name, log, ui)
    if ok and hk.get("RENAME_TO_SCHEMA", False):
        normalize_mkv_match_naming(show_dir, series_name, season_no, log)
