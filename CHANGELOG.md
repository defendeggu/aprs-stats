# Changelog

Alle wichtigen Änderungen an aprs-stats. Das Projekt folgt [Semantic Versioning](https://semver.org/lang/de/):
MAJOR für inkompatible Änderungen, MINOR für neue Funktionen, PATCH für Fehlerbehebungen.

## [0.2.0] – 2026-11-18

### Neu
- Höhenfilter: Falsche GPS-Höhen nach dem Einschalten (Kaltstart, z. B. 102 m mit anschliessendem
  Hochlaufen) und einzelne Ausreisser werden automatisch verworfen. Gilt für Import, Live-Daten und
  den Bestand (beim Start der Web-App). Die Rohhöhe bleibt in `altitude_raw` erhalten.
- Kartenpopup zeigt verworfene Höhen mit dem ursprünglichen GPS-Wert.
- Status zeigt die Anzahl verworfener Höhen.
- CSV-Export enthält zusätzlich die Spalte `altitude_raw`.

### Geändert
- `POSTGRES_PASSWORD` ist Pflicht; ohne `.env` startet der Stack nicht mehr mit einem Standardpasswort.
- `.gitignore` schliesst `.env*`, Datenbank-Sicherungen und aprs.fi-Exporte aus.
- Collector: Ohne `APRS_IS_LOGIN` wird das zuerst eingetragene Rufzeichen verwendet (vorher das
  alphabetisch erste).
- Fahrten enden mit der letzten Bewegung statt mit der letzten Position (Standzeit zählt nicht mehr).

## [0.1.0] – 2026-11-18

### Neu
- Docker-Stack mit PostgreSQL/PostGIS, Web-App (FastAPI) und APRS-IS-Collector.
- Stationen mit fester SSID oder allen SSIDs, live über APRS-IS verfolgt.
- Import von aprs.fi-Exporten (CSV/JSON) mit Duplikaterkennung zwischen Import und Live-Daten.
- Karte (Spuren, Punkte, Heatmap, letzte Position), Kilometer, Aktivität, Geschwindigkeit/Höhe,
  Fahrten, Orte, Digipeater/iGates, CSV-Export.

[0.2.0]: https://github.com/defendeggu/aprs-stats/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/defendeggu/aprs-stats/releases/tag/v0.1.0
