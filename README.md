# aprs-stats

Author: Adrian S / HB3XVA & Anthropic Claude - v0.5.0

[Changelog](CHANGELOG.md) · Lizenz MIT

Selbst gehostete Statistik für APRS-Positionsdaten, dazu eine feste Position (Bake) für aprs.fi. Man trägt Rufzeichen mit SSID ein. Neue Daten kommen laufend live aus dem APRS-IS-Netz, ältere lassen sich als Export von aprs.fi importieren. Die Weboberfläche zeigt einzelne Funkgeräte (SSIDs) oder alle zusammen: auf der Karte, als Heatmap, in Grafiken und Tabellen.

## Inhalt

- [Funktionen](#funktionen)
- [Schnellstart](#schnellstart)
- [Bedienung](#bedienung)
- [Konfiguration](#konfiguration)
- [Wie die Auswertungen rechnen](#wie-die-auswertungen-rechnen)
- [Aufbau](#aufbau)
- [Betrieb](#betrieb)
- [Sicherheit](#sicherheit)
- [Entwicklung](#entwicklung)

## Funktionen

| Bereich | Was es kann |
|---|---|
| Stationen | Rufzeichen mit fester SSID oder mit *alle SSIDs*. Bei *alle SSIDs* wird jedes Gerät, das sendet, automatisch als eigenes Gerät angelegt. Bezeichnung und Farbe pro Gerät. |
| Live | Dauerhafte Verbindung zu APRS-IS, Filter aus den eingetragenen Stationen. Neue Stationen sind innert 15 s aktiv. |
| Import | CSV oder JSON von [aprs.fi/export](https://aprs.fi/export), mehrere Dateien auf einmal. Doppelte Positionen werden übersprungen, auch zwischen Import und Live-Daten. |
| Karte | Spuren, Punkte, Heatmap, letzte Position, besuchte Gemeinden mit Kantonsgrenzen, benannte Orte. Karten: OpenStreetMap, swisstopo-Landeskarte, swisstopo-Luftbild. |
| Statistik | Kilometer pro Tag/Woche/Monat/Jahr (gestapelt nach Gerät), Aktivität nach Wochentag und Uhrzeit, Geschwindigkeit und Höhe über die Zeit. |
| Fahrten und Orte | Liste der Fahrten mit Start- und Zielort, Distanz, Dauer und Tempo; Aufenthaltsorte mit Stunden und Anzahl Tage. Orte lassen sich benennen, von Hand oder mit einem Vorschlag von OpenStreetMap; ohne Namen steht die Gemeinde da. |
| Gemeinden | Besuchte Gemeinden und Kantone aus den amtlichen Grenzen von swisstopo: Kacheln, Kartenebene, Tabellen mit Tagen, km, erstem und letztem Besuch. |
| Pfade | Digipeater, iGates, Weg ins Netz (Internet, direkt zum iGate, über Digipeater), letzte Rohpakete. |
| Datenqualität | Falsche GPS-Höhen nach dem Einschalten und Ausreisser werden automatisch verworfen. |
| Export | CSV der aktuellen Auswahl. |
| Bake | Eine feste Position (z. B. Heimstation) mit Symbol regelmässig an APRS-IS senden, damit sie auf aprs.fi sichtbar bleibt. |

## Schnellstart

Voraussetzung: Docker mit Compose.

```bash
git clone https://github.com/defendeggu/aprs-stats.git
cd aprs-stats
cp .env.example .env
sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(openssl rand -hex 16)/" .env
docker compose up -d --build
```

Danach <http://localhost:8092> öffnen und unter **Stationen & Import** das erste Rufzeichen eintragen.

## Bedienung

**Station eintragen:** Rufzeichen eingeben und SSID wählen. Die Auswahl zeigt die empfohlene Bedeutung jeder SSID nach [aprs.org/aprs11/SSIDs.txt](https://www.aprs.org/aprs11/SSIDs.txt), z. B. -0 Primärstation, -7 Handfunkgerät, -9 Mobil, -10 Internet/iGate, -13 Wetterstation. -0 wird wie dort festgelegt ohne SSID angezeigt und gesendet: `HB9ABC` und `HB9ABC-0` sind dieselbe Station. Alphanumerische SSIDs mit 1–2 Zeichen (z. B. `-TT`) lassen sich direkt im Rufzeichenfeld eintragen. Mit *alle SSIDs* erscheint jedes Funkgerät (z. B. -7 Handfunkgerät, -9 Auto) automatisch, sobald es sendet. Ist *live verfolgen* aktiv, nimmt der Collector die Station in seinen Filter auf.

**Export importieren:**

1. Auf [aprs.fi/export](https://aprs.fi/export) einloggen, Rufzeichen mit SSID und Zeitraum wählen, Format CSV.
2. aprs.fi erlaubt höchstens 30 Tage pro Export und nur wenige Exporte pro Tag. Am besten Monat für Monat exportieren.
3. In aprs-stats die Datei(en) wählen. Steht das Rufzeichen nicht in der Datei (bei aprs.fi-CSV der Fall), es im Feld darunter angeben, z. B. `HB3XVA-9`.

Erkannte Spalten (Gross-/Kleinschreibung und Einheiten in Klammern egal): `time`/`timestamp`/`date`, `lat`, `lng`/`lon`, `speed`, `course`, `altitude`, `comment`, `name`/`callsign`. Trennzeichen `,` `;` oder Tab, Dezimalkomma geht auch. Zeiten ohne Zeitzone gelten als UTC, Unix-Zeitstempel werden erkannt.

**Auswahl:** Links Zeitraum (24 h bis *Alles* oder eigene Daten) und Geräte wählen. Ein Klick auf das Rufzeichen wählt alle seine SSIDs. *alle* wählt alle Geräte, auch solche, die später dazukommen; *keine* wählt alle ab, Karte und Statistik sind dann leer. Alle Ansichten, Kacheln und der CSV-Export folgen dieser Auswahl.

**Bake (feste Position publizieren):**

1. In `.env` `APRS_IS_LOGIN` (dein Rufzeichen) und `APRS_IS_PASSCODE` (dein persönlicher APRS-IS-Passcode, z. B. aus deinem APRS-Client) eintragen und `docker compose up -d` ausführen. Der Tab **Bake** zeigt oben, ob der Login verifiziert ist.
2. SSID wählen (die SSID unterscheidet die Bake von den mobilen Geräten; üblich für eine feste Station ist keine SSID oder z. B. -10), über **Symboltafel …** das Symbol wählen (primäre Tafel `/`, alternative Tafel `\`, optional mit Overlay-Zeichen 0–9/A–Z) und die Position eingeben oder auf der Karte setzen.
3. Optional Höhe, Kommentar (höchstens 43 Zeichen) und Genauigkeit. Mit *~185 m* oder *~1,8 km* wird die Position absichtlich unscharf gesendet (APRS Position Ambiguity), etwa für die Wohnadresse.
4. Intervall wählen (Standard 30 min) und speichern. Die Bake wird sofort und danach im Intervall gesendet. Unter dem Formular steht das genaue Paket.

Gesendet wird nur mit verifiziertem Login und nur für das Rufzeichen des Logins, mit beliebiger SSID, und nur solange der Stack läuft. Das Paket geht nur ans Internet (APRS-IS), nicht über Funk.

**Fahrten und Orte:** Jede Fahrt zeigt Start und Ziel, z. B. *Zuhause → Luzern (LU)*: den eigenen Ortsnamen, wenn dort einer vergeben ist, sonst die Gemeinde. Endet eine Fahrt in derselben Gemeinde oder am selben Ort, steht *Rundfahrt*. Das Suchfeld filtert nach Ort oder Gerät, z. B. alle Fahrten nach Luzern. Ein Klick auf eine Fahrt zeigt genau diese Fahrt auf der Karte, mit Start (grün) und Ziel (rot). Ein Klick auf einen Ort zoomt dorthin.

**Orte benennen:** In der Orte-Tabelle auf ✎ klicken und einen Namen eingeben, z. B. *Zuhause*. *Vorschlag von OpenStreetMap* fragt [Nominatim](https://nominatim.openstreetmap.org/) nach dem Ort (Gebäude, Geschäft oder Adresse) und trägt den Vorschlag ins Feld ein; er lässt sich vor dem Speichern ändern. Nur dieser Knopf schickt Koordinaten nach aussen. Der Name gilt für alle Orte, deren Mittelpunkt innerhalb des gewählten Radius liegt, also auch in anderen Zeiträumen. Ein leeres Feld oder *Name entfernen* löscht ihn. Auf der Karte zeigt die Ebene *Ortsnamen* alle benannten Orte.

**Gemeinden:** Beim ersten Start lädt aprs-stats die Gemeinde- und Kantonsgrenzen ([swissBOUNDARIES3D](https://www.swisstopo.admin.ch/de/landschaftsmodell-swissboundaries3d), rund 37 MB) im Hintergrund und ordnet jede Position einer Gemeinde zu. Neue Positionen werden laufend zugeordnet. Die Kacheln zeigen, wie viele der 2110 Gemeinden und 26 Kantone die Auswahl besucht hat. Ein Klick darauf öffnet den Tab **Gemeinden**: Kantone mit Fortschrittsbalken (ein Klick filtert die Gemeinden), Gemeinden mit Tagen, km, erstem und letztem Besuch (ein Klick zeigt den Umriss auf der Karte). Auf der Karte färbt die Ebene *Gemeinden* besuchte Gemeinden ein (je kräftiger, desto mehr Tage) und zeigt die Kantonsgrenzen. Swisstopo gibt jedes Jahr eine neue Ausgabe heraus, z. B. nach Gemeindefusionen. *Neuste Ausgabe laden* oben im Tab ersetzt die Grenzen und ordnet alle Positionen neu zu.

## Konfiguration

Alle Einstellungen stehen in `.env` (Vorlage: [.env.example](.env.example)).

| Variable | Bedeutung | Standard |
|---|---|---|
| `POSTGRES_PASSWORD` | Passwort der Datenbank, **Pflicht**, nur Buchstaben und Ziffern | – |
| `APRS_STATS_PORT` | Port der Oberfläche | `8092` |
| `APRS_IS_LOGIN` | Login bei APRS-IS; leer = zuerst eingetragenes Rufzeichen | – |
| `APRS_IS_PASSCODE` | APRS-IS-Passcode; `-1` genügt zum Mitlesen, für Baken der persönliche Passcode | `-1` |
| `APRS_IS_SERVER` / `APRS_IS_PORT` | APRS-IS-Server | `rotate.aprs2.net` / `14580` |
| `TZ` | Zeitzone für Tage, Wochentage, Uhrzeiten | `Europe/Zurich` |
| `TRIP_GAP_MINUTES` | Pause, die eine Fahrt beendet | `20` |
| `MAX_PLAUSIBLE_KMH` | schnellere Sprünge gelten als GPS-Fehler | `250` |
| `LOG_LEVEL` | Log-Stufe des Collectors | `INFO` |
| `BOUNDARIES_AUTOLOAD` | Gemeindegrenzen beim ersten Start automatisch laden; `0` = nur auf Knopfdruck | `1` |
| `NOMINATIM_URL` | Nominatim-Server für Namensvorschläge | `https://nominatim.openstreetmap.org` |
| `NOMINATIM_EMAIL` | optionale Kontaktadresse, die bei Nominatim-Anfragen mitgeht | – |

Ohne Bake sendet aprs-stats nichts ins APRS-Netz; für das reine Mitlesen braucht es keinen gültigen Passcode.

Verbindungen nach aussen: APRS-IS (Collector), die Kartenkacheln (Browser), einmal pro Ausgabe der Download der Grenzen von data.geo.admin.ch (nur ein Download, es gehen keine eigenen Daten hinaus) und Nominatim nur beim Klick auf *Vorschlag von OpenStreetMap*.

## Wie die Auswertungen rechnen

- **Kilometer:** Summe der Distanzen zwischen aufeinanderfolgenden Positionen desselben Geräts. Nicht gezählt werden Abstände über 20 min (Pause), Sprünge schneller als 250 km/h (GPS-Fehler) und Bewegungen unter 50 m (Zittern im Stand). Sind zwei Geräte gleichzeitig unterwegs (z. B. Auto und Handfunkgerät), zählen beide.
- **Fahrten:** Eine Pause von mehr als 20 min beendet eine Fahrt. Angezeigt werden Fahrten ab 1 km. Die Fahrt endet mit der letzten Bewegung. Start ist die erste Position der Fahrt (meist noch im Stand), Ziel die letzte Position mit Bewegung. Ein Ortsname gilt für Start oder Ziel, wenn der Punkt höchstens den Radius des Namens (mindestens 150 m) davon entfernt liegt. Liegt das Ziel weiter weg vom Parkplatz als dieser Radius, z. B. weil der Tracker beim Einparken nicht mehr gesendet hat, steht die Gemeinde da.
- **Orte:** Standpunkte (unter 5 km/h) werden mit DBSCAN gruppiert (Radius wählbar, Standard 150 m, mindestens 4 Punkte). Die Aufenthaltsdauer zählt pro Position höchstens 30 min.
- **Höhe:** Nach dem Einschalten melden viele Tracker zuerst eine zu tiefe Höhe (z. B. 102 m) und laufen dann über einige Minuten zur echten Höhe hoch. Unterwegs gibt es nach einem kurzen Neustart einzelne Ausreisser. Eine Höhe gilt als plausibel, wenn sie höchstens 30 m plus 12 % der horizontalen Distanz von der letzten plausiblen Höhe abweicht (Strassen sind selten steiler). Beginnt eine Fahrt dort, wo die letzte Fahrt endete, dient deren Höhe als Referenz. Sonst ist die Referenz der Punkt mit der Höhe am nächsten beim Median der Fahrt. Verworfene Höhen fehlen in Grafiken und Kacheln, die Rohwerte bleiben in `altitude_raw` erhalten und erscheinen im Kartenpopup und im CSV-Export. Details: [altitude.py](app/aprs_stats/altitude.py).
- **Pfade:** APRS-IS dedupliziert. Pro Paket sieht man meist nur den ersten Weg ins Netz, nicht alle Digipeater und iGates, die es gehört haben. Der aprs.fi-Export enthält keine Pfade, Pfadauswertungen gibt es deshalb nur für Live-Daten.
- **Gemeinden und Kantone:** Jede Position wird dem Hoheitsgebiet zugeordnet, in dem sie liegt (Punkt in Fläche, PostGIS). Gezählt werden die Schweizer Gemeinden. Seen in Kantonsbesitz (z. B. *Zürichsee (ZH)*), Kommunanzen, Liechtenstein, Büsingen und Campione erscheinen in der Liste, zählen aber nicht zu den 2110 Gemeinden. Seen zählen zum Kanton. Die km eines Abschnitts zählen zur Gemeinde, in der er endet. Wer nur durchfährt, ohne dass dort eine Position gesendet wird, hat die Gemeinde nicht besucht. Bei einem langen Sendeintervall fehlen deshalb kleine Gemeinden. Die Karte zeigt vereinfachte Grenzen (20 m), gezählt wird mit den genauen.
- **Ortsnamen:** Ein Name gilt für einen Ort, wenn dessen Mittelpunkt höchstens den Radius des Namens (beim Speichern der gewählte Radius, mindestens 150 m) oder den aktuell gewählten Radius vom gespeicherten Punkt entfernt liegt. Liegen mehrere Namen in Reichweite, gewinnt der nächste.
- **Duplikate:** Eine Position gilt als doppelt, wenn dasselbe Gerät zur selben Sekunde schon eine hat oder wenn eine Position aus der anderen Quelle (Import oder live) höchstens 90 s und 50 m entfernt liegt.

## Aufbau

```
APRS-IS (rotate.aprs2.net:14580)        aprs.fi-Export (CSV/JSON)
          │ Filter b/RUFZEICHEN*                  │ Upload
          ▼                                      ▼
   ┌─────────────┐                      ┌────────────────┐
   │  collector  │                      │      web       │◄── Browser :8092
   │ Python,     │                      │ FastAPI, API,  │
   │ aprslib     │                      │ Oberfläche     │
   └──────┬──────┘                      └───────┬────────┘
          │                                     │
          └──────────────►┌──────────┐◄─────────┘
                          │    db    │
                          │ Postgres │
                          │ PostGIS  │
                          └──────────┘
```

| Dienst | Container | Aufgabe |
|---|---|---|
| `db` | `aprs-stats-db` | PostgreSQL 16 mit PostGIS, Volume `db-data`, nur im internen Netz |
| `web` | `aprs-stats-web` | Oberfläche (Leaflet, Leaflet.heat, Chart.js, lokal ausgeliefert) und API |
| `collector` | `aprs-stats-collector` | APRS-IS-Verbindung, speichert Pakete und Positionen, sendet Baken |

Tabellen: `stations`, `packets` (Rohpakete mit Pfad, Digipeatern, iGate; gesendete Baken mit Quelle `beacon`), `positions` (PostGIS-Punkte, bereinigte und rohe Höhe, Gebiet), `beacons`, `collector_status`, `imports`, `areas` und `kantone` (Grenzen von swisstopo), `boundaries_meta`, `place_names`. Das Schema wird beim Start angelegt und erweitert ([schema.sql](app/aprs_stats/schema.sql)).

Code in [app/aprs_stats/](app/aprs_stats/):

| Datei | Inhalt |
|---|---|
| `web.py` | API und Auslieferung der Oberfläche |
| `collector.py` | APRS-IS-Client mit Neuverbindung, Statusmeldung und Senden der Baken |
| `importer.py` | Einlesen von CSV/JSON, Spaltenerkennung |
| `stats.py` | SQL für Kilometer, Fahrten, Orte, Aktivität, Pfade, Gemeinden und Kantone |
| `boundaries.py` | Laden der swisstopo-Grenzen (GeoPackage ohne GDAL), Zuordnung der Positionen |
| `geocode.py` | Namensvorschläge über Nominatim (höchstens 1 Anfrage pro Sekunde) |
| `altitude.py` | Höhenfilter |
| `aprs.py` | Rufzeichen, Filter, Pfadzerlegung, Positionspakete für Baken |
| `store.py` | Speichern mit Duplikaterkennung |
| `static/` | Oberfläche (HTML, CSS, JavaScript, Bibliotheken) |

## Betrieb

Der Stack liegt im Dockge-Verzeichnis und lässt sich dort oder mit `docker compose` steuern.

```bash
docker compose ps                     # Zustand
docker compose logs -f collector      # empfangene Pakete live
docker compose up -d --build          # nach einem Update neu bauen
```

**Sicherung:**

```bash
docker compose exec -T db pg_dump -U aprs aprs | gzip > aprs-stats-$(date +%F).sql.gz
```

**Wiederherstellung** (in eine leere Datenbank):

```bash
gunzip -c aprs-stats-JJJJ-MM-TT.sql.gz | docker compose exec -T db psql -U aprs aprs
```

Sicherungen und Exporte gehören nicht ins Repository; die `.gitignore` schliesst sie aus.

## Sicherheit

- Passwörter und der APRS-IS-Passcode stehen nur in `.env`. Diese Datei ist in `.gitignore` und wird nie committet. `docker-compose.yml` enthält keine Standardpasswörter: Ohne `POSTGRES_PASSWORD` startet der Stack nicht.
- Die Datenbank ist nur im internen Docker-Netz erreichbar, nicht vom Host.
- Die Container laufen schreibgeschützt, ohne Linux-Capabilities und ohne Rechteausweitung; die Web-App als eigener Benutzer.
- Baken werden nur mit verifiziertem Login und nur für das Rufzeichen des Logins gesendet, frühestens alle 10 min. Wer die Oberfläche erreicht, kann aber Baken für dieses Rufzeichen anlegen. Ein weiterer Grund, sie nicht offen ins Internet zu stellen.
- Die Oberfläche hat **keine Anmeldung**. Sie ist für das Heimnetz gedacht und darf nicht direkt ins Internet. Für den Zugriff von aussen einen Reverse-Proxy mit Anmeldung oder ein VPN davorschalten.
- Positionsdaten sind persönliche Daten. Exporte und Sicherungen entsprechend aufbewahren.
- Namensvorschläge schicken die Koordinaten eines Orts an OpenStreetMap Nominatim, z. B. die der Wohnadresse. Das passiert nur beim Klick auf *Vorschlag von OpenStreetMap*. Wer das nicht will, gibt Namen von Hand ein oder setzt `NOMINATIM_URL` auf eine eigene Instanz.

## Entwicklung

Tests laufen im Image:

```bash
docker build -t aprs-stats:latest app
docker run --rm -v "$PWD/tests:/tests:ro" -u root aprs-stats:latest \
  sh -c "pip install -q pytest && python -m pytest -q -p no:cacheprovider /tests"
```

API-Dokumentation (OpenAPI): <http://localhost:8092/docs>

Versionierung nach [Semantic Versioning](https://semver.org/lang/de/). Die Version steht in [app/aprs_stats/\_\_init\_\_.py](app/aprs_stats/__init__.py) (die Webseite zeigt sie in der Fusszeile, die API unter `/api/version`). Bei einer neuen Version auch die Author-Zeile oben in diesem README anpassen. Änderungen im [CHANGELOG](CHANGELOG.md), Releases als Git-Tags `vX.Y.Z`.

## Lizenz

MIT, siehe [LICENSE](LICENSE). Mitgelieferte Bibliotheken: Leaflet 1.9.4 (BSD-2), Leaflet.heat 0.2.0 (BSD-2), Chart.js 4.4.1 (MIT).
APRS-Symbole: [aprs.fi symbol set](https://github.com/hessu/aprs-symbols) von Heikki Hannikainen, OH7LZB; Symbolbeschreibungen: [aprs-symbol-index](https://github.com/hessu/aprs-symbol-index) (CC BY-SA 4.0).
