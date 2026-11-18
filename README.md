# aprs-stats

Eigene Auswertung von APRS-Positionsdaten: Rufzeichen mit SSID eintragen, die Daten kommen laufend live aus dem APRS-IS-Netz, ältere Daten lassen sich als Export (z. B. von aprs.fi) importieren. Die Weboberfläche zeigt einzelne Geräte (SSIDs) oder alle zusammen auf der Karte, als Heatmap und in Grafiken.

## Funktionen

- **Stationen:** Rufzeichen mit fester SSID oder mit *alle SSIDs*. Bei *alle SSIDs* erscheint jedes Funkgerät des Rufzeichens automatisch als eigenes Gerät, sobald es sendet. Bezeichnung und Farbe pro Gerät.
- **Live:** Der Collector bleibt mit APRS-IS verbunden (`rotate.aprs2.net:14580`), filtert auf die eingetragenen Stationen und speichert jedes Paket mit Pfad. Ändern sich die Stationen, verbindet er sich innert 15 s mit dem neuen Filter neu.
- **Import:** CSV oder JSON, z. B. von [aprs.fi/export](https://aprs.fi/export). Die Spalten werden über ihre Namen erkannt (`time`, `lat`, `lng`, `speed`, `course`, `altitude`, `comment`, `name` …). Zeiten ohne Zeitzone gelten als UTC. Enthält die Datei kein Rufzeichen, gibt man es beim Import an. Doppelte Positionen werden übersprungen, auch zwischen Import und Live-Daten (gleiches Gerät, höchstens 90 s und 50 m auseinander).
- **Karte:** Spuren, Punkte, Heatmap und letzte Position, wahlweise auf OpenStreetMap, swisstopo-Landeskarte oder swisstopo-Luftbild.
- **Statistik:** gefahrene Kilometer pro Tag, Woche, Monat oder Jahr (gestapelt nach Gerät), Aktivität nach Wochentag und Uhrzeit, Geschwindigkeit und Höhe über die Zeit.
- **Fahrten und Orte:** Fahrten (eine Pause von mehr als 20 min beendet eine Fahrt) und Aufenthaltsorte (Standpunkte mit DBSCAN gruppiert).
- **Pfade:** Digipeater, iGates und Art des Wegs ins Netz (Internet, direkt zum iGate, über Digipeater) sowie die letzten Rohpakete.
- **Export:** CSV der aktuellen Auswahl.

Alle Ansichten folgen der Auswahl links: Zeitraum und Geräte. Keine Auswahl bedeutet alle Geräte.

## Aufbau

| Dienst | Aufgabe |
|---|---|
| `db` | PostgreSQL 16 mit PostGIS, nur im internen Netz |
| `web` | FastAPI: API und Oberfläche (Leaflet, leaflet.heat, Chart.js, lokal ausgeliefert) |
| `collector` | Python-Prozess mit APRS-IS-Verbindung, parst mit `aprslib` |

Tabellen: `stations`, `packets` (Rohpakete mit Pfad, Digipeatern, iGate), `positions` (PostGIS-Punkte), `collector_status`, `imports`. Distanzen, Fahrten und Orte werden bei jeder Abfrage aus den Positionen berechnet. Sprünge schneller als 250 km/h gelten als GPS-Fehler, Bewegungen unter 50 m als Zittern im Stand.

## Betrieb

```bash
cp .env.example .env        # Passwort und Login anpassen
docker compose up -d --build
```

Oberfläche: <http://localhost:8092> (Port über `APRS_STATS_PORT`). Der Stack liegt im Dockge-Verzeichnis und erscheint dort als `aprs-stats`.

Einstellungen in `.env`:

| Variable | Bedeutung | Standard |
|---|---|---|
| `APRS_STATS_PORT` | Port der Oberfläche | `8092` |
| `POSTGRES_PASSWORD` | Passwort der Datenbank | – |
| `APRS_IS_LOGIN` | Login bei APRS-IS (leer: erstes eingetragenes Rufzeichen) | – |
| `APRS_IS_PASSCODE` | Passcode; `-1` genügt zum Mitlesen | `-1` |
| `APRS_IS_SERVER`, `APRS_IS_PORT` | APRS-IS-Server | `rotate.aprs2.net`, `14580` |
| `TZ` | Zeitzone für Tage, Wochentage und Uhrzeiten | `Europe/Zurich` |
| `TRIP_GAP_MINUTES` | Pause, die eine Fahrt beendet | `20` |
| `MAX_PLAUSIBLE_KMH` | schnellere Sprünge gelten als GPS-Fehler | `250` |

Die Oberfläche hat keine Anmeldung. Sie ist für das Heimnetz gedacht und sollte nicht direkt ins Internet gestellt werden.

Sicherung der Datenbank:

```bash
docker compose exec -T db pg_dump -U aprs aprs | gzip > aprs-stats-$(date +%F).sql.gz
```

## Hinweise zu den Daten

- APRS-IS dedupliziert: Pro Paket sieht man meist nur den ersten Weg ins Netz, nicht alle Digipeater und iGates, die es gehört haben.
- Der aprs.fi-Export enthält keine Pfade. Digipeater- und iGate-Auswertungen gibt es deshalb nur für Live-Daten.
- aprs.fi exportiert höchstens 30 Tage pro Abfrage und begrenzt die Anzahl Exporte. Am besten Monat für Monat exportieren und die Dateien gesammelt importieren (mehrere Dateien auf einmal sind möglich).

## Entwicklung

Tests (laufen im Image):

```bash
docker compose build web
docker run --rm -v "$PWD/tests:/tests:ro" -u root aprs-stats:latest \
  sh -c "pip install -q pytest && python -m pytest -q -p no:cacheprovider /tests"
```

API-Dokumentation: <http://localhost:8092/docs>

## Lizenz

MIT, siehe [LICENSE](LICENSE). Mitgelieferte Bibliotheken: Leaflet (BSD-2), Leaflet.heat (BSD-2), Chart.js (MIT).
