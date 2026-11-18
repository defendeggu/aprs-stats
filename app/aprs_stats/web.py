"""Weboberfläche und API."""
import csv
import io
import math
import os
from contextlib import asynccontextmanager
from datetime import datetime
from importlib.resources import files
from typing import Annotated

import psycopg
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import AUTHOR, __version__, db, stats
from .altitude import clean_all, clean_callsign
from .aprs import MAX_COMMENT_BYTES, full_call, normalize_callsign, normalize_ssid, position_packet, split_full
from .importer import parse_file
from .store import ensure_station, insert_position

STATIC = files("aprs_stats").joinpath("static")
MAX_UPLOAD = 50 * 1024 * 1024


@asynccontextmanager
async def lifespan(_app):
    db.init_schema()
    with db.conn() as c:
        clean_all(c.cursor())
    yield


app = FastAPI(title="aprs-stats", version=__version__, lifespan=lifespan)


# --- Hilfen -----------------------------------------------------------------

def make_filter(calls: str | None, start: datetime | None, end: datetime | None) -> stats.Filter:
    lst = [c.strip().upper() for c in (calls or "").split(",") if c.strip()]
    return stats.Filter(calls=lst, start=start, end=end)


CallsQ = Annotated[str | None, Query(description="Rufzeichen mit SSID, kommagetrennt; leer = alle")]
StartQ = Annotated[datetime | None, Query(alias="from")]
EndQ = Annotated[datetime | None, Query(alias="to")]


# --- Stationen --------------------------------------------------------------

class StationIn(BaseModel):
    callsign: str = Field(..., examples=["HB3XVA"])
    ssid: str = Field("", examples=["9", "*", ""])
    label: str | None = None
    color: str | None = None
    track: bool = True


class StationPatch(BaseModel):
    label: str | None = None
    color: str | None = None
    track: bool | None = None


def _station_row(r: dict) -> dict:
    r = dict(r)
    r["full"] = f"{r['callsign']}-*" if r["ssid"] == "*" else full_call(r["callsign"], r["ssid"])
    return r


@app.get("/api/stations")
def list_stations():
    with db.conn() as c:
        rows = c.execute(
            """
            SELECT s.*, x.points, x.first, x.last, l.lat AS last_lat, l.lon AS last_lon,
                   l.speed_kmh AS last_speed, l.comment AS last_comment
            FROM stations s
            LEFT JOIN LATERAL (
                SELECT count(*) AS points, min(ts) AS first, max(ts) AS last
                FROM positions p
                WHERE p.callsign = CASE WHEN s.ssid = '' THEN s.callsign ELSE s.callsign || '-' || s.ssid END
            ) x ON s.ssid <> '*'
            LEFT JOIN LATERAL (
                SELECT lat, lon, speed_kmh, comment FROM positions p
                WHERE p.callsign = CASE WHEN s.ssid = '' THEN s.callsign ELSE s.callsign || '-' || s.ssid END
                ORDER BY ts DESC LIMIT 1
            ) l ON s.ssid <> '*'
            ORDER BY s.callsign, s.ssid = '*' DESC, s.ssid
            """
        ).fetchall()
    return [_station_row(r) for r in rows]


@app.post("/api/stations", status_code=201)
def add_station(s: StationIn):
    try:
        base, ssid_from_call = normalize_callsign(s.callsign)
        ssid = normalize_ssid(s.ssid) if s.ssid.strip() else ssid_from_call
    except ValueError as e:
        raise HTTPException(422, str(e))
    with db.conn() as c:
        row = c.execute(
            """INSERT INTO stations (callsign, ssid, label, color, track, auto)
               VALUES (%s, %s, %s, %s, %s, false)
               ON CONFLICT (callsign, ssid) DO UPDATE
                 SET label = coalesce(EXCLUDED.label, stations.label),
                     color = coalesce(EXCLUDED.color, stations.color),
                     track = EXCLUDED.track, auto = false
               RETURNING *""",
            (base, ssid, (s.label or "").strip() or None, s.color, s.track),
        ).fetchone()
    return _station_row(row)


@app.patch("/api/stations/{sid}")
def patch_station(sid: int, p: StationPatch):
    sets, params = [], []
    for k in ("label", "color", "track"):
        v = getattr(p, k)
        if v is not None:
            sets.append(f"{k} = %s")
            params.append(v.strip() or None if isinstance(v, str) else v)
    if not sets:
        raise HTTPException(422, "Nichts zu ändern")
    with db.conn() as c:
        row = c.execute(
            f"UPDATE stations SET {', '.join(sets)} WHERE id = %s RETURNING *", (*params, sid)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Station nicht gefunden")
    return _station_row(row)


@app.delete("/api/stations/{sid}")
def delete_station(sid: int, purge: bool = False):
    """Station entfernen. Mit purge=true werden auch ihre Positionen und Pakete gelöscht."""
    with db.conn() as c:
        row = c.execute("DELETE FROM stations WHERE id = %s RETURNING *", (sid,)).fetchone()
        if not row:
            raise HTTPException(404, "Station nicht gefunden")
        deleted = 0
        if purge and row["ssid"] != "*":
            full = full_call(row["callsign"], row["ssid"])
            deleted = c.execute("DELETE FROM positions WHERE callsign = %s", (full,)).rowcount
            c.execute("DELETE FROM packets WHERE callsign = %s", (full,))
    return {"deleted_station": _station_row(row), "deleted_positions": deleted}


# --- Daten ------------------------------------------------------------------

@app.get("/api/positions")
def positions(calls: CallsQ = None, start: StartQ = None, end: EndQ = None,
              limit: int = Query(30000, le=200000)):
    """Positionen als Liste [callsign, ts(ms), lat, lon, speed, alt, course, comment, source, alt_raw].
    Bei mehr als `limit` Punkten wird gleichmässig ausgedünnt."""
    f = make_filter(calls, start, end)
    where, params = f.where()
    with db.conn() as c:
        n = c.execute(f"SELECT count(*) AS n FROM positions WHERE {where}", params).fetchone()["n"]
        step = max(1, math.ceil(n / limit))
        rows = c.execute(
            f"""SELECT callsign, (EXTRACT(EPOCH FROM ts) * 1000)::bigint AS t, lat, lon,
                       speed_kmh, altitude_m, course, comment, source, altitude_raw
                FROM (SELECT *, row_number() OVER (ORDER BY ts) AS rn FROM positions WHERE {where}) x
                WHERE rn %% %(step)s = 0 OR rn = 1 ORDER BY callsign, ts""",
            {**params, "step": step},
        ).fetchall()
    return {
        "total": n, "step": step,
        "rows": [[r["callsign"], r["t"], r["lat"], r["lon"], r["speed_kmh"], r["altitude_m"],
                  r["course"], r["comment"], r["source"], r["altitude_raw"]] for r in rows],
    }


@app.get("/api/latest")
def latest(calls: CallsQ = None):
    f = make_filter(calls, None, None)
    where, params = f.where()
    with db.conn() as c:
        return c.execute(
            f"""SELECT DISTINCT ON (callsign) callsign, ts, lat, lon, speed_kmh, course, altitude_m,
                       altitude_raw, comment, symbol, source
                FROM positions WHERE {where} ORDER BY callsign, ts DESC""",
            params,
        ).fetchall()


@app.get("/api/packets")
def packets(calls: CallsQ = None, start: StartQ = None, end: EndQ = None,
            limit: int = Query(200, le=2000)):
    f = make_filter(calls, start, end)
    where, params = f.where("received_at")
    with db.conn() as c:
        return c.execute(
            f"""SELECT id, received_at, callsign, raw, digis, qconstruct, igate, format
                FROM packets WHERE {where} ORDER BY received_at DESC LIMIT %(limit)s""",
            {**params, "limit": limit},
        ).fetchall()


@app.get("/api/stats/summary")
def stats_summary(calls: CallsQ = None, start: StartQ = None, end: EndQ = None):
    with db.conn() as c:
        return stats.summary(c, make_filter(calls, start, end))


@app.get("/api/stats/distance")
def stats_distance(calls: CallsQ = None, start: StartQ = None, end: EndQ = None,
                   bucket: str = Query("day", pattern="^(hour|day|week|month|year)$")):
    with db.conn() as c:
        return stats.distance(c, make_filter(calls, start, end), bucket)


@app.get("/api/stats/activity")
def stats_activity(calls: CallsQ = None, start: StartQ = None, end: EndQ = None):
    with db.conn() as c:
        return stats.activity(c, make_filter(calls, start, end))


@app.get("/api/stats/timeline")
def stats_timeline(calls: CallsQ = None, start: StartQ = None, end: EndQ = None):
    with db.conn() as c:
        return stats.timeline(c, make_filter(calls, start, end))


@app.get("/api/stats/trips")
def stats_trips(calls: CallsQ = None, start: StartQ = None, end: EndQ = None, min_km: float = 1.0):
    with db.conn() as c:
        return stats.trips(c, make_filter(calls, start, end), min_km=min_km)


@app.get("/api/stats/places")
def stats_places(calls: CallsQ = None, start: StartQ = None, end: EndQ = None,
                 eps: float = Query(150, ge=20, le=2000)):
    with db.conn() as c:
        return stats.places(c, make_filter(calls, start, end), eps_m=eps)


@app.get("/api/stats/paths")
def stats_paths(calls: CallsQ = None, start: StartQ = None, end: EndQ = None):
    with db.conn() as c:
        return stats.paths(c, make_filter(calls, start, end))


@app.get("/api/status")
def status():
    with db.conn() as c:
        col = c.execute("SELECT * FROM collector_status WHERE id = 1").fetchone()
        counts = c.execute(
            """SELECT (SELECT count(*) FROM positions) AS positions,
                      (SELECT count(*) FROM packets) AS packets,
                      (SELECT count(*) FROM stations) AS stations,
                      (SELECT count(*) FROM positions
                        WHERE altitude_raw IS NOT NULL AND altitude_m IS NULL) AS altitude_filtered,
                      pg_size_pretty(pg_database_size(current_database())) AS db_size"""
        ).fetchone()
        imports = c.execute("SELECT * FROM imports ORDER BY imported_at DESC LIMIT 20").fetchall()
    return {"version": __version__, "collector": col, "counts": counts, "imports": imports}


# --- Import / Export --------------------------------------------------------

@app.post("/api/import")
async def import_file(file: UploadFile = File(...), callsign: str = Form("")):
    content = await file.read(MAX_UPLOAD + 1)
    if len(content) > MAX_UPLOAD:
        raise HTTPException(413, "Datei zu gross (max. 50 MB)")
    try:
        rows, errors = parse_file(content, file.filename or "", callsign.strip() or None)
    except (ValueError, UnicodeDecodeError) as e:
        raise HTTPException(422, str(e))

    imported = duplicate = 0
    with db.conn() as c:
        cur = c.cursor()
        for call in {r["callsign"] for r in rows}:
            ensure_station(cur, call, track=False)
        for r in rows:
            try:
                if insert_position(cur, source="import", **r):
                    imported += 1
                else:
                    duplicate += 1
            except ValueError as e:
                errors.append(f"{r['ts']:%Y-%m-%d %H:%M:%S}: {e}")
        for call in {r["callsign"] for r in rows}:
            clean_callsign(cur, call)
        cur.execute(
            """INSERT INTO imports (filename, callsign, rows_total, rows_imported, rows_duplicate, rows_error)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (file.filename, ", ".join(sorted({r["callsign"] for r in rows})) or None,
             len(rows) + len(errors), imported, duplicate, len(errors)),
        )
    return {
        "filename": file.filename, "rows": len(rows) + len(errors), "imported": imported,
        "duplicate": duplicate, "errors": len(errors), "error_samples": errors[:20],
        "callsigns": sorted({r["callsign"] for r in rows}),
        "first": min((r["ts"] for r in rows), default=None),
        "last": max((r["ts"] for r in rows), default=None),
    }


@app.get("/api/export.csv")
def export_csv(calls: CallsQ = None, start: StartQ = None, end: EndQ = None):
    f = make_filter(calls, start, end)
    where, params = f.where()

    def gen():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["callsign", "time_utc", "lat", "lng", "speed_kmh", "course", "altitude_m",
                    "altitude_raw", "comment", "source"])
        with db.conn() as c:
            cur = c.cursor(name="export")
            cur.execute(
                f"""SELECT callsign, to_char(ts AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') AS t, lat, lon,
                           speed_kmh, course, altitude_m, altitude_raw, comment, source
                    FROM positions WHERE {where} ORDER BY ts""",
                params,
            )
            for r in cur:
                w.writerow([r["callsign"], r["t"], r["lat"], r["lon"], r["speed_kmh"], r["course"],
                            r["altitude_m"], r["altitude_raw"], r["comment"], r["source"]])
                if buf.tell() > 65536:
                    yield buf.getvalue()
                    buf.seek(0)
                    buf.truncate()
        yield buf.getvalue()

    return StreamingResponse(gen(), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="aprs-stats.csv"'})


# --- Baken ------------------------------------------------------------------

APRS_IS_LOGIN = os.environ.get("APRS_IS_LOGIN", "").strip().upper()
APRS_IS_PASSCODE = os.environ.get("APRS_IS_PASSCODE", "-1").strip() or "-1"


class BeaconIn(BaseModel):
    callsign: str
    ssid: str = ""
    symbol_table: str = Field("/", min_length=1, max_length=1)
    symbol_code: str = Field("-", min_length=1, max_length=1)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    altitude_m: float | None = None
    ambiguity: int = Field(0, ge=0, le=4)
    comment: str | None = Field(None, max_length=200)
    interval_min: int = Field(30, ge=10, le=1440)
    enabled: bool = True


def _beacon_values(b: BeaconIn) -> dict:
    """Prüft eine Bake und liefert die Werte für die Datenbank samt Paketvorschau."""
    try:
        base, ssid_from_call = normalize_callsign(b.callsign)
        ssid = normalize_ssid(b.ssid) if b.ssid.strip() else ssid_from_call
        if ssid == "*":
            raise ValueError("Eine Bake braucht eine feste SSID (oder keine)")
        if APRS_IS_LOGIN and split_full(APRS_IS_LOGIN)[0] != base:
            raise ValueError(f"Baken sind nur für das eigene Rufzeichen ({split_full(APRS_IS_LOGIN)[0]}) erlaubt")
        comment = (b.comment or "").strip() or None
        packet = position_packet(full_call(base, ssid), b.lat, b.lon, b.symbol_table, b.symbol_code,
                                 comment, b.altitude_m, b.ambiguity)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"callsign": base, "ssid": ssid, "symbol_table": b.symbol_table, "symbol_code": b.symbol_code,
            "lat": b.lat, "lon": b.lon, "altitude_m": b.altitude_m, "ambiguity": b.ambiguity,
            "comment": comment, "interval_min": b.interval_min, "enabled": b.enabled, "packet": packet}


def _beacon_row(r: dict) -> dict:
    r = dict(r)
    r["full"] = full_call(r["callsign"], r["ssid"])
    try:
        r["packet"] = position_packet(r["full"], r["lat"], r["lon"], r["symbol_table"], r["symbol_code"],
                                      r["comment"], r["altitude_m"], r["ambiguity"])
    except ValueError as e:
        r["packet"] = None
        r["last_error"] = r["last_error"] or str(e)
    return r


@app.get("/api/beacons/config")
def beacon_config():
    """Ob Senden möglich ist: Login und Passcode gesetzt, Login vom Server verifiziert."""
    with db.conn() as c:
        col = c.execute("SELECT state, login, updated_at FROM collector_status WHERE id = 1").fetchone()
    login_text = (col or {}).get("login") or ""
    return {
        "login": APRS_IS_LOGIN or None,
        "callsign": split_full(APRS_IS_LOGIN)[0] if APRS_IS_LOGIN else None,
        "passcode_set": APRS_IS_PASSCODE != "-1",
        "verified": " verified" in f" {login_text}" and "unverified" not in login_text,
        "collector_login": login_text or None,
        "max_comment": MAX_COMMENT_BYTES,
    }


@app.get("/api/beacons")
def list_beacons():
    with db.conn() as c:
        rows = c.execute("SELECT * FROM beacons ORDER BY callsign, ssid").fetchall()
    return [_beacon_row(r) for r in rows]


@app.post("/api/beacons/preview")
def preview_beacon(b: BeaconIn):
    return {"packet": _beacon_values(b)["packet"]}


@app.post("/api/beacons", status_code=201)
def add_beacon(b: BeaconIn):
    v = _beacon_values(b)
    v.pop("packet")
    with db.conn() as c:
        exists = c.execute("SELECT 1 FROM beacons WHERE callsign = %s AND ssid = %s",
                           (v["callsign"], v["ssid"])).fetchone()
        if exists:
            raise HTTPException(409, f"Für {full_call(v['callsign'], v['ssid'])} gibt es schon eine Bake")
        row = c.execute(
            """INSERT INTO beacons (callsign, ssid, symbol_table, symbol_code, lat, lon, altitude_m, ambiguity,
                                    comment, interval_min, enabled, next_due_at)
               VALUES (%(callsign)s, %(ssid)s, %(symbol_table)s, %(symbol_code)s, %(lat)s, %(lon)s,
                       %(altitude_m)s, %(ambiguity)s, %(comment)s, %(interval_min)s, %(enabled)s, now())
               RETURNING *""",
            v,
        ).fetchone()
    return _beacon_row(row)


@app.put("/api/beacons/{bid}")
def update_beacon(bid: int, b: BeaconIn):
    """Bake ändern. Ist sie aktiv, wird sie sofort mit den neuen Werten gesendet."""
    v = _beacon_values(b)
    v.pop("packet")
    with db.conn() as c:
        try:
            row = c.execute(
                """UPDATE beacons SET callsign = %(callsign)s, ssid = %(ssid)s, symbol_table = %(symbol_table)s,
                          symbol_code = %(symbol_code)s, lat = %(lat)s, lon = %(lon)s, altitude_m = %(altitude_m)s,
                          ambiguity = %(ambiguity)s, comment = %(comment)s, interval_min = %(interval_min)s,
                          enabled = %(enabled)s, next_due_at = now(), last_error = NULL
                   WHERE id = %(id)s RETURNING *""",
                {**v, "id": bid},
            ).fetchone()
        except psycopg.errors.UniqueViolation:
            raise HTTPException(409, f"Für {full_call(v['callsign'], v['ssid'])} gibt es schon eine Bake")
    if not row:
        raise HTTPException(404, "Bake nicht gefunden")
    return _beacon_row(row)


@app.post("/api/beacons/{bid}/send")
def send_beacon_now(bid: int):
    """Bake beim nächsten Durchlauf des Collectors (innert 5 s) senden; frühestens 60 s nach der letzten."""
    with db.conn() as c:
        row = c.execute("UPDATE beacons SET next_due_at = now() WHERE id = %s AND enabled RETURNING *",
                        (bid,)).fetchone()
    if not row:
        raise HTTPException(404, "Bake nicht gefunden oder nicht aktiv")
    return _beacon_row(row)


@app.patch("/api/beacons/{bid}")
def toggle_beacon(bid: int, enabled: bool):
    with db.conn() as c:
        row = c.execute(
            """UPDATE beacons SET enabled = %s,
                      next_due_at = CASE WHEN %s THEN now() ELSE next_due_at END, last_error = NULL
               WHERE id = %s RETURNING *""",
            (enabled, enabled, bid),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Bake nicht gefunden")
    return _beacon_row(row)


@app.delete("/api/beacons/{bid}")
def delete_beacon(bid: int):
    with db.conn() as c:
        row = c.execute("DELETE FROM beacons WHERE id = %s RETURNING *", (bid,)).fetchone()
    if not row:
        raise HTTPException(404, "Bake nicht gefunden")
    return {"deleted": _beacon_row(row)}


# --- Oberfläche -------------------------------------------------------------

@app.get("/api/version")
def version():
    return {"version": __version__, "author": AUTHOR, "credit": f"Author: {AUTHOR} - v{__version__}"}


@app.get("/healthz")
def healthz():
    with db.conn() as c:
        c.execute("SELECT 1")
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(str(STATIC.joinpath("index.html")))


app.mount("/", StaticFiles(directory=str(STATIC)), name="static")
