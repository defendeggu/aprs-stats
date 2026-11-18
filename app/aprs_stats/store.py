"""Schreiben in die Datenbank (gemeinsam für Collector und Importer)."""
from datetime import datetime

import psycopg

from .aprs import split_full

# Gleiche Position aus einer anderen Quelle (Export vs. live) gilt als Duplikat,
# wenn sie innerhalb dieses Zeitfensters und dieser Distanz liegt.
DEDUP_SECONDS = 90
DEDUP_METERS = 50

_INSERT_POSITION = """
INSERT INTO positions (packet_id, callsign, ts, lat, lon, geom, speed_kmh, course,
                       altitude_m, comment, symbol, source)
SELECT %(packet_id)s, %(callsign)s, %(ts)s, %(lat)s, %(lon)s,
       ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326),
       %(speed)s, %(course)s, %(alt)s, %(comment)s, %(symbol)s, %(source)s
WHERE NOT EXISTS (
    SELECT 1 FROM positions p
    WHERE p.callsign = %(callsign)s
      AND p.source <> %(source)s
      AND p.ts BETWEEN %(ts)s::timestamptz - make_interval(secs => %(dsec)s)
                   AND %(ts)s::timestamptz + make_interval(secs => %(dsec)s)
      AND ST_DWithin(p.geom::geography,
                     ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography, %(dm)s)
)
ON CONFLICT (callsign, ts) DO NOTHING
"""


def insert_position(
    cur: psycopg.Cursor,
    *,
    callsign: str,
    ts: datetime,
    lat: float,
    lon: float,
    source: str,
    speed: float | None = None,
    course: float | None = None,
    alt: float | None = None,
    comment: str | None = None,
    symbol: str | None = None,
    packet_id: int | None = None,
) -> bool:
    """Gibt True zurück, wenn die Position neu gespeichert wurde."""
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        raise ValueError("Koordinaten ausserhalb des gültigen Bereichs")
    cur.execute(
        _INSERT_POSITION,
        {
            "packet_id": packet_id, "callsign": callsign, "ts": ts, "lat": lat, "lon": lon,
            "speed": speed, "course": course, "alt": alt,
            "comment": (comment or None) and comment[:500], "symbol": symbol,
            "source": source, "dsec": DEDUP_SECONDS, "dm": DEDUP_METERS,
        },
    )
    return cur.rowcount == 1


def ensure_station(cur: psycopg.Cursor, full: str, *, track: bool = False) -> None:
    """Konkrete Station (Rufzeichen + SSID) anlegen, falls noch nicht vorhanden."""
    base, ssid = split_full(full)
    cur.execute(
        "INSERT INTO stations (callsign, ssid, track, auto) VALUES (%s, %s, %s, true) "
        "ON CONFLICT (callsign, ssid) DO NOTHING",
        (base, ssid, track),
    )
