# file: makemkv/makemkv.py
from __future__ import annotations

"""
Wrapper um MakeMKV (CLI) mit robuster Ausgabe-Analyse und Progress-Anzeige.

Features
- Sucht die ausführbare makemkvcon (Windows/Linux)
- Startet Remux (ISO / BDMV / VIDEO_TS) in ein Zielverzeichnis
- Fortschritt:
  * PRGV-Linien (MakeMKV Robot) → Prozentbalken
  * Tracks-Anzeige: "Tracks: <übrig>/<gesamt>"
    - Gesamtzahl aus MSG:5014 ("<N> Titel werden ... gespeichert")
    - Done/Current: anhand der bereits erzeugten *.mkv im Ausgabeverzeichnis
  * Discs danach: vom Aufrufer übergeben
- Stabile Dekodierung der MakeMKV-Ausgabe (verhindert cp1252/UnicodeDecodeError)
- Ausführliches Logging (jede Zeile als DEBUG)
"""

import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from .config import CONFIG
from .logui import ConsoleUI

__all__ = ["find_makemkvcon", "run_makemkv"]


# ---------------------------------------------------------------------------
# Find makemkvcon
# ---------------------------------------------------------------------------

def find_makemkvcon(log) -> Optional[str]:
    """Findet die makemkvcon-Binary gemäß CONFIG (Windows bevorzugt 64-bit)."""
    if os.name == "nt":
        for p in CONFIG["MAKEMKV"]["WIN_PATHS"]:
            if Path(p).exists():
                log.info(f"MakeMKV gefunden: {p}")
                return p
        log.warning("MakeMKV-CLI nicht gefunden (Windows). Pfade in CONFIG['MAKEMKV']['WIN_PATHS'] prüfen.")
        return None

    # Linux / macOS
    candidate = shutil.which(CONFIG["MAKEMKV"]["LINUX_PATH"]) or CONFIG["MAKEMKV"]["LINUX_PATH"]
    if shutil.which(candidate) or Path(candidate).exists():
        log.info(f"MakeMKV gefunden: {candidate}")
        return candidate

    log.warning("makemkvcon nicht im PATH. CONFIG['MAKEMKV']['LINUX_PATH'] prüfen.")
    return None


# ---------------------------------------------------------------------------
# Helpers für Parsing & Input-Bau
# ---------------------------------------------------------------------------

def _parse_prgv(line: str) -> Optional[Tuple[int, int]]:
    """
    Parst MakeMKV Robot-Progress-Zeilen: PRGV:<job>,<cur>,<total>
    → gibt (cur, total) zurück.
    """
    if not line.startswith("PRGV:"):
        return None
    try:
        parts = line.strip().split(":")[1].split(",")
        if len(parts) >= 3:
            cur = int(parts[1])
            total = int(parts[2])
            if total > 0:
                return cur, total
    except Exception:
        pass
    return None


def _parse_msg_5014_total_tracks(line: str) -> Optional[int]:
    """
    Extrahiert aus einer MSG:5014-Zeile die Anzahl der zu speichernden Titel (Tracks).
    Beispiel (deutsche UI):
      MSG:5014,...,"5 Titel werden in Verzeichnis file://...", ... ,"5","file://..."
    Heuristik: erste in Anführungszeichen stehende reine Zahl oder die vorletzte Zahl.
    """
    if "MSG:5014" not in line:
        return None
    # 1) schnelle Variante: erste "Zahl" in Anführungszeichen
    m = re.search(r'\"(\d{1,3})\"', line)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    # 2) robustere Fallback-Suche: alle Zahlen, nimm die größte sinnvolle
    nums = [int(n) for n in re.findall(r'\"(\d{1,3})\"', line)]
    return max(nums) if nums else None


def _build_input_spec(source_kind: str, source_path: Path) -> str:
    """
    MakeMKV Eingabe-Spezifikation:
      - ISO:  iso:<pfad-zur-iso>
      - Ordner: file:<pfad-zum-BDMV-oder-VIDEO_TS-Ordner>
    """
    kind = source_kind.lower().strip()
    if kind == "iso":
        return f"iso:{str(source_path)}"
    return f"file:{str(source_path)}"


def _count_mkvs(dir_: Path) -> int:
    try:
        return sum(1 for _ in dir_.glob("*.mkv"))
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_makemkv(
    makemkv_bin: str,
    source_kind: str,
    source_path: Path,
    out_dir: Path,
    *,
    log,
    ui: Optional[ConsoleUI] = None,
    discs_remaining: Optional[int] = None,
) -> bool:
    """
    Startet MakeMKV und zeigt Fortschritt/Tracks/Discs in der Konsole.
    Gibt True bei Erfolg zurück, sonst False.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if ui is None:
        ui = ConsoleUI(True)

    extra = CONFIG["MAKEMKV"]["EXTRA_OPTS"] or []
    input_spec = _build_input_spec(source_kind, source_path)
    cmd = [makemkv_bin, "mkv", *extra, input_spec, "all", str(out_dir)]

    # Für Windows sicher dekodieren (verhindert UnicodeDecodeError in cp1252)
    enc = "mbcs" if os.name == "nt" else "utf-8"

    log.info(f"MakeMKV: {' '.join(shlex.quote(x) for x in cmd)}")

    if CONFIG["BEHAVIOR"].get("DRY_RUN", False):
        log.info("[DRY-RUN] MakeMKV nicht ausgeführt.")
        return True

    tracks_total: Optional[int] = None
    # 'tracks_current' interpretieren wir als (bereits gesichert + 1),
    # damit die Anzeige "übrig/gesamt" sinnvoll ist.
    tracks_current: Optional[int] = None

    try:
        with subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding=enc,
            errors="replace",
            bufsize=1,
        ) as proc:
            cur = 0
            total = 0
            while True:
                line = proc.stdout.readline() if proc.stdout is not None else ""
                if not line and proc.poll() is not None:
                    break

                s = line.rstrip("\r\n")
                if s:
                    log.debug(s)

                    # Anzahl der zu speichernden Titel erkennen
                    if tracks_total is None:
                        maybe_total = _parse_msg_5014_total_tracks(s)
                        if maybe_total:
                            tracks_total = maybe_total

                    # PRGV verarbeiten
                    pr = _parse_prgv(s)
                    if pr:
                        cur, total = pr

                # Tracks-Done anhand der bereits erzeugten MKVs schätzen
                done = _count_mkvs(out_dir)
                if tracks_total and done >= 0:
                    # +1, weil "current" als die gerade laufende Speicherung verstanden wird
                    tracks_current = min(tracks_total, (done + 1)) if proc.poll() is None else min(tracks_total, done)

                # Fortschritt anzeigen
                if total > 0:
                    ui.bar(
                        f"Remux: {source_path.name}",
                        cur,
                        total,
                        tracks_current=tracks_current,
                        tracks_total=tracks_total,
                        discs_remaining=discs_remaining,
                    )
                else:
                    # Kein PRGV → Spinner + Extras
                    ui.spin(
                        f"Remux läuft: {source_path.name}",
                        discs_remaining=discs_remaining,
                    )

            rc = proc.wait()
        ui.done()

        if rc != 0:
            log.error(f"MakeMKV Returncode {rc} – Quelle: {source_path}")
            return False

        return True

    except Exception as e:
        ui.done()
        log.exception(f"Fehler beim MakeMKV-Aufruf: {e}")
        return False
