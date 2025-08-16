# file: makemkv/utils.py
from __future__ import annotations

import os
import re
import sys
import shutil
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Tuple

# -----------------------------
# Basic platform / path helpers
# -----------------------------

def is_windows() -> bool:
    return os.name == "nt"


def ensure_dir(p: Path) -> Path:
    """Create directory (including parents) if missing and return it."""
    p.mkdir(parents=True, exist_ok=True)
    return p


def rmtree_silent(p: Path, *, log: Optional[logging.Logger] = None, dry_run: bool = False) -> None:
    """Remove directory tree without raising; logs best-effort."""
    if dry_run:
        if log:
            log.info(f"[DRY-RUN] Löschen: {p}")
        return
    try:
        shutil.rmtree(p, ignore_errors=True)
        if log:
            log.info(f"Ordner gelöscht: {p}")
    except Exception as e:
        if log:
            log.warning(f"Ordner löschen fehlgeschlagen ({p}): {e}")


def unlink_silent(p: Path, *, log: Optional[logging.Logger] = None, dry_run: bool = False) -> None:
    if dry_run:
        if log:
            log.info(f"[DRY-RUN] Datei löschen: {p}")
        return
    try:
        p.unlink(missing_ok=True)
        if log:
            log.info(f"Datei gelöscht: {p}")
    except Exception as e:
        if log:
            log.warning(f"Datei löschen fehlgeschlagen ({p}): {e}")


# -----------------------------
# Filenames / formatting
# -----------------------------

_INVALID_FS = re.compile(r'[\\/:*?"<>|\x00-\x1F]')

def sanitize_filename(name: str) -> str:
    """
    Windows/macOS/Linux-safe filename:
    - Strip control + reserved characters
    - Collapse whitespace
    - Trim trailing dots/space
    """
    name = name.strip()
    name = _INVALID_FS.sub("_", name)
    name = re.sub(r"\s+", " ", name)
    name = name.strip().rstrip("._")
    # Avoid empty names
    return name or "unnamed"


def unique_path(dst: Path) -> Path:
    """Return a non-existing path by appending ' (n)' before suffix if needed."""
    if not dst.exists():
        return dst
    stem, ext = dst.stem, dst.suffix
    n = 1
    while True:
        cand = dst.with_name(f"{stem} ({n}){ext}")
        if not cand.exists():
            return cand
        n += 1


def safe_move(src: Path, dst: Path, *, log: Optional[logging.Logger] = None, dry_run: bool = False) -> Path:
    """
    Move src → dst, creating parent, de-duping name if necessary.
    Returns the final destination path.
    """
    ensure_dir(dst.parent)
    final = dst if not dst.exists() else unique_path(dst)
    if dry_run:
        if log:
            log.info(f"[DRY-RUN] Move: {src} -> {final}")
        return final
    shutil.move(str(src), str(final))
    if log:
        log.info(f"Verschoben: {src.name} -> {final}")
    return final


def safe_rename(src: Path, dst: Path, *, log: Optional[logging.Logger] = None, dry_run: bool = False) -> Path:
    """Rename with parent creation + unique fallback. Returns final destination."""
    ensure_dir(dst.parent)
    final = dst if not dst.exists() else unique_path(dst)
    if dry_run:
        if log:
            log.info(f"[DRY-RUN] Rename: {src} -> {final}")
        return final
    src.rename(final)
    if log:
        log.info(f"Rename: {src.name} -> {final.name}")
    return final


def fmt_bytes(n: Optional[int]) -> str:
    if n is None or n < 0:
        return "n/a"
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    v = float(n)
    i = 0
    while v >= 1024 and i < len(units) - 1:
        v /= 1024.0
        i += 1
    return f"{v:.2f} {units[i]}"


def fmt_seconds(sec: Optional[float]) -> str:
    if sec is None or sec < 0:
        return "n/a"
    s = int(round(sec))
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


def now_stamp(fmt: str = "%Y-%m-%d-%H-%M") -> str:
    """Local time, safe for filenames by default."""
    return datetime.now(timezone.utc).astimezone().strftime(fmt)


def mask_secret(s: str, keep: int = 4) -> str:
    """Mask a secret for logs: 'abcd…'"""
    if not s:
        return ""
    return s[:keep] + ("…" if len(s) > keep else "")


# -----------------------------
# Sorting / parsing
# -----------------------------

_nat_part = re.compile(r"(\d+)")

def natural_key(s: str):
    """Human-friendly sort key: 'file2' < 'file10'."""
    return [int(t) if t.isdigit() else t.lower() for t in _nat_part.split(s)]


def try_int(s: str, default: Optional[int] = None) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return default


def parse_prgv(line: str) -> Optional[Tuple[int, int]]:
    """
    Parse MakeMKV progress lines: 'PRGV:<job>,<cur>,<total>'.
    Returns (cur, total) or None.
    """
    if not line.startswith("PRGV:"):
        return None
    try:
        parts = line.strip().split(":")[1].split(",")
        if len(parts) >= 3:
            cur, total = int(parts[1]), int(parts[2])
            return (cur, total) if total > 0 else None
    except Exception:
        return None
    return None


# -----------------------------
# File listing helpers
# -----------------------------

VIDEO_EXTS = {".mkv", ".mp4", ".m4v", ".ts", ".m2ts", ".avi", ".mov", ".wmv"}

def list_video_files(folder: Path, *, recursive: bool = False) -> List[Path]:
    """List video files with common extensions (case-insensitive)."""
    if not folder.exists():
        return []
    exts = {e.lower() for e in VIDEO_EXTS}
    it: Iterable[Path] = folder.rglob("*") if recursive else folder.iterdir()
    out: List[Path] = []
    for p in it:
        try:
            if p.is_file() and p.suffix.lower() in exts:
                out.append(p)
        except PermissionError:
            continue
    return sorted(out, key=lambda p: natural_key(p.name))


# -----------------------------
# Small IO helpers
# -----------------------------

def write_text_atomic(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """
    Write file atomically: create temp file in same dir then replace.
    """
    tmp = path.with_name(path.name + ".tmp")
    ensure_dir(path.parent)
    tmp.write_text(text, encoding=encoding)
    tmp.replace(path)


def read_text_safely(path: Path, *, encoding: str = "utf-8") -> str:
    try:
        return path.read_text(encoding=encoding, errors="replace")
    except Exception:
        return ""


# -----------------------------
# Windows stdout cleanup
# -----------------------------

def enable_utf8_stdout_on_windows() -> None:
    """
    Best-effort: force UTF-8 output to reduce cp1252 decode issues in terminals.
    (No-op on non-Windows.)
    """
    if not is_windows():
        return
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass


__all__ = [
    "is_windows",
    "ensure_dir",
    "rmtree_silent",
    "unlink_silent",
    "sanitize_filename",
    "unique_path",
    "safe_move",
    "safe_rename",
    "fmt_bytes",
    "fmt_seconds",
    "now_stamp",
    "mask_secret",
    "natural_key",
    "try_int",
    "parse_prgv",
    "VIDEO_EXTS",
    "list_video_files",
    "write_text_atomic",
    "read_text_safely",
    "enable_utf8_stdout_on_windows",
]
