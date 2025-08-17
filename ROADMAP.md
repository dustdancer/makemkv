Roadmap & To-Do
Versionierung

Projektversion (global, semver-artig): MAJOR.MINOR.PATCH

PATCH (0.0.x): Bugfixes / kleinste Änderungen

MINOR (0.x): neue Features, abwärtskompatibel

MAJOR (1.x): größere, evtl. inkompatible Änderungen

Keine per-Datei-Versionen; nur eine Projektversion (optional: Modul-__version__ als Info)

MVP (v0.1 – lauffähig & robust)

Ziel: zuverlässig scannen → remuxen → verschieben → einfach umbenennen, mit guten Logs & Dry-Run.

 Plattformen: Windows & Linux

 Config + Validierung

 YAML laden (config/config.yaml) + Defaults

 Schema-Prüfung (pydantic/voluptuous)

 MakeMKV-Suche (Win 64/32, Linux PATH)

 Pfade: importroot/transcode, remux, logs

 Optionen: Log-Level, Dry-Run, Mindestlängen, TMDb an/aus, Delete-Originals

 Secrets getrennt (config/secrets.txt), nur auslesen, kein Scannen

 Scan

 Gezielte Suche nach ISO / BDMV / VIDEO_TS

 RC-10-Fix: Pfad-Normalisierung auf VIDEO_TS/VIDEO_TS.IFO bzw. BDMV/index.bdmv

 Deduplizieren & Kategorisieren (movies/tv)

 Remux

 MakeMKV-Aufruf mit --robot

 PRGV-Parsing (Fortschritt), Spinner

 Fehlercodes behandeln (0 ok, 10 bad source, 251 key expired …)

 Freier-Speicher-Check vor Start

 Rename/Move

 Movies: längster Track = Hauptfilm, Rest Trailer/Bonus; klares Zielschema

 TV: einfache Heuristik per Median-Laufzeit

 Einzel-Episode (≈ Median), Doppel-Episode (~2× Median), Play-All (≥3×)

 Fallback trackNN

 Renaming-Fallbacks: (1) Verzeichnisname, (2) optionaler Hook

 Zielordner: movies/<Name (Year)> und tv/<Serie (Year)>/season XX

 Logging/Debug

 Zeitgestempelte Logs (Run-Timestamp)

 Abschnitte: Scan / Remux / Rename

 Run-Settings protokollieren (wichtige Configwerte)

 Run-Report am Ende (Kurzfassung)

 Dry-Run global

 Safer Delete: Originale erst löschen, wenn Ziel-MKVs plausibel vorhanden

v1.0 (Qualität & Bedienung)

 Idempotenz & Resume: „skip already done“ + Marker/CSV

 Lokaler TMDb-Cache (nur Staffel/Episodenanzahl; TTL)

 Watch-Mode (einfacher Hot-Folder, watchdog)

 _tmp-Cleanup beim Start

 CLI-Subcommands: scan, remux, rename, report, clean (+ --config, --dry-run)

 Lange Windows-Pfade optional via \\?\ behandeln

 Optionale Benachrichtigungen (Webhook/Telegram) bei Fehlern/Fertig

v1.1 (Komfort & Interop)

 Track-Auswahl-Präferenzen: Audio-Sprachen, Forced-Subs, Commentary filtern, Default-Flags

 NFO/Sidecar-Export (Kodi/Jellyfin) – optional

 Sonarr/Radarr-freundliches Schema – optionales Renaming-Profil

 mkv-episode-matcher Hook: Integration + normiertes Zielschema (SxxExx – Titel)

 Dockerfile (reproduzierbare Umgebung mit ffprobe/mediainfo)

v2.0 (Fortgeschritten)

 Erweiterte Episoden-Zuordnung
DB/Längen-Katalog, Extended/Director’s Cut, Cross-Disc-Chronologie

 Boxsets über mehrere Seasons (Heuristik + Overrides)

 Konfigurierbare Parallelisierung (IO-Messung, Worker-Limit)

 Dienstbetrieb-Beispiele (systemd/Task Scheduler) + Health-Checks

 Metriken/Stats & feingranulare Logger (scan/remux/rename/api, Laufzeit-Stats)

Modul-Schnitt (Struktur, empfohlene Ordner)

 config/ – Loader, Defaults, Schema-Validierung

 scan/ – Finder + Typbestimmung + RC-10-Fix

 remux/ – MakeMKV-Runner + Progress + Fehlercodes

 rename/ – Movie/TV-Heuristiken + Fallbacks + Hook-Adapter

 integrations/ – tmdb_client, mkv-match, notifier

 ops/ – mounts, paths, disk-space, safe-delete, tmp-cleanup

 cli/ – Subcommands & Argumente

 tests/ + fixtures/ – Fake-Bäume + Stub-makemkvcon

Backlog / später

 Fortgeschrittene Play-All/Doppelfolgen-Erkennung (weiche Faktoren)

 Globale fortlaufende Episoden über mehrere Discs nur bei verifizierter Chronologie

 „Warteschlangen-Dashboard“ mit verbleibenden Discs/Tracks (großes UI)

Nicht-Funktionales / Pflege

 Requirements pflegen (minimale, stabile Abhängigkeiten)

 README mit Setup, Quickstart, Beispiele

 CHANGELOG nach Keep-a-Changelog (ab 0.0.1)

 --version & Build-Info ins Log

 Beispiel-Configs: config_example.yaml, secrets.example.txt

 .gitignore (eigene config.yaml/secrets.txt ausgeschlossen)

 Tests: Unit-Tests für Heuristiken & RC-10-Pfadlogik

 Sample-Fixtures: kleine DVD/BD/UHD/TV-Beispielstrukturen

Akzeptanzkriterien (DoD) je Feature

Kurzform (für alle Punkte oben):

Funktioniert auf Win & Linux (sofern relevant)

Dry-Run unterstützt

Ausführliche Logs

Fehlerfälle behandelt (klarer Rückgabecode/Logeintrag)

Dokumentiert im README

Falls „gefährlich“ (Löschen/Umbenennen): Safer-Checks vorhanden