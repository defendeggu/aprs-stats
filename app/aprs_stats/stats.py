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
    calls: list[str]
    start: datetime | None = None
    end: datetime | None = None

    def where(self, ts_col: str = "ts", call_col: str = "callsign") -> tuple[str, dict]:
        parts, params = ["true"], {}
        if self.calls:
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
        SELECT callsign, ts, geom, speed_kmh,
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
        """,
        {**params, "eps": eps, "minpts": min_points, "tz": TZ, "limit": limit},
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
