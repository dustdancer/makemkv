# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import yaml

# --------- Datamodel ---------

@dataclass
class AppCfg:
    log_level: str = "INFO"
    dry_run: bool = True

@dataclass
class PathsCfg:
    base_root: Path = Path(".")
    transcode_dir: Path = Path("./transcode")
    remux_dir: Path = Path("./remux")
    logs_dir: Path = Path("./logs")

@dataclass
class MakeMKVCfg:
    win_paths: list[str] = None
    linux_path: str = "makemkvcon"
    extra_opts: list[str] = None

@dataclass
class BehaviorCfg:
    delete_originals: bool = False
    minlength_seconds: int = 300
    trailer_max_seconds: int = 240
    episode_min_seconds: int = 1080
    episode_max_seconds: int = 3900
    log_retention_days: int = 14

@dataclass
class TMDbCfg:
    enabled: bool = False
    language: str = "de-DE"
    timeout_seconds: int = 8

@dataclass
class ProbeCfg:
    prefer_ffprobe: bool = True
    ffprobe_path: str = "ffprobe"
    mediainfo_path: str = "mediainfo"

@dataclass
class HooksCfg:
    mkv_match_enabled: bool = False
    mkv_match_binary: str = "mkv-match"
    mkv_match_extra_args: list[str] = None
    mkv_match_rename_to_schema: bool = True

@dataclass
class Config:
    app: AppCfg
    paths: PathsCfg
    makemkv: MakeMKVCfg
    behavior: BehaviorCfg
    tmdb: TMDbCfg
    probe: ProbeCfg
    hooks: HooksCfg

# --------- Loader ---------

def _as_path(v: str | Path) -> Path:
    return v if isinstance(v, Path) else Path(v)

def load_config(path: str | Path = "config/config.yaml") -> Config:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    # app
    app_raw = raw.get("app", {}) or {}
    app = AppCfg(
        log_level=str(app_raw.get("log_level", "INFO")).upper(),
        dry_run=bool(app_raw.get("dry_run", True)),
    )

    # paths
    p_raw = raw.get("paths", {}) or {}
    paths = PathsCfg(
        base_root=_as_path(p_raw.get("base_root", ".")),
        transcode_dir=_as_path(p_raw.get("transcode_dir", "./transcode")),
        remux_dir=_as_path(p_raw.get("remux_dir", "./remux")),
        logs_dir=_as_path(p_raw.get("logs_dir", "./logs")),
    )

    # makemkv
    mk_raw = raw.get("makemkv", {}) or {}
    mk = MakeMKVCfg(
        win_paths=list(mk_raw.get("win_paths", [])),
        linux_path=str(mk_raw.get("linux_path", "makemkvcon")),
        extra_opts=list(mk_raw.get("extra_opts", []) or []),
    )

    # behavior
    b_raw = raw.get("behavior", {}) or {}
    behavior = BehaviorCfg(
        delete_originals=bool(b_raw.get("delete_originals", False)),
        minlength_seconds=int(b_raw.get("minlength_seconds", 300)),
        trailer_max_seconds=int(b_raw.get("trailer_max_seconds", 240)),
        episode_min_seconds=int(b_raw.get("episode_min_seconds", 1080)),
        episode_max_seconds=int(b_raw.get("episode_max_seconds", 3900)),
        log_retention_days=int(b_raw.get("log_retention_days", 14)),
    )

    # tmdb
    t_raw = raw.get("tmdb", {}) or {}
    tmdb = TMDbCfg(
        enabled=bool(t_raw.get("enabled", False)),
        language=str(t_raw.get("language", "de-DE")),
        timeout_seconds=int(t_raw.get("timeout_seconds", 8)),
    )

    # probe
    pr_raw = raw.get("probe", {}) or {}
    probe = ProbeCfg(
        prefer_ffprobe=bool(pr_raw.get("prefer_ffprobe", True)),
        ffprobe_path=str(pr_raw.get("ffprobe_path", "ffprobe")),
        mediainfo_path=str(pr_raw.get("mediainfo_path", "mediainfo")),
    )

    # hooks
    hk_raw = raw.get("hooks", {}) or {}
    mm_raw = hk_raw.get("mkv_match", {}) or {}
    hooks = HooksCfg(
        mkv_match_enabled=bool(mm_raw.get("enabled", False)),
        mkv_match_binary=str(mm_raw.get("binary", "mkv-match")),
        mkv_match_extra_args=list(mm_raw.get("extra_args", []) or []),
        mkv_match_rename_to_schema=bool(mm_raw.get("rename_to_schema", True)),
    )

    return Config(
        app=app,
        paths=paths,
        makemkv=mk,
        behavior=behavior,
        tmdb=tmdb,
        probe=probe,
        hooks=hooks,
    )
