# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field, ConfigDict, field_validator


class Paths(BaseModel):
    model_config = ConfigDict(extra="ignore")

    base_root: Path
    transcode_dir: Path
    remux_dir: Path
    logs_dir: Path

    @field_validator("base_root", "transcode_dir", "remux_dir", "logs_dir", mode="before")
    @classmethod
    def _to_path(cls, v):
        # akzeptiert str/Path, expanduser & resolve (soweit sinnvoll)
        p = Path(str(v)).expanduser()
        return p

class MakeMKV(BaseModel):
    model_config = ConfigDict(extra="ignore")

    win_paths: List[str] = Field(default_factory=list)
    linux_path: str = "makemkvcon"
    extra_opts: List[str] = Field(default_factory=lambda: ["--robot"])


class Probe(BaseModel):
    model_config = ConfigDict(extra="ignore")

    prefer_ffprobe: bool = True
    ffprobe_path: str = "ffprobe"
    mediainfo_path: str = "mediainfo"


class Behavior(BaseModel):
    model_config = ConfigDict(extra="ignore")

    delete_originals: bool = False
    dry_run: bool = True
    log_retention_days: int = 14
    trailer_max: int = 240
    episode_min: int = 18 * 60
    episode_max: int = 65 * 60
    tiny_file_bytes: int = 100 * 1024 * 1024
    episode_tolerance: float = 0.15
    double_ep_tol: float = 0.12
    playall_mult_tol_min: int = 240
    playall_mult_tol_max: int = 480
    playall_factor_min: float = 3.0
    playall_factor_soft: float = 2.7
    size_tolerance: float = 0.22


class TMDb(BaseModel):
    model_config = ConfigDict(extra="ignore")

    api_key: str = ""
    lang: str = "de-DE"
    timeout: int = 8
    enabled: bool = True


class MkvMatchHook(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    binary: str = "mkv-match"
    extra_args: List[str] = Field(default_factory=list)
    rename_to_schema: bool = True


class Hooks(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mkv_match: MkvMatchHook = Field(default_factory=MkvMatchHook)


class Validation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    strict_path_check: bool = False


class AppConfig(BaseModel):
    """Top-Level Konfiguration, wie sie aus config.yaml geladen wird."""
    model_config = ConfigDict(extra="ignore")

    paths: Paths
    makemkv: MakeMKV = Field(default_factory=MakeMKV)
    probe: Probe = Field(default_factory=Probe)
    behavior: Behavior = Field(default_factory=Behavior)
    tmdb: TMDb = Field(default_factory=TMDb)
    hooks: Hooks = Field(default_factory=Hooks)
    validation: Validation = Field(default_factory=Validation)

    @property
    def base_root(self) -> Path:
        return self.paths.base_root

    @property
    def transcode_dir(self) -> Path:
        return self.paths.transcode_dir

    @property
    def remux_dir(self) -> Path:
        return self.paths.remux_dir

    @property
    def logs_dir(self) -> Path:
        return self.paths.logs_dir
