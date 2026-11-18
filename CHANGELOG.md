# Changelog

Alle wichtigen Änderungen an aprs-stats. Das Projekt folgt [Semantic Versioning](https://semver.org/lang/de/):
MAJOR für inkompatible Änderungen, MINOR für neue Funktionen, PATCH für Fehlerbehebungen.

## [0.3.2] – 2026-11-19

### Neu
- Author und Version auf der Webseite (Fusszeile und Seitentitel) und im README:
  „Author: Adrian S / HB3XVA & Anthropic Claude - vX.Y.Z“.
- API-Endpunkt `/api/version`.

## [0.3.1] – 2026-11-18

### Geändert
- SSID **-0** ist in allen Auswahlfeldern (Station eintragen, Bake) wählbar. Sie bezeichnet nach
  [aprs.org/aprs11/SSIDs.txt](https://www.aprs.org/aprs11/SSIDs.txt) die Primärstation und wird wie
  dort festgelegt ohne SSID angezeigt und gesendet (`HB9ABC` = `HB9ABC-0`). Die Auswahl „keine SSID“
  entfällt, weil sie dasselbe bedeutet.
- SSID-Auswahl zeigt die empfohlene Bedeutung (z. B. „-9 · Mobil (Hauptfahrzeug)“, „-7 · Handfunkgerät“).
- Geräteliste und Tabellen zeigen „-0“ statt „(ohne)“; Tooltip mit der Bedeutung der SSID.

## [0.3.0] – 2026-11-18

### Neu
- Tab **Bake**: eine feste Position (z. B. Heimstation) regelmässig an APRS-IS senden, damit sie auf
  aprs.fi dauerhaft sichtbar ist. Rufzeichen mit SSID, Symbol, Position (Eingabe oder Klick auf die
  Karte), Höhe, Kommentar (max. 43 Zeichen), Intervall (10 min bis 6 h), Positionsunschärfe.
  Paketvorschau, „Jetzt senden“, Pausieren, Link zu aprs.fi.
- Symboltafel mit allen Symbolen der primären und alternativen Tafel, Overlay-Zeichen und Suche
  (aprs.fi symbol set von OH7LZB).
- Karte zeigt die letzte Position mit dem gesendeten APRS-Symbol und aktive Baken.
- Gesendete Baken erscheinen im Paket-Log (Quelle `beacon`).

### Sicherheit
- Gesendet wird nur mit verifiziertem APRS-IS-Login (`APRS_IS_LOGIN` und `APRS_IS_PASSCODE` in
  `.env`) und nur für das Rufzeichen des Logins. Mindestintervall 10 min, frühestens 60 s nach der
  letzten Sendung.

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

[0.3.2]: https://github.com/defendeggu/aprs-stats/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/defendeggu/aprs-stats/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/defendeggu/aprs-stats/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/defendeggu/aprs-stats/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/defendeggu/aprs-stats/releases/tag/v0.1.0
