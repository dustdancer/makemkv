# -*- coding: utf-8 -*-
"""
Config-Loader + Validator (Pydantic v2)

- Liest YAML:            ./config/config.yaml
- Liest Secrets:         ./config/secrets.txt  (Format KEY=VALUE)
- Merged Secrets/ENV:    TMDB_API_KEY (optional), SMB_USER/SMB_PASS (optional)
- Normalisiert Pfade:    relative -> relativ zu base_root; Back-/Forward-Slashes ok
- Optional: Pfad-Existenz prüfen/erstellen (logs/remux)

Hinweis Versionierung:
Diese Datei wurde erstmals in v0.0.3 hinzugefügt.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import os
import re
import sys

import yaml  # PyYAML
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# -------------------------
# Secrets parsing (einfach)
# -------------------------

def _read_secrets_file(path: Path) -> Dict[str, str]:
    """
    Liest eine KEY=VALUE Datei (secrets.txt) mit einfachen Regeln:
      - erlaubt: KEY=VALUE (VALUE optional in '...' oder "...")
      - ignoriert: leere Zeilen, Kommentare (# oder ;)
    Bekannte Keys (case-insensitive):
      TMDB_API_KEY, SMB_USER, SMB_PASS
    """
    result: Dict[str, str] = {}
    if not path.exists():
        return result

    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        key = k.strip().upper()
        val = v.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        if key in ("TMDB_API_KEY", "SMB_USER", "SMB_PASS"):
            result[key] = val
    return result


# -------------------------
# Pydantic Modelle
# -------------------------

class PathsConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    base_root: Path = Field(..., description="Basisverzeichnis, auf das relative Pfade bezogen werden.")
    transcode_dir: Path = Field(..., description="Pfad zu den Quellmedien (ISO/BDMV/VIDEO_TS).")
    remux_dir: Path = Field(..., description="Zielverzeichnis für fertige MKVs.")
    logs_dir: Path = Field(..., description="Verzeichnis für Logs.")

    @field_validator("base_root", "transcode_dir", "remux_dir", "logs_dir", mode="before")
    @classmethod
    def _expand_env_and_tilde(cls, v: Any) -> Any:
        # Erlaubt Umgebungsvariablen und ~
        if isinstance(v, str):
            v = os.path.expandvars(os.path.expanduser(v))
        return v

    @model_validator(mode="after")
    def _join_relative_to_base(self) -> "PathsConfig":
        # Alle Felder relativ zu base_root auflösen, falls nicht absolut
        br = self.base_root
        def norm(p: Path) -> Path:
            return (br / p) if not p.is_absolute() else p
        self.transcode_dir = norm(self.transcode_dir)
        self.remux_dir     = norm(self.remux_dir)
        self.logs_dir      = norm(self.logs_dir)
        return self


class MakeMKVConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    win_paths: List[Path] = Field(
        default_factory=lambda: [
            Path(r"C:\Program Files (x86)\MakeMKV\makemkvcon64.exe"),
            Path(r"C:\Program Files\MakeMKV\makemkvcon64.exe"),
            Path(r"C:\Program Files (x86)\MakeMKV\makemkvcon.exe"),
            Path(r"C:\Program Files\MakeMKV\makemkvcon.exe"),
        ]
    )
    linux_path: str = "makemkvcon"
    extra_opts: List[str] = Field(default_factory=lambda: ["--robot"])


class BehaviorConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    delete_originals: bool = True
    dry_run: bool = False
    log_retention_days: int = 14
    minlength_seconds: int = 60  # optional für MakeMKV --minlength
    trailer_max_seconds: int = 240  # <= 4 min als Trailer behandeln


class TMDbConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True  # wird final aus api_key abgeleitet
    api_key: str = ""
    lang: str = "de-DE"
    timeout: int = 8

    @model_validator(mode="after")
    def _derive_enabled(self) -> "TMDbConfig":
        # enabled = True nur wenn Schlüssel vorhanden
        self.enabled = bool(self.api_key)
        return self


class AppConfig(BaseModel):
    """
    Gesamtkonfiguration nach Validierung/Normalisierung.
    """
    model_config = ConfigDict(extra="ignore")

    paths: PathsConfig
    makemkv: MakeMKVConfig = Field(default_factory=MakeMKVConfig)
    behavior: BehaviorConfig = Field(default_factory=BehaviorConfig)
    tmdb: TMDbConfig = Field(default_factory=TMDbConfig)

    # Optional mitgeführt (nicht zwingend genutzt – nur erreichbar):
    smb_user: Optional[str] = None
    smb_pass: Optional[str] = None


# -------------------------
# Loader-Funktionen
# -------------------------

def _first_existing(paths: List[Path]) -> Optional[Path]:
    for p in paths:
        if p.exists():
            return p
    return None


def _default_config_candidates() -> List[Path]:
    """
    Bevorzugt ./config/config.yaml (Arbeitsverzeichnis),
    fällt zurück auf Pfad relativ zu diesem Modul.
    """
    here = Path(__file__).resolve()
    repo_root_guess = here.parents[2] if len(here.parents) >= 3 else here.parent
    return [
        Path.cwd() / "config" / "config.yaml",
        repo_root_guess / "config" / "config.yaml",
    ]


def load_config(
    config_path: Optional[Path] = None,
    secrets_path: Optional[Path] = None,
    create_missing_dirs: bool = False,
    check_path_existence: bool = False,
) -> AppConfig:
    """
    Lädt, merged und validiert die Konfiguration.

    - config_path: Pfad zur YAML (Default: ./config/config.yaml)
    - secrets_path: Pfad zu secrets.txt (Default: ./config/secrets.txt)
    - create_missing_dirs: logs_dir/remux_dir ggf. anlegen
    - check_path_existence: wenn True, prüft Existenz (transcode_dir muss existieren)

    Raises:
        FileNotFoundError, yaml.YAMLError, pydantic.ValidationError, ValueError
    """
    # 1) YAML laden
    if config_path is None:
        candidates = _default_config_candidates()
        cfg_file = _first_existing(candidates)
        if not cfg_file:
            raise FileNotFoundError("config/config.yaml wurde nicht gefunden.")
        config_path = cfg_file

    with config_path.open("r", encoding="utf-8") as f:
        raw: Dict[str, Any] = yaml.safe_load(f) or {}

    # 2) Secrets + ENV mergen
    if secrets_path is None:
        # Standard: ./config/secrets.txt neben YAML
        secrets_path = config_path.parent / "secrets.txt"

    secrets = _read_secrets_file(secrets_path)
    # ENV hat Vorrang vor secrets.txt
    tmdb_env = os.environ.get("TMDB_API_KEY")
    smb_user_env = os.environ.get("SMB_USER")
    smb_pass_env = os.environ.get("SMB_PASS")

    tmdb_key = (tmdb_env or secrets.get("TMDB_API_KEY") or "").strip()
    smb_user = (smb_user_env or secrets.get("SMB_USER") or "").strip() or None
    smb_pass = (smb_pass_env or secrets.get("SMB_PASS") or "").strip() or None

    # 3) Rohdaten in unser Schema einsortieren
    #    (wir erlauben in YAML z. B. keys "paths", "behavior", "tmdb", "makemkv")
    paths_raw = raw.get("paths") or {}
    makemkv_raw = raw.get("makemkv") or {}
    behavior_raw = raw.get("behavior") or {}
    tmdb_raw = raw.get("tmdb") or {}

    # API-Key von secrets/env überschreibt YAML
    if tmdb_key:
        tmdb_raw = dict(tmdb_raw)
        tmdb_raw["api_key"] = tmdb_key

    # 4) Validierung via Pydantic
    cfg = AppConfig(
        paths=PathsConfig(**paths_raw),
        makemkv=MakeMKVConfig(**makemkv_raw),
        behavior=BehaviorConfig(**behavior_raw),
        tmdb=TMDbConfig(**tmdb_raw),
        smb_user=smb_user,
        smb_pass=smb_pass,
    )

    # 5) Optionale Pfadprüfungen/Erstellung
    if create_missing_dirs:
        cfg.paths.logs_dir.mkdir(parents=True, exist_ok=True)
        cfg.paths.remux_dir.mkdir(parents=True, exist_ok=True)

    if check_path_existence:
        # transcode_dir sollte existieren (sonst gibt's nichts zu tun)
        if not cfg.paths.transcode_dir.exists():
            raise ValueError(f"transcode_dir existiert nicht: {cfg.paths.transcode_dir}")
        # base_root muss nicht zwingend existieren, aber oft sinnvoll
        if not cfg.paths.base_root.exists():
            # kein harter Fehler – nur Hinweis
            print(f"[WARN] base_root existiert nicht: {cfg.paths.base_root}", file=sys.stderr)

    return cfg


# -------------------------
# kleiner CLI-Test
# -------------------------

if __name__ == "__main__":
    try:
        conf = load_config(create_missing_dirs=False, check_path_existence=False)
        print("Konfiguration geladen:")
        print(f"  base_root    : {conf.paths.base_root}")
        print(f"  transcode_dir: {conf.paths.transcode_dir}")
        print(f"  remux_dir    : {conf.paths.remux_dir}")
        print(f"  logs_dir     : {conf.paths.logs_dir}")
        print(f"  TMDb enabled : {conf.tmdb.enabled} (key={'…' if conf.tmdb.api_key else '—'})")
        print(f"  dry_run      : {conf.behavior.dry_run}")
    except Exception as e:
        print(f"[FATAL] {e}", file=sys.stderr)
        sys.exit(2)
