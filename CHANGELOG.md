# Changelog

Alle wichtigen Änderungen an aprs-stats. Das Projekt folgt [Semantic Versioning](https://semver.org/lang/de/):
MAJOR für inkompatible Änderungen, MINOR für neue Funktionen, PATCH für Fehlerbehebungen.

## [0.6.0] – 2026-11-25

### Neu
- **Funk und Internet getrennt:** Positionen und Pakete können über Funk empfangen sein (Quelle `rf`, angeliefert z. B. von RadioMoni). Karte und Rohpakete zeigen den Empfangsweg: Funk, Internet (APRS-IS), Internet (Import aprs.fi), Internet (eigene Bake). Neue Kachel „Positionen Funk · Internet“.
- **Anbindung mit Token** (`APRS_STATS_API_TOKEN`):
  - `POST /api/ingest` nimmt ein Funk-Paket an, gespeichert wie beim Collector nur für eingetragene Stationen. Doppelte Positionen aus Funk und APRS-IS zählen einmal.
  - `GET /api/feed/packets` und `/api/feed/positions` liefern alles inkrementell mit Gemeinde und Kanton.
- API: `/api/stats/summary` liefert `by_source`, `/api/packets` die Quelle.

### Geändert
- Collector und Anlieferung speichern über dieselbe Funktion (`ingest.store_packet`).
- Image: Debian-Sicherheitsupdates beim Build; pip wird nach der Installation entfernt (seine mitgelieferten Bibliotheken hatten bekannte Lücken). Die Tests holen es mit `python -m ensurepip` zurück.
- Neue Spalte `ext_ref` (Kennung beim Lieferanten) in `packets` und `positions`; das Schema wird beim Start erweitert.

## [0.5.0] – 2026-11-21

### Neu
- **Fahrten mit Start- und Zielort**, z. B. „Zuhause → Luzern (LU)“: eigener Ortsname, sonst die Gemeinde.
  Gleicher Start und gleiches Ziel erscheinen als *Rundfahrt*.
- Suchfeld über der Fahrten-Tabelle (Ort oder Gerät).
- Ein Klick auf eine Fahrt markiert auf der Karte Start (grün) und Ziel (rot).
- API: `/api/stats/trips` liefert zusätzlich `from`, `to`, Koordinaten, Ortsnamen und Gemeinden von Start und Ziel.

## [0.4.0] – 2026-11-20

### Neu
- **Besuchte Gemeinden und Kantone** aus den amtlichen Grenzen von swisstopo (swissBOUNDARIES3D).
  Die Grenzen werden beim ersten Start automatisch geladen (abschaltbar mit `BOUNDARIES_AUTOLOAD=0`),
  jede Position wird ihrer Gemeinde zugeordnet.
  - Kacheln „Gemeinden (von 2110)“ und „Kantone (von 26)“ für die aktuelle Auswahl.
  - Neuer Tab **Gemeinden**: Kantone mit Fortschritt, Gemeinden mit Tagen, km, erstem und letztem Besuch, Suche.
  - Kartenebene **Gemeinden**: besuchte Gemeinden eingefärbt (nach Anzahl Tage), Kantonsgrenzen.
  - *Neuste Ausgabe laden* aktualisiert die Grenzen, z. B. nach Gemeindefusionen.
- **Namen für Orte**: In der Orte-Tabelle mit ✎ benennen, von Hand oder mit einem Vorschlag von
  OpenStreetMap Nominatim (nur auf Knopfdruck). Ohne Namen zeigt die Tabelle die Gemeinde.
  Kartenebene **Ortsnamen**.
- API: `/api/stats/gemeinden`, `/api/areas/gemeinden.geojson`, `/api/areas/kantone.geojson`,
  `/api/areas/status`, `/api/areas/load`, `/api/places`, `/api/geocode/reverse`.
- Status-Tab zeigt die Ausgabe der Gemeindegrenzen.

### Geändert
- API-Antworten werden komprimiert (gzip), wenn der Browser es unterstützt.

## [0.3.3] – 2026-11-19

### Behoben
- Geräteauswahl: Der Knopf **keine** wählte zwar alle Geräte ab, Karte und Statistik zeigten aber
  weiterhin alle Geräte, weil eine leere Auswahl als „alle“ galt. Jetzt zeigt **keine** nichts an,
  **alle** zeigt alle Geräte (auch neu hinzukommende).
- API: Der Parameter `calls` unterscheidet jetzt zwischen fehlend (alle Geräte) und leer (`calls=`, keine Geräte).

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
