"""Auswertungen. Alle Funktionen nehmen einen Filter (Rufzeichen, Zeitraum) entgegen."""
import math
import os
from dataclasses import dataclass
from datetime import datetime

TZ = os.environ.get("TZ", "Europe/Zurich")

# Parameter für Distanz und Fahrten
TRIP_GAP_S = int(os.environ.get("TRIP_GAP_MINUTES", "20")) * 60   # Pause, die eine Fahrt beendet
MAX_KMH = float(os.environ.get("MAX_PLAUSIBLE_KMH", "250"))       # schnellere Sprünge = GPS-Fehler
MIN_SEG_KM = 0.05                                                  # GPS-Zittern im Stand ignorieren


@dataclass
class Filter:
    calls: list[str] | None                                        # None = alle, [] = keine
    start: datetime | None = None
    end: datetime | None = None

    def where(self, ts_col: str = "ts", call_col: str = "callsign") -> tuple[str, dict]:
        parts, params = ["true"], {}
        if self.calls is not None:
            parts.append(f"{call_col} = ANY(%(calls)s)")
            params["calls"] = self.calls
        if self.start:
            parts.append(f"{ts_col} >= %(start)s")
            params["start"] = self.start
        if self.end:
            parts.append(f"{ts_col} < %(end)s")
            params["end"] = self.end
        return " AND ".join(parts), params


def _segments_cte(where: str) -> str:
    """CTE `seg`: aufeinanderfolgende Positionen pro Rufzeichen mit Distanz und Zeitabstand,
    plus `km_ok` (plausible Fahrstrecke) und `trip` (Fahrtnummer)."""
    return f"""
    WITH p AS (
        SELECT callsign, ts, geom, speed_kmh, area,
               lag(ts)   OVER w AS pts,
               lag(geom) OVER w AS pgeom
        FROM positions WHERE {where}
        WINDOW w AS (PARTITION BY callsign ORDER BY ts)
    ), q AS (
        SELECT *,
               CASE WHEN pgeom IS NULL THEN NULL
                    ELSE ST_Distance(geom::geography, pgeom::geography) / 1000.0 END AS km,
               EXTRACT(EPOCH FROM ts - pts) AS dt
        FROM p
    ), seg AS (
        SELECT *,
               CASE WHEN dt > 0 AND dt <= {TRIP_GAP_S} AND km >= {MIN_SEG_KM}
                         AND km / (dt / 3600.0) <= {MAX_KMH} THEN km ELSE 0 END AS km_ok,
               SUM(CASE WHEN dt IS NULL OR dt > {TRIP_GAP_S} THEN 1 ELSE 0 END)
                   OVER (PARTITION BY callsign ORDER BY ts) AS trip
        FROM q
    )
    """


def summary(c, f: Filter) -> dict:
    where, params = f.where()
    row = c.execute(
        f"""SELECT count(*) AS points, count(DISTINCT callsign) AS devices,
                   min(ts) AS first, max(ts) AS last,
                   max(speed_kmh) AS max_speed, max(altitude_m) AS max_alt, min(altitude_m) AS min_alt,
                   count(DISTINCT (ts AT TIME ZONE %(tz)s)::date) AS days
            FROM positions WHERE {where}""",
        {**params, "tz": TZ},
    ).fetchone()
    km = c.execute(
        _segments_cte(where) + "SELECT coalesce(sum(km_ok), 0) AS km FROM seg", params
    ).fetchone()["km"]
    pw, pp = f.where("received_at")
    packets = c.execute(f"SELECT count(*) AS n FROM packets WHERE {pw}", pp).fetchone()["n"]
    return {**row, "km": float(km), "packets": packets}


def distance(c, f: Filter, bucket: str) -> list[dict]:
    where, params = f.where()
    rows = c.execute(
        _segments_cte(where)
        + """SELECT to_char(date_trunc(%(bucket)s, ts AT TIME ZONE %(tz)s), %(fmt)s) AS bucket,
                    callsign, round(sum(km_ok)::numeric, 2)::float AS km,
                    count(*) AS points
             FROM seg GROUP BY 1, 2 ORDER BY 1, 2""",
        {**params, "bucket": bucket, "tz": TZ, "fmt": _bucket_fmt(bucket)},
    ).fetchall()
    return rows


def _bucket_fmt(bucket: str) -> str:
    return {"hour": "YYYY-MM-DD HH24:00", "day": "YYYY-MM-DD", "week": "IYYY-\"W\"IW",
            "month": "YYYY-MM", "year": "YYYY"}[bucket]


def activity(c, f: Filter) -> list[dict]:
    """Anzahl Positionen nach Wochentag (1 = Mo) und Stunde (Ortszeit)."""
    where, params = f.where()
    return c.execute(
        f"""SELECT EXTRACT(ISODOW FROM ts AT TIME ZONE %(tz)s)::int AS dow,
                   EXTRACT(HOUR FROM ts AT TIME ZONE %(tz)s)::int AS hour,
                   count(*) AS n
            FROM positions WHERE {where} GROUP BY 1, 2""",
        {**params, "tz": TZ},
    ).fetchall()


def timeline(c, f: Filter, limit: int = 5000) -> list[dict]:
    """Geschwindigkeit und Höhe über die Zeit (ausgedünnt auf höchstens `limit` Punkte)."""
    where, params = f.where()
    n = c.execute(f"SELECT count(*) AS n FROM positions WHERE {where}", params).fetchone()["n"]
    step = max(1, math.ceil(n / limit))
    return c.execute(
        f"""SELECT callsign, ts, speed_kmh, altitude_m FROM (
                SELECT callsign, ts, speed_kmh, altitude_m, row_number() OVER (ORDER BY ts) AS rn
                FROM positions WHERE {where}) x
            WHERE rn %% %(step)s = 0 ORDER BY ts""",
        {**params, "step": step},
    ).fetchall()


def trips(c, f: Filter, min_km: float = 1.0, limit: int = 300) -> list[dict]:
    where, params = f.where()
    return c.execute(
        _segments_cte(where)
        + """SELECT callsign, min(ts) AS start,
                    max(ts) FILTER (WHERE km_ok > 0) AS "end",
                    round(sum(km_ok)::numeric, 2)::float AS km, count(*) AS points,
                    max(speed_kmh) AS max_speed,
                    EXTRACT(EPOCH FROM max(ts) FILTER (WHERE km_ok > 0) - min(ts))::int AS seconds
             FROM seg GROUP BY callsign, trip
             HAVING sum(km_ok) >= %(min_km)s
             ORDER BY min(ts) DESC LIMIT %(limit)s""",
        {**params, "min_km": min_km, "limit": limit},
    ).fetchall()


def places(c, f: Filter, eps_m: float = 150, min_points: int = 4, limit: int = 50) -> list[dict]:
    """Aufenthaltsorte: Standpunkte (langsam) mit DBSCAN gruppieren."""
    where, params = f.where()
    avg = c.execute(f"SELECT avg(lat) AS lat FROM positions WHERE {where}", params).fetchone()["lat"]
    if avg is None:
        return []
    eps = eps_m / max(0.2, math.cos(math.radians(avg)))  # Meter -> Web-Mercator-Einheiten
    return c.execute(
        f"""
        WITH p AS (
            SELECT callsign, ts, geom, speed_kmh,
                   lead(ts) OVER (PARTITION BY callsign ORDER BY ts) AS nts
            FROM positions WHERE {where}
        ), s AS (
            SELECT * FROM p WHERE speed_kmh IS NULL OR speed_kmh < 5
        ), cl AS (
            SELECT *, ST_ClusterDBSCAN(ST_Transform(geom, 3857), eps := %(eps)s,
                                       minpoints := %(minpts)s) OVER () AS cid
            FROM s
        )
        , pl AS (
            SELECT cid, count(*) AS points,
                   ST_Y(ST_Centroid(ST_Collect(geom))) AS lat,
                   ST_X(ST_Centroid(ST_Collect(geom))) AS lon,
                   min(ts) AS first, max(ts) AS last,
                   count(DISTINCT (ts AT TIME ZONE %(tz)s)::date) AS days,
                   round((sum(LEAST(coalesce(EXTRACT(EPOCH FROM nts - ts), 0), 1800)) / 3600.0)::numeric, 1)::float
                       AS hours,
                   array_agg(DISTINCT callsign) AS callsigns
            FROM cl WHERE cid IS NOT NULL
            GROUP BY cid ORDER BY hours DESC, points DESC LIMIT %(limit)s
        )
        SELECT pl.*, n.id AS name_id, n.name, n.source AS name_source,
               a.name AS gemeinde, k.abbr AS kanton
        FROM pl
        LEFT JOIN LATERAL (
            SELECT n.id, n.name, n.source,
                   ST_Distance(n.geom::geography, ST_SetSRID(ST_MakePoint(pl.lon, pl.lat), 4326)::geography) AS d
            FROM place_names n
            WHERE ST_DWithin(n.geom::geography, ST_SetSRID(ST_MakePoint(pl.lon, pl.lat), 4326)::geography,
                             greatest(n.radius_m, %(eps_m)s))
            ORDER BY d LIMIT 1) n ON true
        LEFT JOIN LATERAL (
            SELECT name, kanton_nr FROM areas
            WHERE ST_Intersects(geom, ST_SetSRID(ST_MakePoint(pl.lon, pl.lat), 4326))
            ORDER BY (kind = 'Gemeindegebiet') DESC LIMIT 1) a ON true
        LEFT JOIN kantone k ON k.nr = a.kanton_nr
        ORDER BY pl.hours DESC, pl.points DESC
        """,
        {**params, "eps": eps, "eps_m": eps_m, "minpts": min_points, "tz": TZ, "limit": limit},
    ).fetchall()


def paths(c, f: Filter) -> dict:
    """Digipeater, iGates und Art des Wegs ins Netz (nur Live-Pakete haben Pfade)."""
    where, params = f.where("received_at")
    base = f"SELECT * FROM packets WHERE {where} AND source = 'aprs_is'"
    digis = c.execute(
        f"""SELECT d AS call, count(*) AS n, min(received_at) AS first, max(received_at) AS last
            FROM ({base}) p, unnest(p.digis) AS d GROUP BY d ORDER BY n DESC LIMIT 50""",
        params,
    ).fetchall()
    igates = c.execute(
        f"""SELECT igate AS call, count(*) AS n, min(received_at) AS first, max(received_at) AS last
            FROM ({base}) p WHERE igate IS NOT NULL GROUP BY igate ORDER BY n DESC LIMIT 50""",
        params,
    ).fetchall()
    routes = c.execute(
        f"""SELECT CASE
                     WHEN qconstruct IN ('qAC', 'qAU', 'qAS') OR 'TCPIP*' = ANY(path) OR 'TCPIP' = ANY(path)
                         THEN 'Internet (direkt)'
                     WHEN coalesce(cardinality(digis), 0) = 0 THEN 'Funk, direkt zum iGate'
                     WHEN cardinality(digis) = 1 THEN 'Funk, über 1 Digipeater'
                     ELSE 'Funk, über ' || cardinality(digis) || ' Digipeater'
                   END AS route, count(*) AS n
            FROM ({base}) p GROUP BY 1 ORDER BY n DESC""",
        params,
    ).fetchall()
    formats = c.execute(
        f"SELECT coalesce(format, '?') AS format, count(*) AS n FROM ({base}) p GROUP BY 1 ORDER BY n DESC",
        params,
    ).fetchall()
    return {"digis": digis, "igates": igates, "routes": routes, "formats": formats}


# --- Gemeinden und Kantone (Grenzen aus boundaries.py) ------------------------

def area_counts(c, f: Filter) -> dict:
    """Anzahl besuchter Gemeinden (nur Schweizer Gemeindegebiet) und Kantone."""
    where, params = f.where("p.ts", "p.callsign")
    return c.execute(
        f"""SELECT count(DISTINCT a.id) FILTER (WHERE a.kind = 'Gemeindegebiet' AND a.country = 'CH') AS gemeinden,
                   count(DISTINCT a.kanton_nr) AS kantone,
                   (SELECT count(*) FROM areas WHERE kind = 'Gemeindegebiet' AND country = 'CH') AS gemeinden_total,
                   (SELECT count(*) FROM kantone) AS kantone_total
            FROM positions p JOIN areas a ON a.id = p.area WHERE {where}""",
        params,
    ).fetchone()


def _area_visits_cte(where: str) -> str:
    return _segments_cte(where) + f""",
    v AS (
        SELECT area, min(ts) AS first, max(ts) AS last, count(*) AS points,
               count(DISTINCT (ts AT TIME ZONE %(tz)s)::date) AS days,
               round(sum(km_ok)::numeric, 1)::float AS km,
               array_agg(DISTINCT callsign) AS callsigns
        FROM seg WHERE area > 0 GROUP BY area
    )
    """


def gemeinden(c, f: Filter) -> list[dict]:
    """Besuchte Gebiete (Gemeinden, Seen, Kommunanzen) mit Besuchen; km zählen zum Gebiet des Endpunkts."""
    where, params = f.where()
    return c.execute(
        _area_visits_cte(where)
        + """SELECT a.id, a.bfs_nr, a.name, a.kind, a.country, a.kanton_nr, k.abbr AS kanton,
                    v.first, v.last, v.points, v.days, v.km, v.callsigns,
                    ST_XMin(b) AS west, ST_YMin(b) AS south, ST_XMax(b) AS east, ST_YMax(b) AS north
             FROM v JOIN areas a ON a.id = v.area
             LEFT JOIN kantone k ON k.nr = a.kanton_nr,
             LATERAL (SELECT ST_Envelope(a.geom_s) AS b) e
             ORDER BY v.days DESC, v.points DESC""",
        {**params, "tz": TZ},
    ).fetchall()


def kantone(c, f: Filter) -> list[dict]:
    """Alle Kantone mit Anzahl besuchter Gemeinden; unbesuchte mit points = 0."""
    where, params = f.where()
    return c.execute(
        _area_visits_cte(where)
        + """, kv AS (
                SELECT a.kanton_nr AS nr,
                       count(*) FILTER (WHERE a.kind = 'Gemeindegebiet') AS gemeinden,
                       min(v.first) AS first, max(v.last) AS last, sum(v.points) AS points,
                       round(sum(v.km)::numeric, 1)::float AS km
                FROM v JOIN areas a ON a.id = v.area WHERE a.kanton_nr IS NOT NULL GROUP BY 1
             ), kt AS (
                SELECT kanton_nr AS nr, count(*) AS total FROM areas
                WHERE kind = 'Gemeindegebiet' AND country = 'CH' GROUP BY 1
             )
             SELECT k.nr, k.abbr, k.name, coalesce(kv.gemeinden, 0) AS gemeinden, coalesce(kt.total, 0) AS total,
                    kv.first, kv.last, coalesce(kv.points, 0) AS points, coalesce(kv.km, 0) AS km
             FROM kantone k LEFT JOIN kv ON kv.nr = k.nr LEFT JOIN kt ON kt.nr = k.nr
             ORDER BY coalesce(kv.points, 0) = 0, kv.last DESC NULLS LAST, k.nr""",
        {**params, "tz": TZ},
    ).fetchall()


def gemeinden_geojson(c, f: Filter) -> dict:
    """Besuchte Gebiete als GeoJSON (vereinfachte Grenzen) für die Karte."""
    where, params = f.where()
    row = c.execute(
        _area_visits_cte(where)
        + """SELECT json_build_object('type', 'FeatureCollection', 'features', coalesce(json_agg(json_build_object(
                    'type', 'Feature',
                    'geometry', ST_AsGeoJSON(a.geom_s, 5)::json,
                    'properties', json_build_object('id', a.id, 'name', a.name, 'kind', a.kind,
                        'kanton', k.abbr, 'days', v.days, 'points', v.points, 'km', v.km,
                        'first', v.first, 'last', v.last)
                 )), '[]'::json)) AS fc
             FROM v JOIN areas a ON a.id = v.area LEFT JOIN kantone k ON k.nr = a.kanton_nr""",
        {**params, "tz": TZ},
    ).fetchone()
    return row["fc"]


def kantone_geojson(c) -> dict:
    return c.execute(
        """SELECT json_build_object('type', 'FeatureCollection', 'features', coalesce(json_agg(json_build_object(
                'type', 'Feature', 'geometry', ST_AsGeoJSON(ST_Boundary(geom_s), 4)::json,
                'properties', json_build_object('nr', nr, 'abbr', abbr, 'name', name))), '[]'::json)) AS fc
           FROM kantone"""
    ).fetchone()["fc"]
