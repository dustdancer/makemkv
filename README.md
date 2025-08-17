# MakeMKV Auto Remux (WIP)

Automatisches Scannen → Remuxen (MakeMKV) → Verschieben → einfaches Umbenennen für Movies/TV.
Ziel: robuste Heuristiken, gute Logs, Dry-Run, optional TMDb/mkv-match-Integration.

## Status
Projekt im Aufbau (v0.0.1 – Scaffolding). Funktionen werden schrittweise gemäß Roadmap implementiert.

## Setup (lokal, Windows)
1. **Repo klonen**
2. **Konfig anlegen**
   - `config_example.yaml` nach `config/config.yaml` kopieren und anpassen
   - `secrets.example.txt` nach `config/secrets.txt` kopieren und mit Platzhaltern füllen  
     (z. B. `TMDB_API_KEY=your_key_here`, `SMB_USER=your_user`, `SMB_PASS=your_password`)
3. **Python**
   - Empfohlen: Python 3.10+ und venv
   - Abhängigkeiten kommen später gesammelt in `requirements.txt`
4. **MakeMKV**
   - MakeMKV installieren; `makemkvcon64.exe` Pfad ggf. in `config.yaml` setzen

## Voraussetzungen
- **Python 3.10+**
- **MakeMKV** inkl. `makemkvcon` im System (Windows oder Linux)
- (Empfohlen) **ffprobe** und/oder **mediainfo** für Laufzeit-Erkennung
- Optional: `mkv-episode-matcher` (Hook), TMDb API-Key

## Installation
```bash
git clone <dein-repo>
cd <dein-repo>
pip install -r requirements.txt