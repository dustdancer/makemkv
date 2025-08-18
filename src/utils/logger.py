# -*- coding: utf-8 -*-
"""
Stabiler Loader-Einstieg für den Scanner.
BITTE NICHT anfassen, wenn die Erkennung läuft.

Exportierte (kompatible) Entry-Points:
- find_sources(transcode_root: Path, log) -> list[dict]
- scan_sources(...)
- scan_transcode(...)
- scan(...)
- build_sources(...)

Alle rufen denselben, stabilen Scanner auf.
"""

from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Optional

# WICHTIG: Der Scanner ist in einer separaten Datei, die wir hier nur durchreichen.
from .scanner import find_sources as _stable_find_sources  # stabile, getestete Implementierung


def find_sources(transcode_root: Path, log) -> List[Dict]:
    """Bevorzugter Entry-Point."""
    return _stable_find_sources(transcode_root, log)


# Kompatible Alias-Namen – NICHT ändern, damit main/ältere Versionen funktionieren:
def scan_sources(transcode_root: Path, log) -> List[Dict]:
    return _stable_find_sources(transcode_root, log)

def scan_transcode(transcode_root: Path, log) -> List[Dict]:
    return _stable_find_sources(transcode_root, log)

def scan(transcode_root: Path, log) -> List[Dict]:
    return _stable_find_sources(transcode_root, log)

def build_sources(transcode_root: Path, log) -> List[Dict]:
    return _stable_find_sources(transcode_root, log)
