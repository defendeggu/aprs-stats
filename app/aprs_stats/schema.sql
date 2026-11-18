-- Schema für aprs-stats. Wird beim Start der Web-App ausgeführt (idempotent).

CREATE EXTENSION IF NOT EXISTS postgis;

-- Eingetragene Stationen. ssid = ''  -> Rufzeichen ohne SSID
--                         ssid = '*' -> alle SSIDs des Rufzeichens (Wildcard)
-- track = true: der Collector verfolgt die Station live über APRS-IS.
-- auto  = true: automatisch angelegt (über Wildcard oder Import entdeckt).
CREATE TABLE IF NOT EXISTS stations (
    id          serial PRIMARY KEY,
    callsign    text NOT NULL,
    ssid        text NOT NULL DEFAULT '',
    label       text,
    color       text,
    track       boolean NOT NULL DEFAULT true,
    auto        boolean NOT NULL DEFAULT false,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (callsign, ssid)
);

-- Rohpakete (nur live aus APRS-IS; der aprs.fi-Export enthält keine Rohpakete)
CREATE TABLE IF NOT EXISTS packets (
    id           bigserial PRIMARY KEY,
    received_at  timestamptz NOT NULL,
    source       text NOT NULL,
    callsign     text NOT NULL,
    tocall       text,
    raw          text,
    path         text[],
    digis        text[],
    qconstruct   text,
    igate        text,
    format       text
);
CREATE INDEX IF NOT EXISTS packets_call_ts ON packets (callsign, received_at);

-- Positionen, aus Live-Paketen und Importen
CREATE TABLE IF NOT EXISTS positions (
    id          bigserial PRIMARY KEY,
    packet_id   bigint REFERENCES packets(id) ON DELETE SET NULL,
    callsign    text NOT NULL,
    ts          timestamptz NOT NULL,
    lat         double precision NOT NULL,
    lon         double precision NOT NULL,
    geom        geometry(Point, 4326) NOT NULL,
    speed_kmh   real,
    course      real,
    altitude_m  real,
    comment     text,
    symbol      text,
    source      text NOT NULL,
    UNIQUE (callsign, ts)
);
CREATE INDEX IF NOT EXISTS positions_ts ON positions (ts);
CREATE INDEX IF NOT EXISTS positions_call_ts ON positions (callsign, ts);

-- ab 0.2.0: GPS-Rohhöhe separat, altitude_m ist bereinigt (siehe altitude.py)
ALTER TABLE positions ADD COLUMN IF NOT EXISTS altitude_raw real;
UPDATE positions SET altitude_raw = altitude_m WHERE altitude_raw IS NULL AND altitude_m IS NOT NULL;
CREATE INDEX IF NOT EXISTS positions_geom ON positions USING gist (geom);

-- Zustand des Collectors (eine Zeile)
CREATE TABLE IF NOT EXISTS collector_status (
    id              int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    state           text,
    server          text,
    filter          text,
    login           text,
    connected_since timestamptz,
    last_packet_at  timestamptz,
    packets_total   bigint NOT NULL DEFAULT 0,
    last_error      text,
    updated_at      timestamptz
);

-- Protokoll der Importe
CREATE TABLE IF NOT EXISTS imports (
    id              serial PRIMARY KEY,
    filename        text,
    callsign        text,
    imported_at     timestamptz NOT NULL DEFAULT now(),
    rows_total      int,
    rows_imported   int,
    rows_duplicate  int,
    rows_error      int
);

-- ab 0.3.0: Baken – eigene feste Position regelmässig an APRS-IS senden
CREATE TABLE IF NOT EXISTS beacons (
    id            serial PRIMARY KEY,
    callsign      text NOT NULL,
    ssid          text NOT NULL DEFAULT '',
    symbol_table  text NOT NULL DEFAULT '/',
    symbol_code   text NOT NULL DEFAULT '-',
    lat           double precision NOT NULL,
    lon           double precision NOT NULL,
    altitude_m    real,
    ambiguity     int NOT NULL DEFAULT 0 CHECK (ambiguity BETWEEN 0 AND 4),
    comment       text,
    interval_min  int NOT NULL DEFAULT 30 CHECK (interval_min BETWEEN 10 AND 1440),
    enabled       boolean NOT NULL DEFAULT true,
    next_due_at   timestamptz,
    last_sent_at  timestamptz,
    sent_count    int NOT NULL DEFAULT 0,
    last_packet   text,
    last_error    text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (callsign, ssid)
);
