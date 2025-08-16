# makemkv.py
from __future__ import annotations

import logging
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple


def find_makemkvcon(log: logging.Logger) -> Optional[str]:
    """
    Sucht die MakeMKV-CLI (bevorzugt 64-bit).
    """
    win_paths = [
        r"C:\Program Files (x86)\MakeMKV\makemkvcon64.exe",
        r"C:\Program Files\MakeMKV\makemkvcon64.exe",
        r"C:\Program Files (x86)\MakeMKV\makemkvcon.exe",
        r"C:\Program Files\MakeMKV\makemkvcon.exe",
    ]
    for p in win_paths:
        if Path(p).exists():
            log.info(f"MakeMKV gefunden: {p}")
            return p
    # Linux / PATH
    p = shutil.which("makemkvcon") or "makemkvcon"
    if shutil.which(p) or Path(p).exists():
        log.info(f"MakeMKV gefunden: {p}")
        return p

    log.warning("MakeMKV-CLI nicht gefunden. Pfad prüfen.")
    return None


def _resolve_disc_folder(src: Path) -> Path:
    """
    Nimmt einen beliebigen Pfad (Datei oder Ordner) entgegen und liefert einen
    Pfad zurück, der für makemkvcon 'file:' gültig ist.

    Fälle:
      - …\BDMV  -> bleibt BDMV
      - …\VIDEO_TS -> bleibt VIDEO_TS
      - …\DiscOrdner\BDMV / VIDEO_TS -> wechsle in den jeweiligen Unterordner
      - …\IrgendeineDatei (z.B. DSNS1D5 ohne Endung) -> gehe zum Elternordner
        und suche dort BDMV/VIDEO_TS
      - …\DiscOrdner mit index.bdmv / VIDEO_TS.IFO im Ordner -> nutze diesen Ordner
    """
    p = src

    # Wenn Datei (kein ISO): erst zum Elternordner
    if p.is_file() and p.suffix.lower() != ".iso":
        p = p.parent

    # Bereits auf dem Unterordner?
    name = p.name.upper()
    if name == "BDMV" or name == "VIDEO_TS":
        return p

    # Enthält der Ordner direkt Disc-Struktur?
    if (p / "BDMV").is_dir():
        return p / "BDMV"
    if (p / "VIDEO_TS").is_dir():
        return p / "VIDEO_TS"

    # Manche Rips haben index.bdmv / VIDEO_TS.IFO direkt im Ordner
    if (p / "index.bdmv").exists():
        return p
    if (p / "VIDEO_TS.IFO").exists():
        return p

    # Ein Level höher probieren (falls z.B. …\BDMV\STREAM übergeben wurde)
    parent = p.parent
    if parent and parent.is_dir():
        if parent.name.upper() in ("BDMV", "VIDEO_TS"):
            return parent
        if (parent / "BDMV").is_dir():
            return parent / "BDMV"
        if (parent / "VIDEO_TS").is_dir():
            return parent / "VIDEO_TS"

    return p  # Fallback: unverändert zurückgeben


def _build_input_spec(source_kind: str, source_path: Path, log: logging.Logger) -> Tuple[str, Path]:
    """
    Baut (kind, path) für makemkvcon auf. Korrigiert ungünstige Eingaben:
    - Wenn 'file:' aber Ordner ist Disc-Root ohne BDMV/VIDEO_TS -> in Unterordner wechseln
    - Wenn 'file:' aber eine "komische" Datei (z.B. ohne Endung) -> Elternordner prüfen
    - Wenn .iso-Datei -> 'iso:' verwenden
    """
    kind = source_kind
    p = source_path

    # ISO-Datei?
    if p.is_file() and p.suffix.lower() == ".iso":
        return "iso", p

    if kind != "iso":
        resolved = _resolve_disc_folder(p)
        if resolved != p:
            try:
                log.debug(f"Quellpfad angepasst: {p} -> {resolved}")
            except Exception:
                pass
        return "file", resolved

    return "iso", p


def run_makemkv(
    makemkv: str,
    source_kind: str,
    source_path: Path,
    out_dir: Path,
    log: logging.Logger,
    ui=None,
    extra_opts: Optional[list] = None,
) -> bool:
    """
    Führt makemkvcon aus. Akzeptiert 'source_kind' = 'iso' oder 'file'.
    Korrigiert typische Eingabefehler (Ordner auf Disc-Root statt BDMV/VIDEO_TS, Dateien ohne Endung, …).
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    kind, resolved_src = _build_input_spec(source_kind, source_path, log)

    # Standard: --robot (kann bei Bedarf erweitert werden)
    opts = list(extra_opts) if extra_opts else ["--robot"]
    input_spec = f"{kind}:{str(resolved_src)}"
    cmd = [makemkv, "mkv"] + opts + [input_spec, "all", str(out_dir)]

    log.info(f"MakeMKV: {' '.join(shlex.quote(x) for x in cmd)}")

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
            for line in proc.stdout or []:
                if ui is not None:
                    try:
                        ui.spin(f"Remux läuft: {resolved_src.name}")
                    except Exception:
                        pass
                log.debug(line.rstrip("\r\n"))
            rc = proc.wait()

        if rc != 0:
            # 10 wird von MakeMKV oft als "fatal error" / Quelle ungültig gemeldet
            if rc == 10:
                log.error(
                    "MakeMKV Returncode 10 – Prüfe bitte, ob auf einen gültigen Disc-Ordner "
                    "(BDMV/VIDEO_TS) oder eine .iso-Datei verwiesen wird."
                )
            else:
                log.error(f"MakeMKV Returncode {rc} – Quelle: {resolved_src}")
            return False

        return True
    except FileNotFoundError:
        log.error("makemkvcon nicht gefunden/ausführbar – Pfad prüfen.")
        return False
    except Exception as e:
        log.exception(f"Fehler beim MakeMKV-Aufruf: {e}")
        return False
