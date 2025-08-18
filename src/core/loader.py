# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Tuple, List
import yaml
from datetime import datetime


# ---------- kleine Utilities ----------

def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d-%H-%M")


def _mk_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------- Konfiguration laden ----------

def load_config(cfg_path: Path) -> Dict:
    """
    Lädt config/config.yaml und gibt ein dict mit bereits auf Paths gemappten Pfaden zurück.
    Erwartete Struktur siehe dein Beispiel.
    """
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config nicht gefunden: {cfg_path}")

    with cfg_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    # Defaults robust anwenden
    app = raw.get("app", {})
    paths = raw.get("paths", {})
    tmdb = raw.get("tmdb", {})

    # Basis/absolute Pfade herstellen (UNC/Windows okay)
    base_root = Path(paths.get("base_root", "."))
    transcode_dir = Path(paths.get("transcode_dir", base_root / "transcode"))
    remux_dir = Path(paths.get("remux_dir", base_root / "remux"))
    logs_dir = Path(paths.get("logs_dir", base_root / "logs"))

    cfg: Dict = {
        "app": {
            "log_level": str(app.get("log_level", "INFO")).upper(),
            "dry_run": bool(app.get("dry_run", True)),
        },
        "paths": {
            "base_root": base_root,
            "transcode_dir": transcode_dir,
            "remux_dir": remux_dir,
            "logs_dir": _mk_dir(logs_dir),
        },
        "tmdb": {
            "enabled": bool(tmdb.get("enabled", False)),
            "language": tmdb.get("language", "de-DE"),
            "timeout_seconds": int(tmdb.get("timeout_seconds", 8)),
        },
        "probe": raw.get("probe", {}),
        "behavior": raw.get("behavior", {}),
        "makemkv": raw.get("makemkv", {}),
        "hooks": raw.get("hooks", {}),
    }
    return cfg


# ---------- Logger ----------

def setup_phase_logger(phase: str, logs_dir: Path, timestamp: str | None = None) -> Tuple[logging.Logger, Path]:
    """
    Erstellt einen Logger für eine Phase (AUSLESEN / REMUX / RENAME).
    Format wie in deinen Beispielen: "… | AUSLESEN | …"
    """
    ts = timestamp or now_stamp()
    log_path = logs_dir / f"{ts}_{phase.lower()}.txt"

    logger = logging.getLogger(f"phase.{phase}")
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(f"%(asctime)s | %(levelname)-8s | {phase} | %(message)s", "%Y-%m-%d %H:%M:%S")

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(sh)

    return logger, log_path


def write_pipeline_index(logs_dir: Path, timestamp: str, phase_files: List[Tuple[str, Path]]) -> Path:
    """
    Schreibt eine kleine Übersichtsdatei, die auf die einzelnen Phasen-Logs verweist.
    """
    index_path = logs_dir / f"{timestamp}_pipeline.txt"
    lines = ["# Pipeline-Logs", ""]
    for phase, p in phase_files:
        lines.append(f"- {phase}: {p}")
    index_path.write_text("\n".join(lines), encoding="utf-8")
    return index_path
