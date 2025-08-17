# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from config import CONFIG

# Optional: Wenn du eine Konsolen-Progress-UI hast, wird sie genutzt.
try:
    from logui import ConsoleUI  # type: ignore
except Exception:  # Fallback wenn nicht vorhanden
    ConsoleUI = None  # type: ignore


def find_makemkvcon(log: logging.Logger) -> Optional[str]:
    """Sucht die makemkvcon Binary gemäß CONFIG."""
    if Path("/").anchor:  # immer True, nur um mypy zu beruhigen
        pass
    # Windows
    if CONFIG.get("MAKEMKV", {}).get("WIN_PATHS"):
        for p in CONFIG["MAKEMKV"]["WIN_PATHS"]:
            if Path(p).exists():
                log.info(f"MakeMKV gefunden: {p}")
                return p
    # Linux / PATH
    cand = shutil.which(CONFIG["MAKEMKV"].get("LINUX_PATH", "makemkvcon")) or CONFIG["MAKEMKV"].get("LINUX_PATH", "makemkvcon")
    if shutil.which(cand) or Path(cand).exists():
        log.info(f"MakeMKV gefunden: {cand}")
        return cand
    log.warning("MakeMKV CLI nicht gefunden. Prüfe CONFIG['MAKEMKV'].")
    return None


def _parse_prgv(line: str) -> Optional[Tuple[int, int]]:
    """
    Parst Robot-Progress von makemkvcon: 'PRGV:job,cur,total'.
    Gibt (cur, total) zurück oder None.
    """
    if not line.startswith("PRGV:"):
        return None
    try:
        parts = line.strip().split(":")[1].split(",")
        if len(parts) >= 3:
            cur = int(parts[1]); total = int(parts[2])
            if total > 0:
                return cur, total
    except Exception:
        pass
    return None


def _build_input_spec(source_kind: str, source_path: Path, log: logging.Logger) -> str:
    """
    Erzeugt die Input-Spezifikation für makemkvcon und normalisiert
    bei Disc-Ordnern auf die erwarteten Dateien:
      - DVD:  VIDEO_TS/VIDEO_TS.IFO
      - BD:   BDMV/index.bdmv

    Hintergrund: Wird nur der Disc-Root-Ordner übergeben, liefert makemkvcon
    häufig Returncode 10 (ungültige Quelle). Siehe Diskussion im MakeMKV-Forum.
    """
    p = source_path

    if source_kind == "iso":
        return f"iso:{str(p)}"

    # kind == "file" (Ordner oder Datei)
    if p.is_dir():
        # DVD?
        dvd_ifo = p / "VIDEO_TS" / "VIDEO_TS.IFO"
        if p.name.upper() == "VIDEO_TS":
            dvd_ifo = p / "VIDEO_TS.IFO"
        if dvd_ifo.exists():
            log.debug(f"DVD-Ordner erkannt, nutze IFO: {dvd_ifo}")
            return f"file:{str(dvd_ifo)}"

        # Blu-ray?
        bd_index = p / "BDMV" / "index.bdmv"
        if p.name.upper() == "BDMV":
            bd_index = p / "index.bdmv"
        if bd_index.exists():
            log.debug(f"BD-Ordner erkannt, nutze index.bdmv: {bd_index}")
            return f"file:{str(bd_index)}"

        # Fallback: direkt den Ordner übergeben (kann funktionieren, ist aber unsicher)
        log.debug(f"Disc-Dateien nicht gefunden – übergebe Ordner direkt: {p}")
        return f"file:{str(p)}"

    # Einzeldatei (z.B. bereits IFO oder index.bdmv oder eine Containerdatei)
    return f"file:{str(p)}"


def run_makemkv(
    makemkv: str,
    source_kind: str,
    source_path: Path,
    out_dir: Path,
    log: logging.Logger,
    ui: Optional["ConsoleUI"] = None,
) -> bool:
    """
    Führt den eigentlichen Remux-Aufruf aus. Nutzt _build_input_spec(), um
    Returncode-10-Fälle (falscher Pfad) zu vermeiden.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    extra = CONFIG["MAKEMKV"].get("EXTRA_OPTS", []) or []
    input_spec = _build_input_spec(source_kind, source_path, log)

    cmd = [makemkv, "mkv"] + extra + [input_spec, "all", str(out_dir)]
    log.info(f"MakeMKV: {' '.join(shlex.quote(x) for x in cmd)}")

    # Dry-Run?
    if CONFIG.get("BEHAVIOR", {}).get("DRY_RUN", False):
        log.info("[DRY-RUN] MakeMKV nicht ausgeführt.")
        return True

    try:
        with subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        ) as proc:
            cur = 0
            total = 0
            for line in proc.stdout or []:
                s = line.rstrip("\r\n")
                log.debug(s)
                pr = _parse_prgv(s)
                if pr and ui is not None:
                    cur, total = pr
                    # Fortschritt anzeigen (falls UI vorhanden)
                    try:
                        ui.bar(f"Remux: {source_path.name}", cur, total)
                    except Exception:
                        pass
            rc = proc.wait()

        if ui is not None:
            try:
                ui.done()
            except Exception:
                pass

        if rc != 0:
            if rc == 10:
                log.error(
                    "MakeMKV Returncode 10 – Quelle nicht gültig. "
                    "Bei DVD bitte 'VIDEO_TS/VIDEO_TS.IFO', bei Blu-ray 'BDMV/index.bdmv' übergeben."
                )
            else:
                log.error(f"MakeMKV Returncode {rc} – Quelle: {source_path}")
            return False

        return True

    except Exception as e:
        if ui is not None:
            try:
                ui.done()
            except Exception:
                pass
        log.exception(f"Fehler beim MakeMKV-Aufruf: {e}")
        return False
