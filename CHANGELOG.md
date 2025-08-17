# Changelog
Alle nennenswerten Änderungen an diesem Projekt werden hier dokumentiert.

Das Format folgt grob [Keep a Changelog]. Versionierung nach [SemVer].

## [0.0.2] - 2025-08-17
### Added
- Repository-Grundgerüst: `.gitignore`, `.gitattributes`
- Beispielkonfiguration: `config_example.yaml`
- Secrets-Template: `secrets.example.txt`
- `README.md` Grundgerüst
- Versionierungsstrategie dokumentiert

## [0.0.1] - 2025-08-17
### Added
- Erste Projektstruktur (`config/`, `src/core`, `src/utils`, `src/services`, `src/ui`, `src/hooks`).
- Beispiel-Config `config_example.yaml` und `secrets.example.txt`.
- Scanner: findet ISO / BDMV / VIDEO_TS unterhalb `…/transcode` (movies/, tv/).
- MakeMKV-Runner mit `--robot` und einfachem Fortschritts-UI (Console-Spinner/Bar).
- RC-10-Vorbeugung durch zielgerichtete Übergabe (Ordner/Datei statt „irgendwo im Disc-Root“).
- Einfache Heuristiken für Rename/Move (Movie & TV inkl. Doppel-Folgen/Play-All-Erkennung light).
- Log-Setup mit Zeitstempel, Rotation und Trennung Auslesen/Remux.
- (Optional) TMDb-Abfrage der Episodenanzahl je Season.
- (Optional) Hook-Schnittstelle für `mkv-episode-matcher`.


### Changed
- Projektziel & Roadmap definiert; minimale Requirements ergänzt.

### Fixed
- Kleinere Robustheitsfixes bei Pfad-Normalisierung und Logging.

[Keep a Changelog]: https://keepachangelog.com/de/1.1.0/
[SemVer]: https://semver.org/lang/de/
