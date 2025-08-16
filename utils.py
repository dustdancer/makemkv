# -*- coding: utf-8 -*-
from __future__ import annotations
import os, re
from datetime import datetime
from pathlib import Path

def is_windows() -> bool:
    return os.name == "nt"

def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def now_stamp() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d-%H-%M")

def sanitize_filename(name: str) -> str:
    name = name.strip()
    name = re.sub(r"[\\/:\*\?\"<>\|\x00-\x1F]", "_", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip().rstrip("._")

def mask_key(key: str, keep: int = 4) -> str:
    if not key: return ""
    if len(key) <= keep: return key
    return key[:keep] + "…"
