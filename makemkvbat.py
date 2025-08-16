#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Auto-Remux-Script für MakeMKV – mit erweiterten TV-Heuristiken (Doppel-Episoden & "Play All"),
optionalem mkv-episode-matcher Hook und secrets.txt-Unterstützung.

- Scannt ISO/BDMV/VIDEO_TS unter …/transcode (Unterordner movies/*, tv/*)
- Remuxt mit MakeMKV (CLI), 64-bit bevorzugt
- Movies: längste = Hauptfilm; Trailer/Bonus; sauberes Zielschema
- TV: Gruppierung pro Serie/Season, Disc-Reihenfolge, fortlaufende SxxExx
  * Adaptive Episoden-Erkennung per Median + ±Toleranz
  * Doppel-Episoden (~2× Median) zählen +2 (SxxExx-Eyy)
  * Play-All nur bei klaren Vielfachen (≥3× Median) bzw. wenn noch viele verbleiben
  * Letzte Disc: 2×Median bevorzugt als Doppel-Folge, wenn laut TMDb <=4 Folgen fehlen
- **Neu:** Fallback-Heuristik bei unbekannten Laufzeiten (ffprobe/mediainfo nicht verfügbar)
  * Episode/Double/Play-All anhand *Dateigröße* (Median ± Toleranzen)
- Optionaler Hook: mkv-episode-matcher (CLI) nach Remux → robustes TMDb/Untertitel/Whisper-Matching
  * Danach optionales Umbenennen in dein Schema: "Serienname – SxxExx - Episodentitel.mkv"
- UNC-Mount/Mapping (Windows net use / Linux CIFS), ausführliche Logs, Logrotation
- **Neu:** `secrets.txt`-Support im selben Ordner wie dieses Skript (Keys: user, pass, apikey)

Konfiguration unten in CONFIG anpassen.
"""

from __future__ import annotations
import os
import re
import sys
import json
import shlex
import shutil
import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple, Dict

try:
    from urllib.request import Request, urlopen
    from urllib.parse import urlencode
except Exception:
    Request = None  # type: ignore
    urlopen = None  # type: ignore
    urlencode = None  # type: ignore


# =========================
# ===== Secrets laden =====
# =========================

def load_secrets_file() -> Dict[str, str]:
    """
    Liest `secrets.txt` neben diesem Skript.

    Erlaubte Keys (case-insensitive):
      - user / username
      - pass / password
      - apikey / tmdb / tmdb_api_key

    Format: key=value — Werte dürfen optional in "" oder '' stehen.
    Kommentarzeilen mit # oder ; werden ignoriert.
    """
    secrets: Dict[str, str] = {}
    try:
        script_dir = Path(__file__).resolve().parent
        sec_path = script_dir / "secrets.txt"
        if not sec_path.exists():
            return secrets
        for raw in sec_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            key = k.strip().lower()
            val = v.strip()
            if (len(val) >= 2) and (val[0] == val[-1]) and val[0] in ('"', "'"):
                val = val[1:-1]
            if key in ("username",):
                key = "user"
            elif key in ("password",):
                key = "pass"
            elif key in ("tmdb", "tmdb_api_key"):
                key = "apikey"
            secrets[key] = val
    except Exception:
        pass
    return secrets


# =========================
# ======= CONFIG ==========
# =========================
CONFIG = {
    "NETWORK": {
        "ENABLE_MOUNT": True,
        "UNC_ROOT": r"\\\\blickfeldData\\downloads",
        "WIN_DRIVE_LETTER": "K:",
        "LINUX_MOUNT_POINT": "/mnt/blickfeldData",
        # Platzhalter; werden gleich aus secrets.txt/env überschrieben
        "USERNAME": "user",
        "PASSWORD": "password",
        "LINUX_CIFS_OPTS": "vers=3.0,iocharset=utf8,dir_mode=0775,file_mode=0664",
    },
    "PATHS": {
        "TRANSCODE_REL": r"data\\usenet\\complete\\iso\\transcode",
        "REMUX_REL":     r"data\\usenet\\complete\\iso\\remux",
        "LOGS_REL":      r"data\\usenet\\complete\\iso\\logs",
    },
    "MAKEMKV": {
        "WIN_PATHS": [
            r"C:\\Program Files (x86)\\MakeMKV\\makemkvcon64.exe",
            r"C:\\Program Files\\MakeMKV\\makemkvcon64.exe",
            r"C:\\Program Files (x86)\\MakeMKV\\makemkvcon.exe",
            r"C:\\Program Files\\MakeMKV\\makemkvcon.exe",
        ],
        "LINUX_PATH": "makemkvcon",
        "EXTRA_OPTS": ["--robot"],  # z. B. '--minlength=60'
    },
    "PROBE": {
        "PREFER_FFPROBE": True,
        "FFPROBE_PATH": "ffprobe",
        "MEDIAINFO_PATH": "mediainfo",
    },
    "BEHAVIOR": {
        "DELETE_ORIGINALS": True,
        "DRY_RUN": False,            # für Tests auf True setzen
        "LOG_RETENTION_DAYS": 14,
        "TRAILER_MAX": 240,          # <= 4 min
        "EPISODE_MIN": 18*60,        # 18 min
        "EPISODE_MAX": 65*60,        # 65 min
        "TINY_FILE_BYTES": 100 * 1024 * 1024,  # 100 MB
        "EPISODE_TOLERANCE": 0.15,   # ±15 % um den Median
        "DOUBLE_EP_TOL": 0.12,       # ±12 % um 2×Median
        "PLAYALL_MULT_TOL_MIN": 240, # 4 min
        "PLAYALL_MULT_TOL_MAX": 480, # 8 min
        "PLAYALL_FACTOR_MIN": 3.0,   # >= 3× Median ⇒ Play-All
        "PLAYALL_FACTOR_SOFT": 2.7,  # ab 2.7× Median *kann* Play-All sein (wenn viele verbleiben)
        # Neu: größenbasierte Heuristik
        "SIZE_TOLERANCE": 0.22,      # ±22 % um den Größen-Median
    },
    "TMDB": {
        # Platzhalter; wird unten aus secrets/env gesetzt
        "API_KEY": "",
        "LANG": "de-DE",
        "TIMEOUT": 8,
    },
    "HOOKS": {
        "MKV_MATCH": {
            "ENABLED": True,
            "BINARY": "mkv-match",
            "EXTRA_ARGS": [],
            "RENAME_TO_SCHEMA": True
        }
    }
}
# =========================

# Secrets zuerst anwenden, dann ggf. ENV drüber (ENV gewinnt)
_SECRETS = load_secrets_file()
if _SECRETS.get("user"):
    CONFIG["NETWORK"]["USERNAME"] = _SECRETS["user"]
if _SECRETS.get("pass"):
    CONFIG["NETWORK"]["PASSWORD"] = _SECRETS["pass"]
if _SECRETS.get("apikey"):
    CONFIG["TMDB"]["API_KEY"] = _SECRETS["apikey"]

_env_user = os.environ.get("BLICKFELD_SMB_USER")
_env_pass = os.environ.get("BLICKFELD_SMB_PASS")
_env_tmdb = os.environ.get("TMDB_API_KEY")
if _env_user:
    CONFIG["NETWORK"]["USERNAME"] = _env_user
if _env_pass:
    CONFIG["NETWORK"]["PASSWORD"] = _env_pass
if _env_tmdb:
    CONFIG["TMDB"]["API_KEY"] = _env_tmdb


# --- Utilities ---

def is_windows() -> bool:
    return os.name == "nt"


def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)


def sanitize_filename(name: str) -> str:
    name = name.strip()
    name = re.sub(r"[\\/:\*\?\"<>\|\x00-\x1F]", "_", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip().rstrip("._")


def now_stamp() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d-%H-%M")


# --- Simple Console Progress UI ---
class ConsoleUI:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._last_len = 0
        self._spinner = ['|', '/', '-', '\\']
        self._si = 0

    def write(self, text: str):
        if not self.enabled:
            return
        try:
            sys.stdout.write('\r' + text + ' ' * max(0, self._last_len - len(text)))
            sys.stdout.flush()
            self._last_len = len(text)
        except Exception:
            pass

    def bar(self, prefix: str, current: int, total: int, width: int = 28):
        if not self.enabled:
            return
        total = max(1, total)
        pct = max(0.0, min(1.0, current / total))
        filled = int(width * pct)
        bar = '[' + '#' * filled + '-' * (width - filled) + f'] {current}/{total} {pct*100:5.1f}%'
        self.write(f"{prefix} {bar}")

    def spin(self, prefix: str):
        if not self.enabled:
            return
        ch = self._spinner[self._si % len(self._spinner)]
        self._si += 1
        self.write(f"{prefix} {ch}")

    def done(self):
        if not self.enabled:
            return
        try:
            sys.stdout.write('\n')
            sys.stdout.flush()
        except Exception:
            pass
        self._last_len = 0


def setup_loggers(logs_dir: Path) -> Tuple[logging.Logger, logging.Logger, Path, Path]:
    ensure_dir(logs_dir)
    ts = now_stamp()
    auslesen_log_path = logs_dir / f"{ts}_auslesen.txt"
    remux_log_path    = logs_dir / f"{ts}_remux.txt"

    def mk(name: str, path: Path) -> logging.Logger:
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.setLevel(logging.DEBUG)
        fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", "%Y-%m-%d %H:%M:%S")
        fh = logging.FileHandler(path, encoding="utf-8")
        fh.setLevel(logging.DEBUG); fh.setFormatter(fmt)
        sh = logging.StreamHandler(sys.stdout)
        sh.setLevel(logging.INFO); sh.setFormatter(fmt)
        lg.addHandler(fh); lg.addHandler(sh)
        return lg

    auslesen_logger = mk("auslesen", auslesen_log_path)
    remux_logger    = mk("remux",    remux_log_path)

    # Logrotation
    keep = CONFIG["BEHAVIOR"]["LOG_RETENTION_DAYS"]
    for f in logs_dir.glob("*.txt"):
        try:
            age = datetime.now().astimezone() - datetime.fromtimestamp(f.stat().st_mtime).astimezone()
            if age > timedelta(days=keep):
                f.unlink(missing_ok=True)
        except Exception as e:
            remux_logger.warning(f"Log-Cleanup Problem bei {f}: {e}")

    # Sichtbar protokollieren, ob secrets/env gegriffen haben
    user = CONFIG["NETWORK"]["USERNAME"]
    tmdb = CONFIG["TMDB"]["API_KEY"]
    auslesen_logger.info(f"SMB-User: {user}")
    if tmdb:
        mask = tmdb[:4] + ("…" if len(tmdb) > 4 else "")
        auslesen_logger.info(f"TMDb: API-Key erkannt ({mask})")
    else:
        auslesen_logger.info("TMDb: kein API-Key geladen")

    return auslesen_logger, remux_logger, auslesen_log_path, remux_log_path


# --- Netzwerk mount/map ---

def parse_unc(unc: str) -> Tuple[str, str]:
    m = re.match(r"^\\\\([^\\]+)\\([^\\]+)", unc)
    if not m:
        raise ValueError(f"Ungültiger UNC-Root: {unc}")
    return m.group(1), m.group(2)


def mount_windows(unc_root: str, drive: str, user: str, pwd: str, log: logging.Logger) -> Optional[Path]:
    drive = drive.rstrip("\\/")
    try:
        subprocess.run(
            ["net", "use", drive, "/delete", "/y"],
            capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        cmd = ["net", "use", drive, unc_root, pwd, "/user:" + user, "/persistent:no"]
        if CONFIG["BEHAVIOR"]["DRY_RUN"]:
            log.info(f"[DRY-RUN] net use: {' '.join(cmd)}")
        else:
            log.info(f"Mappe Netzlaufwerk: {' '.join(cmd)}")
            res = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
            )
            if res.returncode != 0:
                log.error(f"net use fehlgeschlagen ({res.returncode}): {res.stdout}\n{res.stderr}")
                return None
        return Path(drive + "\\")
    except Exception as e:
        log.exception(f"Windows Netzlaufwerk Fehler: {e}")
        return None


def mount_linux(unc_root: str, mount_point: str, user: str, pwd: str, log: logging.Logger) -> Optional[Path]:
    server, share = parse_unc(unc_root)
    mp = Path(mount_point); ensure_dir(mp)
    opts = CONFIG["NETWORK"]["LINUX_CIFS_OPTS"]
    uid, gid = os.getuid(), os.getgid()
    opt_str = f"username={user},password={pwd},{opts},uid={uid},gid={gid}"
    cmd = ["mount", "-t", "cifs", f"//{server}/{share}", str(mp), "-o", opt_str]
    if CONFIG["BEHAVIOR"]["DRY_RUN"]:
        log.info(f"[DRY-RUN] mount CIFS: {' '.join(shlex.quote(x) for x in cmd)}")
        return mp
    log.info(f"Mount CIFS: {' '.join(shlex.quote(x) for x in cmd)}")
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        log.error(f"mount fehlgeschlagen ({res.returncode}): {res.stdout}\n{res.stderr}")
        return None
    return mp


def get_share_root(log: logging.Logger) -> Optional[Path]:
    net = CONFIG["NETWORK"]; base: Optional[Path] = None
    if net["ENABLE_MOUNT"]:
        base = mount_windows(net["UNC_ROOT"], net["WIN_DRIVE_LETTER"], net["USERNAME"], net["PASSWORD"], log) if is_windows() \
            else mount_linux(net["UNC_ROOT"], net["LINUX_MOUNT_POINT"], net["USERNAME"], net["PASSWORD"], log)
    else:
        base = Path(net["UNC_ROOT"]) if is_windows() else Path(net["LINUX_MOUNT_POINT"])
    return base


# --- MakeMKV ---

def find_makemkvcon(log: logging.Logger) -> Optional[str]:
    if is_windows():
        for p in CONFIG["MAKEMKV"]["WIN_PATHS"]:
            if Path(p).exists():
                log.info(f"MakeMKV gefunden: {p}")
                return p
        log.warning("MakeMKV-CLI nicht gefunden (Windows). Pfade in CONFIG prüfen.")
        return None
    p = shutil.which(CONFIG["MAKEMKV"]["LINUX_PATH"]) or CONFIG["MAKEMKV"]["LINUX_PATH"]
    if shutil.which(p) or Path(p).exists():
        log.info(f"MakeMKV gefunden: {p}")
        return p
    log.warning("makemkvcon nicht im PATH (Linux). CONFIG['MAKEMKV']['LINUX_PATH'] setzen.")
    return None


def _parse_prgv(line: str) -> Optional[Tuple[int, int]]:
    """Parst MakeMKV Robot-Progress-Zeilen: PRGV:<job>,<cur>,<total>."""
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


def run_makemkv(makemkv: str, source_kind: str, source_path: Path, out_dir: Path,
                log: logging.Logger, ui: Optional[ConsoleUI] = None) -> bool:
    ensure_dir(out_dir)
    if ui is None:
        ui = ConsoleUI(True)
    extra = CONFIG["MAKEMKV"]["EXTRA_OPTS"] or []
    input_spec = f"iso:{str(source_path)}" if source_kind == "iso" else f"file:{str(source_path)}"
    cmd = [makemkv, "mkv"] + extra + [input_spec, "all", str(out_dir)]
    log.info(f"MakeMKV: {' '.join(shlex.quote(x) for x in cmd)}")
    if CONFIG["BEHAVIOR"]["DRY_RUN"]:
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
            bufsize=1
        ) as proc:
            cur = 0; total = 0
            for line in proc.stdout or []:
                s = line.rstrip("\r\n")
                log.debug(s)
                pr = _parse_prgv(s)
                if pr:
                    cur, total = pr
                    ui.bar(f"Remux: {source_path.name}", cur, total)
                else:
                    ui.spin(f"Remux läuft: {source_path.name}")
            rc = proc.wait()
        ui.done()
        if rc != 0:
            log.error(f"MakeMKV Returncode {rc} – Quelle: {source_path}")
            return False
        return True
    except Exception as e:
        ui.done()
        log.exception(f"Fehler beim MakeMKV-Aufruf: {e}")
        return False


# --- Medienanalyse (Dauer via ffprobe/mediainfo) ---

def _probe_ffprobe(path: Path, log: logging.Logger) -> Optional[float]:
    ff = CONFIG["PROBE"]["FFPROBE_PATH"]
    if not shutil.which(ff):
        return None
    try:
        res = subprocess.run(
            [ff, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace"
        )
        if res.returncode == 0 and res.stdout.strip():
            return float(res.stdout.strip())
    except Exception as e:
        log.debug(f"ffprobe Fehler {path}: {e}")
    return None


def _probe_mediainfo(path: Path, log: logging.Logger) -> Optional[float]:
    mi = CONFIG["PROBE"]["MEDIAINFO_PATH"]
    if not shutil.which(mi):
        return None
    try:
        res = subprocess.run(
            [mi, "--Output=JSON", str(path)],
            capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace"
        )
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout)
            tracks = data.get("media", {}).get("track", [])
            for t in tracks:
                if t.get("@type") == "General":
                    dur = t.get("Duration")
                    if dur:
                        val = float(dur)
                        return val/1000.0 if val > 10000 else val
    except Exception as e:
        log.debug(f"mediainfo Fehler {path}: {e}")
    return None


def probe_duration_seconds(p: Path, log: logging.Logger) -> Optional[float]:
    if CONFIG["PROBE"]["PREFER_FFPROBE"]:
        d = _probe_ffprobe(p, log)
        return d if d is not None else _probe_mediainfo(p, log)
    d = _probe_mediainfo(p, log)
    return d if d is not None else _probe_ffprobe(p, log)


# --- Scan nach Quellen ---

def is_disc_folder(p: Path) -> Optional[str]:
    if (p / "BDMV").is_dir():
        return "bdmv"
    if (p / "VIDEO_TS").is_dir():
        return "dvd"
    if p.name.upper() == "BDMV":
        return "bdmv"
    if p.name.upper() == "VIDEO_TS":
        return "dvd"
    return None


def extract_season(s: str) -> Optional[int]:
    m = re.search(r"[Ss](?:eason)?\s*[_\-\.\s]?(\d{1,2})", s)
    if m:
        return int(m.group(1))
    m = re.search(r"\bS(\d{1,2})\b", s)
    return int(m.group(1)) if m else None


def extract_disc_no(s: str) -> Optional[int]:
    s = s.replace("_", " ")
    patterns = [
        r"\bdisc\s*(\d{1,2})\b", r"\bdisk\s*(\d{1,2})\b", r"\bd\s*(\d{1,2})\b",
        r"\bD(\d{1,2})\b", r"\bCD\s*(\d{1,2})\b", r"\bS\d{1,2}D(\d{1,2})\b",
        r"\bDisc(\d{1,2})\b", r"\bDisk(\d{1,2})\b"
    ]
    for pat in patterns:
        m = re.search(pat, s, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
    return None


def parse_name_year(base: str) -> Tuple[str, Optional[str], Optional[str]]:
    name = base; version = None
    mver = re.search(r"\[(.+?)\]", base)
    if mver:
        version = mver.group(1).strip()
        name = re.sub(r"\s*\[.+?\]\s*", " ", name).strip()
    my = re.search(r"\((\d{4})\)", base)
    year = my.group(1) if my else None
    if my:
        name = re.sub(r"\s*\(\d{4}\)\s*", " ", name).strip()
    name = sanitize_filename(name)
    return name, year, version


def find_sources(transcode_root: Path, log: logging.Logger) -> List[Dict]:
    log.info(f"Scan: {transcode_root}")
    sources: List[Dict] = []
    for root, dirs, files in os.walk(transcode_root):
        root_p = Path(root)
        rel = root_p.relative_to(transcode_root) if root_p != transcode_root else Path("")
        parts = [p.lower() for p in rel.parts]
        category = "movies" if "movies" in parts else ("tv" if "tv" in parts else None)

        # ISOs
        for f in files:
            if f.lower().endswith(".iso"):
                p = root_p / f
                base_disp = sanitize_filename(p.stem)
                sources.append({
                    "kind": "iso",
                    "path": p,
                    "category": category,
                    "display": base_disp,
                    "item_root": p.parent,
                    "season": extract_season(p.stem),
                    "disc": extract_disc_no(p.stem) or extract_disc_no(str(p.parent)),
                })
                log.debug(f"ISO: {p} (cat={category}, season={extract_season(p.stem)}, disc={extract_disc_no(p.stem)})")

        # Disc-Ordner
        kind_here = is_disc_folder(root_p)
        if kind_here:
            item_root = root_p if root_p.name.upper() not in ("BDMV", "VIDEO_TS") else root_p.parent
            eff_path = root_p if root_p.name.upper() in ("BDMV", "VIDEO_TS") else (root_p / ("BDMV" if kind_here == "bdmv" else "VIDEO_TS"))
            base_disp = sanitize_filename(item_root.name)
            sources.append({
                "kind": "file",
                "path": eff_path,
                "category": category,
                "display": base_disp,
                "item_root": item_root,
                "season": extract_season(item_root.name),
                "disc": extract_disc_no(item_root.name) or extract_disc_no(str(item_root.parent)),
            })
            log.debug(f"Disc-Ordner: {eff_path} (cat={category}, season={extract_season(item_root.name)}, disc={extract_disc_no(item_root.name)})")

    # Deduplizieren
    deduped: List[Dict] = []
    seen = set()
    for s in sources:
        key = (s.get("kind"), str(s.get("path")).lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(s)
    if len(deduped) != len(sources):
        log.info(f"Duplikate entfernt: {len(sources) - len(deduped)}")
    log.info(f"Scan fertig: {len(deduped)} Quelle(n)")
    return deduped


# --- Destination helpers ---

def destination_for_movie(remux_root: Path, base: str) -> Path:
    name, year, version = parse_name_year(base)
    dir_name = f"{name} ({year})" if year else name
    return remux_root / "movies" / dir_name


def destination_for_tv(remux_root: Path, base: str, season_no: Optional[int]) -> Path:
    name, year, version = parse_name_year(base)
    series_dir = f"{name} ({year})" if year else name
    return remux_root / "tv" / series_dir / (f"season {season_no:02d}" if season_no is not None else "season ??")


# --- Klassifikation / Helpers ---

def extract_title_index(fname: str) -> int:
    m = re.search(r"[^\d](\d{1,3})\.mkv$", fname)
    if m:
        return int(m.group(1))
    m = re.search(r"_t(\d{1,3})\.mkv$", fname, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d{1,3})\.mkv$", fname)
    return int(m.group(1)) if m else 9999


def durations_for_files(files: List[Path], log: logging.Logger) -> Dict[Path, float]:
    d: Dict[Path, float] = {}
    for f in files:
        dur = probe_duration_seconds(f, log)
        d[f] = dur if dur is not None else -1.0
        try:
            size = f.stat().st_size
        except FileNotFoundError:
            size = -1
        log.debug(f"Dauer {f.name}: {d[f]} s  | Größe: {size} B")
    return d


def median(values: List[float]) -> float:
    s = sorted(values); n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    return (s[mid-1] + s[mid]) / 2.0 if n % 2 == 0 else s[mid]


def near(value: float, target: float, tol_abs_min: float, tol_abs_max: float) -> bool:
    base_tol = max(tol_abs_min, min(tol_abs_max, target * 0.12))
    return abs(value - target) <= base_tol


def is_playall(dur: float, ep_med: float, remaining_total: Optional[int]) -> bool:
    if ep_med <= 0 or dur <= 0:
        return False
    if dur >= CONFIG["BEHAVIOR"]["PLAYALL_FACTOR_MIN"] * ep_med:
        return True
    if remaining_total is not None and remaining_total > 4 and dur >= CONFIG["BEHAVIOR"]["PLAYALL_FACTOR_SOFT"] * ep_med:
        return True
    for k in (3, 4, 5, 6, 7, 8):
        if near(dur, k * ep_med, CONFIG["BEHAVIOR"]["PLAYALL_MULT_TOL_MIN"], CONFIG["BEHAVIOR"]["PLAYALL_MULT_TOL_MAX"]):
            if remaining_total is None or remaining_total >= k:
                return True
    return False


# --- Rename/Move: Movies ---

def rename_and_move_movie(tmp_out: Path, dest_base: Path, base_display: str, log: logging.Logger) -> bool:
    files = sorted(tmp_out.glob("*.mkv"))
    if not files:
        log.error(f"Keine MKVs in {tmp_out}.")
        return False

    name, year, version = parse_name_year(base_display)
    ensure_dir(dest_base)

    durations = durations_for_files(files, log)
    # Sortierung: erst nach Dauer (unbekannt = -1 ⇒ ans Ende), dann nach Größe (größte zuerst), dann Name
    files_sorted = sorted(
        files,
        key=lambda p: (
            durations.get(p, -1.0) if durations.get(p, -1.0) >= 0 else float('-inf'),
            -p.stat().st_size if p.exists() else 0,
            p.name
        ),
        reverse=True
    )

    TR = CONFIG["BEHAVIOR"]["TRAILER_MAX"]
    main_done = False; trailer_counter = 1; bonus_counter = 1; ok = False

    def mv(src: Path, dst: Path):
        ensure_dir(dst.parent)
        if CONFIG["BEHAVIOR"]["DRY_RUN"]:
            log.info(f"[DRY-RUN] Move: {src} -> {dst}")
        else:
            shutil.move(str(src), str(dst))
            log.info(f"Verschoben: {src.name} -> {dst}")

    for idx, f in enumerate(files_sorted):
        dur = durations.get(f, -1.0)
        is_trailer = dur >= 0 and dur <= TR
        if not main_done and (idx == 0) and (dur < 0 or dur >= 45*60):
            tgt_name = f"{name}.mkv" if not version else f"{name} [{version}].mkv"
            mv(f, dest_base / tgt_name)
            main_done = True; ok = True
        elif is_trailer:
            mv(f, dest_base / f"{name}_trailer{('-' + str(trailer_counter)) if trailer_counter > 1 else ''}.mkv")
            trailer_counter += 1; ok = True
        else:
            mv(f, dest_base / f"{name} [bonusmaterial] - extra{bonus_counter:02d}.mkv")
            bonus_counter += 1; ok = True

    if not main_done:
        log.warning("Kein plausibler Hauptfilm – Fallback trackNN.")
        for idx, f in enumerate(files_sorted):
            mv(f, dest_base / f"{name} track{idx+1:02d}.mkv")
            ok = True

    try:
        if not CONFIG["BEHAVIOR"]["DRY_RUN"]:
            shutil.rmtree(tmp_out, ignore_errors=True)
    except Exception:
        pass
    return ok


# --- Rename/Move: TV ---

def rename_and_move_tv(
    tmp_out: Path,
    dest_base: Path,
    base_display: str,
    season_no: Optional[int],
    start_episode_no: int,
    expected_total_eps: Optional[int],
    is_last_disc: bool,
    log: logging.Logger,
) -> Tuple[bool, int]:
    files = sorted(tmp_out.glob("*.mkv"), key=lambda p: (extract_title_index(p.name), p.name))
    if not files:
        log.error(f"Keine MKVs in {tmp_out}.")
        return False, start_episode_no

    name, year, version = parse_name_year(base_display)
    ensure_dir(dest_base)

    durations = durations_for_files(files, log)
    TR = CONFIG["BEHAVIOR"]["TRAILER_MAX"]
    EP_MIN = CONFIG["BEHAVIOR"]["EPISODE_MIN"]
    EP_MAX = CONFIG["BEHAVIOR"]["EPISODE_MAX"]
    TINY   = CONFIG["BEHAVIOR"]["TINY_FILE_BYTES"]
    tol    = CONFIG["BEHAVIOR"]["EPISODE_TOLERANCE"]
    dtol   = CONFIG["BEHAVIOR"]["DOUBLE_EP_TOL"]
    size_tol = CONFIG["BEHAVIOR"]["SIZE_TOLERANCE"]

    sizes = {f: (f.stat().st_size if f.exists() else -1) for f in files}

    # Kandidaten für Dauer-basierte Medianbildung
    candidates = [durations[f] for f in files
                  if durations.get(f, -1.0) >= EP_MIN and durations.get(f, -1.0) <= EP_MAX
                  and sizes.get(f, -1) >= TINY]
    ep_med = median(candidates) if candidates else 0.0
    lo, hi = (ep_med*(1.0 - tol), ep_med*(1.0 + tol)) if ep_med > 0 else (0.0, 0.0)

    # Größenbasierter Median (Fallback)
    size_candidates = [sizes[f] for f in files if sizes.get(f, -1) >= TINY]
    size_med = float(median(size_candidates)) if size_candidates else 0.0
    slo, shi = (size_med*(1.0 - size_tol), size_med*(1.0 + size_tol)) if size_med > 0 else (0.0, 0.0)

    remaining_total = None
    if expected_total_eps is not None:
        remaining_total = max(0, expected_total_eps - (start_episode_no - 1))

    log.info(
        f"Episoden-Median: {ep_med:.1f}s | Fenster: [{lo:.1f}, {hi:.1f}] | "
        f"Größen-Median: {size_med/1024/1024/1024:.2f} GiB | Fenster: [{slo/1024/1024/1024:.2f}, {shi/1024/1024/1024:.2f}] GiB | "
        f"Start-Episode: {start_episode_no:02d} | Erwartet gesamt: {expected_total_eps} | "
        f"Verbleibend: {remaining_total} | Letzte Disc: {is_last_disc}"
    )

    def mv(src: Path, dst: Path):
        ensure_dir(dst.parent)
        if CONFIG["BEHAVIOR"]["DRY_RUN"]:
            log.info(f"[DRY-RUN] Move: {src} -> {dst}")
        else:
            shutil.move(str(src), str(dst))
            log.info(f"Verschoben: {src.name} -> {dst}")

    ep_no = start_episode_no
    trailer_counter = 1
    bonus_counter = 1
    success_any = False

    # Entscheiden, ob wir Dauer- oder Größenheuristik nehmen
    use_size_fallback = (ep_med <= 0) or (len(candidates) < max(1, len(files)//3))

    for f in files:
        dur = durations.get(f, -1.0)
        size = sizes.get(f, -1)
        tiny = size >= 0 and size < TINY

        # 1) Trailer-Erkennung
        is_trailer = (dur >= 0 and dur <= TR) or (tiny and dur > 0 and dur <= EP_MIN*0.6)

        if use_size_fallback:
            # 2) Größenbasierte Episode/Double
            is_episode = (not tiny) and (size_med > 0) and (size >= slo and size <= shi)
            is_double_ep = (not tiny) and (size_med > 0) and (size >= (2.0 - dtol) * size_med and size <= (2.0 + dtol) * size_med)
            # 3) Größenbasierter Play-All (≥3× Median)
            playall_candidate = (not tiny) and (size_med > 0) and (size >= CONFIG["BEHAVIOR"]["PLAYALL_FACTOR_MIN"] * size_med)
        else:
            # 2) Dauerbasierte Episode/Double
            is_episode = (dur >= lo and dur <= hi) and not tiny
            is_double_ep = not tiny and dur > hi and dur >= (2.0 - dtol) * ep_med and dur <= (2.0 + dtol) * ep_med
            # 3) Dauerbasierter Play-All
            playall_candidate = dur > 0 and is_playall(dur, ep_med, remaining_total)

        if is_last_disc and remaining_total is not None and remaining_total <= 4:
            if is_double_ep:
                playall_candidate = False

        log.debug(
            f"Classify: {f.name} | dur={dur:.1f}s | size={size} | tiny={tiny} | "
            f"episode={is_episode} | double={is_double_ep} | trailer={is_trailer} | playall?={playall_candidate} | "
            f"mode={'SIZE' if use_size_fallback else 'DURATION'}"
        )

        if playall_candidate and not is_episode and not is_double_ep:
            mv(f, dest_base / f"{name} [bonusmaterial] - playall.mkv")
            success_any = True
            continue

        if is_double_ep:
            if season_no is not None:
                tgt = dest_base / f"{name} – S{season_no:02d}E{ep_no:02d}-E{ep_no+1:02d}.mkv"
            else:
                tgt = dest_base / f"{name} – E{ep_no:02d}-E{ep_no+1:02d}.mkv"
            ep_no += 2
            mv(f, tgt)
            success_any = True
            continue

        if is_episode:
            if season_no is not None:
                tgt = dest_base / f"{name} – S{season_no:02d}E{ep_no:02d}.mkv"
            else:
                tgt = dest_base / f"{name} – E{ep_no:02d}.mkv"
            ep_no += 1
            mv(f, tgt)
            success_any = True
        elif is_trailer:
            mv(f, dest_base / f"{name}_trailer{('-' + str(trailer_counter)) if trailer_counter > 1 else ''}.mkv")
            trailer_counter += 1
            success_any = True
        else:
            mv(f, dest_base / f"{name} [bonusmaterial] - extra{bonus_counter:02d}.mkv")
            bonus_counter += 1
            success_any = True

    # WICHTIG: Fallback nur, wenn GAR NICHTS verschoben wurde.
    if (ep_no == start_episode_no) and (success_any is False):
        log.warning("Keine Episoden erkannt – Fallback trackNN (Reihenfolge beibehalten).")
        idx = 1
        for f in files:
            mv(f, dest_base / f"{name} track{idx:02d}.mkv")
            idx += 1
            success_any = True

    try:
        if not CONFIG["BEHAVIOR"]["DRY_RUN"]:
            shutil.rmtree(tmp_out, ignore_errors=True)
    except Exception:
        pass

    return success_any, ep_no


# --- TMDb: erwartete Episoden-Anzahl (optional) ---

def tmdb_is_enabled() -> bool:
    api = CONFIG["TMDB"].get("API_KEY")
    return bool(api)


def http_get_json(url: str, params: Dict[str, str], timeout: int) -> Optional[Dict]:
    if Request is None or urlopen is None or urlencode is None:
        return None
    query = urlencode(params)
    req = Request(url + ("?" + query if query else ""), headers={"Accept": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8", errors="replace")
            return json.loads(data)
    except Exception:
        return None


def tmdb_search_tv_id(series_name: str, year_hint: Optional[str], log: logging.Logger) -> Optional[int]:
    api = CONFIG["TMDB"].get("API_KEY")
    if not tmdb_is_enabled() or not api:
        return None
    base = "https://api.themoviedb.org/3/search/tv"
    params = {
        "api_key": api,
        "language": CONFIG["TMDB"].get("LANG", "de-DE"),
        "query": series_name,
    }
    if year_hint and year_hint.isdigit():
        params["first_air_date_year"] = year_hint
    data = http_get_json(base, params, CONFIG["TMDB"].get("TIMEOUT", 8))
    if not data or not data.get("results"):
        log.debug("TMDb: keine Treffer in search/tv")
        return None
    results = data["results"]
    for r in results:
        if r.get("name", "").lower() == series_name.lower():
            return r.get("id")
    return results[0].get("id")


def tmdb_get_season_episode_count(series_name: str, year_hint: Optional[str], season_no: Optional[int], log: logging.Logger) -> Optional[int]:
    if season_no is None:
        return None
    api = CONFIG["TMDB"].get("API_KEY")
    if not tmdb_is_enabled() or not api:
        return None
    sid = tmdb_search_tv_id(series_name, year_hint, log)
    if not sid:
        return None
    base = f"https://api.themoviedb.org/3/tv/{sid}/season/{season_no}"
    params = {"api_key": api, "language": CONFIG["TMDB"].get("LANG", "de-DE")}
    data = http_get_json(base, params, CONFIG["TMDB"].get("TIMEOUT", 8))
    if not data:
        return None
    eps = data.get("episodes")
    return len(eps) if isinstance(eps, list) else None


# --- Optional Hook: mkv-episode-matcher ---

def run_mkv_match(show_dir: Path, season_no: Optional[int], series_name: Optional[str],
                  log: logging.Logger, ui: Optional[ConsoleUI] = None) -> bool:
    hk = CONFIG.get("HOOKS", {}).get("MKV_MATCH", {})
    if not hk or not hk.get("ENABLED", False):
        return False
    bin_name = hk.get("BINARY", "mkv-match")
    if not shutil.which(bin_name):
        log.info("mkv-match nicht gefunden (nicht im PATH) – Hook wird übersprungen.")
        return False
    args = [bin_name, "--show-dir", str(show_dir)]
    if season_no is not None:
        args += ["--season", str(season_no)]
    api = CONFIG["TMDB"].get("API_KEY")
    if api:
        args += ["--tmdb-api-key", api]
    extra = hk.get("EXTRA_ARGS", []) or []
    args.extend(extra)

    if ui is None:
        ui = ConsoleUI(True)

    log.info(f"[HOOK] mkv-match: {' '.join(shlex.quote(x) for x in args)}")
    if CONFIG["BEHAVIOR"].get("DRY_RUN", False):
        log.info("[DRY-RUN] mkv-match nicht ausgeführt.")
        return True
    try:
        with subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1
        ) as proc:
            for line in proc.stdout or []:
                s = line.rstrip("\r\n")
                ui.spin(f"mkv-match: {show_dir.name}")
                log.debug(f"mkv-match | {s}")
            rc = proc.wait()
        ui.done()
        if rc != 0:
            log.warning(f"mkv-match Returncode {rc} – evtl. kein Match/Teilerfolg.")
            return False
        return True
    except Exception as e:
        ui.done()
        log.exception(f"mkv-match Fehler: {e}")
        return False


def normalize_mkv_match_naming(show_dir: Path, series_base: Optional[str],
                               season_no: Optional[int], log: logging.Logger) -> None:
    """Benennt Dateien in das Schema 'Serienname – SxxExx - Episodentitel.mkv' um (nur S/E-Treffer)."""
    base = series_base or show_dir.parent.name
    series_name, year_hint, _ = parse_name_year(base)

    def make_unique(dst: Path) -> Path:
        if not dst.exists():
            return dst
        stem, ext = dst.stem, dst.suffix
        i = 1
        while True:
            cand = dst.with_name(f"{stem} ({i}){ext}")
            if not cand.exists():
                return cand
            i += 1

    pat = re.compile(r"(?i)S(\d{1,2})E(\d{2})(?:[-_ ]?E(\d{2}))?")

    for f in sorted(show_dir.glob("*.mkv")):
        m = pat.search(f.name)
        if not m:
            continue
        s = int(m.group(1))
        e1 = int(m.group(2))
        e2 = m.group(3)
        title = pat.sub("", f.stem)
        title = re.sub(r"^[\s\-_.]+|[\s\-_.]+$", "", title)
        title = title.replace("_", " ").replace(".", " ")
        title = re.sub(r"\s+", " ", title).strip()
        title = sanitize_filename(title) if title else None

        if season_no is not None and s != season_no:
            pass

        if e2:
            new_name = f"{series_name} – S{s:02d}E{e1:02d}-E{int(e2):02d}"
        else:
            new_name = f"{series_name} – S{s:02d}E{e1:02d}"
        if title:
            new_name += f" - {title}"
        new_path = f.with_name(new_name + f.suffix)
        new_path = make_unique(new_path)

        if CONFIG["BEHAVIOR"].get("DRY_RUN", False):
            log.info(f"[DRY-RUN] Rename: {f.name} -> {new_path.name}")
        else:
            try:
                f.rename(new_path)
                log.info(f"Rename: {f.name} -> {new_path.name}")
            except Exception as e:
                log.warning(f"Rename fehlgeschlagen für {f.name}: {e}")


# --- Hauptablauf ---

def delete_path(p: Path, log: logging.Logger):
    if CONFIG["BEHAVIOR"]["DRY_RUN"]:
        log.info(f"[DRY-RUN] Löschen: {p}")
        return
    if p.is_file() or p.is_symlink():
        p.unlink(missing_ok=True)
        log.info(f"Datei gelöscht: {p}")
    elif p.is_dir():
        shutil.rmtree(p, ignore_errors=True)
        log.info(f"Ordner gelöscht: {p}")


def main():
    dummy = logging.getLogger("dummy"); dummy.addHandler(logging.NullHandler())
    base_root = get_share_root(dummy) if CONFIG["NETWORK"]["ENABLE_MOUNT"] else None
    if not base_root:
        base_root = Path(CONFIG["NETWORK"]["WIN_DRIVE_LETTER"] + "\\") if is_windows() else Path(CONFIG["NETWORK"]["LINUX_MOUNT_POINT"])
        if not base_root.exists() and is_windows():
            base_root = Path(CONFIG["NETWORK"]["UNC_ROOT"])
    if not base_root or not base_root.exists():
        print(f"[FATAL] Basis-Root nicht gefunden: {base_root}")
        sys.exit(2)

    P = CONFIG["PATHS"]
    transcode_root = base_root / Path(P["TRANSCODE_REL"])
    remux_root     = base_root / Path(P["REMUX_REL"])
    logs_dir       = base_root / Path(P["LOGS_REL"])
    ensure_dir(remux_root); ensure_dir(logs_dir)

    auslesen_log, remux_log, _, _ = setup_loggers(logs_dir)
    ui = ConsoleUI(True)

    auslesen_log.info(f"Base: {base_root}")
    auslesen_log.info(f"Transcode: {transcode_root}")
    auslesen_log.info(f"Remux: {remux_root}")
    auslesen_log.info(f"Logs: {logs_dir}")

    if not transcode_root.exists():
        auslesen_log.error(f"Transcode-Verzeichnis existiert nicht: {transcode_root}")
        sys.exit(3)

    sources = find_sources(transcode_root, auslesen_log)
    if not sources:
        auslesen_log.info("Keine Quellen gefunden. Ende.")
        return

    makemkv = find_makemkvcon(remux_log)
    if not makemkv:
        remux_log.error("MakeMKV CLI nicht gefunden – Abbruch.")
        sys.exit(4)

    # --- Filme / TV trennen ---
    movies = [s for s in sources if (s.get("category") != "tv")]
    tvs    = [s for s in sources if (s.get("category") == "tv")]

    # Filme
    for src in movies:
        disp = src["display"]; src_path = src["path"]; item_root = src["item_root"]
        remux_log.info("=" * 80)
        remux_log.info(f"[MOVIE] Quelle: {src_path} | {src['kind']} | Bezeichner: {disp}")

        tmp_out = remux_root / "_tmp" / sanitize_filename(disp)
        ensure_dir(tmp_out)

        if not run_makemkv(makemkv, "iso" if src["kind"] == "iso" else "file", src_path, tmp_out, remux_log, ui):
            remux_log.error(f"Remux FEHLGESCHLAGEN (Movie): {src_path}")
            delete_path(tmp_out, remux_log)
            continue

        dest_base = destination_for_movie(remux_root, disp)
        ok = rename_and_move_movie(tmp_out, dest_base, disp, remux_log)
        if not ok:
            remux_log.warning(f"Movie-Ausgabe nicht verschoben: {disp}")
            continue

        if CONFIG["BEHAVIOR"]["DELETE_ORIGINALS"]:
            remux_log.info(f"Original löschen: {item_root}")
            delete_path(item_root if item_root.is_dir() else src_path, remux_log)

    # TV gruppieren: key = (series_key, season)
    def series_key(s: str) -> str:
        s2 = re.sub(r"\b[Dd]isc\s*\d{1,2}\b", "", s)
        s2 = re.sub(r"\b[Dd](\d{1,2})\b", "", s2)
        s2 = re.sub(r"\b[Ss](?:eason)?\s*\d{1,2}\b", "", s2)
        s2 = re.sub(r"\bS\d{1,2}D\d{1,2}\b", "", s2)
        return sanitize_filename(s2).strip()

    tv_groups: Dict[Tuple[str, Optional[int]], List[Dict]] = {}
    for s in tvs:
        key = (series_key(s["display"]), s.get("season"))
        tv_groups.setdefault(key, []).append(s)

    # Pro Gruppe: Discs sortieren -> TMDb Episode Count (optional) -> verarbeiten
    for (series_base, season_no), discs in tv_groups.items():
        remux_log.info("=" * 80)
        remux_log.info(f"[TV] Serie='{series_base}' | Season={season_no} | Discs={len(discs)}")

        series_name, year_hint, _ = parse_name_year(series_base if series_base else "")
        expected_total_eps = tmdb_get_season_episode_count(series_name, year_hint, season_no, remux_log)
        if expected_total_eps:
            remux_log.info(f"TMDb: erwartete Episoden (S{season_no}): {expected_total_eps}")
        else:
            remux_log.info("TMDb: keine Episodenanzahl verfügbar (API-Key nicht gesetzt oder kein Treffer).")

        discs_sorted = sorted(discs, key=lambda d: (d.get("disc") or 9999, str(d["path"])))
        next_ep = 1

        for idx, d in enumerate(discs_sorted):
            disp = d["display"]; src_path = d["path"]; item_root = d["item_root"]
            disc_no = d.get("disc")
            is_last_disc = (idx == len(discs_sorted) - 1)

            remux_log.info("-" * 60)
            remux_log.info(f"Disc: {disc_no if disc_no else '?'} | Quelle: {src_path} | Bezeichner: {disp} | Letzte Disc: {is_last_disc}")

            tmp_out = remux_root / "_tmp" / sanitize_filename(f"{series_name or disp}_S{season_no or 0:02d}_D{disc_no or 0:02d}")
            ensure_dir(tmp_out)

            if not run_makemkv(makemkv, "iso" if d["kind"] == "iso" else "file", src_path, tmp_out, remux_log, ui):
                remux_log.error(f"Remux FEHLGESCHLAGEN (TV): {src_path}")
                delete_path(tmp_out, remux_log)
                continue

            dest_base = destination_for_tv(remux_root, series_name or disp, season_no)
            ok, next_ep = rename_and_move_tv(
                tmp_out, dest_base,
                series_name or disp,
                season_no, next_ep,
                expected_total_eps,
                is_last_disc,
                remux_log,
            )
            if not ok:
                remux_log.warning(f"TV-Ausgabe nicht verschoben: {disp}")
                continue

            # Optional: mkv-episode-matcher Hook (per Disc auf Season-Ordner)
            if CONFIG.get("HOOKS", {}).get("MKV_MATCH", {}).get("ENABLED", False):
                season_dir = destination_for_tv(remux_root, series_name or series_base, season_no)
                try:
                    ran = run_mkv_match(season_dir, season_no, series_name or series_base, remux_log, ui)
                    if ran and CONFIG["HOOKS"]["MKV_MATCH"].get("RENAME_TO_SCHEMA", True):
                        normalize_mkv_match_naming(season_dir, series_name or series_base, season_no, remux_log)
                except Exception as _e:
                    remux_log.warning(f"mkv-match Hook übersprungen/fehlerhaft: {_e}")

            if CONFIG["BEHAVIOR"]["DELETE_ORIGINALS"]:
                remux_log.info(f"Original löschen: {item_root}")
                delete_path(item_root if item_root.is_dir() else src_path, remux_log)

    remux_log.info("=" * 80)
    remux_log.info("Fertig – alle Quellen abgearbeitet.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAbgebrochen (Ctrl+C).")
