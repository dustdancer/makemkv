# -*- coding: utf-8 -*-
"""
Loader + Logger-Setup
- YAML laden und in einfache Objekte mit Attributzugriff mappen
- Stage-Logger (AUSLESEN | REMUX | RENAME) + Pipeline-Log
"""

from __future__ import annotations
import logging
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timedelta
import yaml


def _to_namespace(d):
    if isinstance(d, dict):
        return SimpleNamespace(**{k: _to_namespace(v) for k, v in d.items()})
    if isinstance(d, list):
        return [ _to_namespace(x) for x in d ]
    return d


def _coerce_paths(cfg_ns):
    # Pfade in Path konvertieren
    cfg_ns.paths.base_root   = Path(cfg_ns.paths.base_root)
    cfg_ns.paths.transcode_dir = Path(cfg_ns.paths.transcode_dir)
    cfg_ns.paths.remux_dir   = Path(cfg_ns.paths.remux_dir)
    cfg_ns.paths.logs_dir    = Path(cfg_ns.paths.logs_dir)
    # MakeMKV Listen sicherstellen
    if not isinstance(cfg_ns.makemkv.win_paths, list):
        cfg_ns.makemkv.win_paths = [str(cfg_ns.makemkv.win_paths)]
    if not isinstance(cfg_ns.makemkv.extra_opts, list):
        cfg_ns.makemkv.extra_opts = [str(cfg_ns.makemkv.extra_opts)]
    return cfg_ns


def load_config() -> SimpleNamespace:
    # config/config.yaml relativ zu Projektwurzel
    here = Path(__file__).resolve()
    cfg_path = here.parents[2] / "config" / "config.yaml"
    if not cfg_path.exists():
        raise FileNotFoundError(f"Konfigurationsdatei nicht gefunden: {cfg_path}")

    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8", errors="replace"))
    cfg = _to_namespace(data)

    # Defaults absichern
    if not hasattr(cfg, "behavior"):
        cfg.behavior = SimpleNamespace()
    if not hasattr(cfg.behavior, "delete_originals"):
        cfg.behavior.delete_originals = False

    # TMDb enabled ableiten, wenn Key gesetzt (falls in YAML disabled)
    if hasattr(cfg, "tmdb"):
        if getattr(cfg.tmdb, "enabled", False) and not getattr(cfg.tmdb, "timeout_seconds", None):
            cfg.tmdb.timeout_seconds = 8
        if not getattr(cfg.tmdb, "enabled", False):
            # falls jemand API-Key gesetzt hat, trotzdem enabled lassen? Wir respektieren das YAML-Feld.
            pass

    cfg = _coerce_paths(cfg)

    # Log-Level normalisieren
    lvl = str(getattr(cfg.app, "log_level", "INFO")).upper()
    if lvl not in ("DEBUG", "INFO", "WARNING", "ERROR"):
        lvl = "INFO"
    cfg.app.log_level = lvl

    return cfg


class _StageFilter(logging.Filter):
    def __init__(self, stage: str):
        super().__init__()
        self.stage = stage

    def filter(self, record: logging.LogRecord) -> bool:
        record.stage = self.stage
        return True


def _make_logger(name: str, stage: str, file_path: Path, level: int, pipeline_handler: logging.Handler) -> logging.Logger:
    lg = logging.getLogger(stage)  # bewusst: Stage als Name
    lg.handlers.clear()
    lg.setLevel(level)

    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(stage)s | %(message)s", "%Y-%m-%d %H:%M:%S")

    fh = logging.FileHandler(file_path, encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(fmt)
    fh.addFilter(_StageFilter(stage))

    sh = logging.StreamHandler()
    sh.setLevel(level)
    sh.setFormatter(fmt)
    sh.addFilter(_StageFilter(stage))

    pipeline_handler.addFilter(_StageFilter(stage))

    lg.addHandler(fh)
    lg.addHandler(sh)
    lg.addHandler(pipeline_handler)

    return lg


def setup_stage_loggers(logs_dir: Path, log_level: str = "INFO"):
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d-%H-%M")

    auslesen_path = logs_dir / f"{ts}_auslesen.txt"
    remux_path    = logs_dir / f"{ts}_remux.txt"
    rename_path   = logs_dir / f"{ts}_rename.txt"
    pipeline_path = logs_dir / f"{ts}_pipeline.txt"

    level = getattr(logging, (log_level or "INFO").upper(), logging.INFO)

    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(stage)s | %(message)s", "%Y-%m-%d %H:%M:%S")
    pipeline_handler = logging.FileHandler(pipeline_path, encoding="utf-8")
    pipeline_handler.setLevel(level)
    pipeline_handler.setFormatter(fmt)

    auslesen = _make_logger("auslesen", "AUSLESEN", auslesen_path, level, pipeline_handler)
    remux    = _make_logger("remux",    "REMUX",    remux_path,    level, pipeline_handler)
    rename   = _make_logger("rename",   "RENAME",   rename_path,   level, pipeline_handler)

    # Logrotation (einfach: alte *.txt > retention löschen)
    keep_days =  int(14)
    for f in logs_dir.glob("*.txt"):
        try:
            age = datetime.now() - datetime.fromtimestamp(f.stat().st_mtime)
            if age > timedelta(days=keep_days):
                f.unlink(missing_ok=True)
        except Exception:
            pass

    return auslesen, remux, rename, pipeline_path
