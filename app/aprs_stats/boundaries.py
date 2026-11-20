"""Gemeinde- und Kantonsgrenzen aus swissBOUNDARIES3D (swisstopo) laden und Positionen zuordnen.

Quelle: https://www.swisstopo.admin.ch/de/landschaftsmodell-swissboundaries3d (frei, Open Government Data).
Geladen wird das GeoPackage (LV95) der neusten Ausgabe aus dem STAC-Katalog von data.geo.admin.ch.
Es geht nur ein öffentlicher Download hinaus, keine eigenen Daten.
"""
import json
import logging
import os
import sqlite3
import tempfile
import threading
import urllib.request
import zipfile
from datetime import datetime, timezone

from . import __version__, db

log = logging.getLogger("boundaries")

STAC_ITEMS = "https://data.geo.admin.ch/api/stac/v1/collections/ch.swisstopo.swissboundaries3d/items?limit=100"
USER_AGENT = f"aprs-stats/{__version__}"
SIMPLIFY_M = 20            # Toleranz für die Kartenanzeige (Meter, LV95)
ASSIGN_CHUNK = 20000
_ASSIGN_LOCK = 4712        # Advisory-Lock: Zuordnung läuft nie doppelt

# Kantonsnummer (BFS) -> Kürzel
KANTON_ABBR = {
    1: "ZH", 2: "BE", 3: "LU", 4: "UR", 5: "SZ", 6: "OW", 7: "NW", 8: "GL", 9: "ZG", 10: "FR",
    11: "SO", 12: "BS", 13: "BL", 14: "SH", 15: "AR", 16: "AI", 17: "SG", 18: "GR", 19: "AG",
    20: "TG", 21: "TI", 22: "VD", 23: "VS", 24: "NE", 25: "GE", 26: "JU",
}

_thread: threading.Thread | None = None
_thread_lock = threading.Lock()


# --- GeoPackage ---------------------------------------------------------------

def gpkg_to_wkb(blob: bytes) -> bytes:
    """GeoPackage-Geometrie (Header + WKB) -> WKB. Siehe OGC GeoPackage 1.3, Kap. 2.1.3."""
    if blob[:2] != b"GP":
        raise ValueError("keine GeoPackage-Geometrie")
    flags = blob[3]
    envelope = (flags >> 1) & 0x07
    sizes = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
    if envelope not in sizes:
        raise ValueError(f"ungültiger Envelope-Typ {envelope}")
    return blob[8 + sizes[envelope]:]


def latest_release() -> tuple[str, str]:
    """(Ausgabe, URL des GeoPackage-Zips) der neusten Ausgabe."""
    req = urllib.request.Request(STAC_ITEMS, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        items = json.load(r)["features"]
    best = None
    for it in items:
        for a in it.get("assets", {}).values():
            if "geopackage" in (a.get("type") or "") and "_2056_" in a["href"]:
                if best is None or it["id"] > best[0]:
                    best = (it["id"], a["href"])
    if not best:
        raise RuntimeError("Keine GeoPackage-Ausgabe im STAC-Katalog gefunden")
    version = best[0].removeprefix("swissboundaries3d_")
    return version, best[1]


def _set_meta(**kw) -> None:
    cols = ", ".join(kw)
    vals = ", ".join(f"%({k})s" for k in kw)
    upd = ", ".join(f"{k} = EXCLUDED.{k}" for k in kw)
    with db.conn() as c:
        c.execute(
            f"""INSERT INTO boundaries_meta (id, {cols}, updated_at) VALUES (1, {vals}, now())
                ON CONFLICT (id) DO UPDATE SET {upd}, updated_at = now()""",
            kw,
        )


def _read_gpkg(path: str) -> tuple[list[tuple], list[tuple]]:
    g = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        areas = [
            (bfs, name, kind, kt, icc, gpkg_to_wkb(geom))
            for bfs, name, kind, kt, icc, geom in g.execute(
                "SELECT bfs_nummer, name, objektart, kantonsnummer, icc, geom FROM tlm_hoheitsgebiet "
                "WHERE geom IS NOT NULL")
        ]
        kantone = [
            (nr, name, gpkg_to_wkb(geom))
            for nr, name, geom in g.execute(
                "SELECT kantonsnummer, name, geom FROM tlm_kantonsgebiet WHERE geom IS NOT NULL")
        ]
    finally:
        g.close()
    return areas, kantone


_GEOM = "ST_SetSRID(ST_Force2D(ST_GeomFromWKB(%(wkb)s)), 2056)"


def load(version: str, url: str) -> int:
    """Lädt eine Ausgabe herunter, ersetzt die Grenzen und ordnet alle Positionen neu zu."""
    with tempfile.TemporaryDirectory(prefix="sb3d-") as tmp:
        zpath = os.path.join(tmp, "sb.zip")
        _set_meta(state="loading", message=f"Lade {version} herunter …")
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=120) as r, open(zpath, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
        with zipfile.ZipFile(zpath) as z:
            name = next((n for n in z.namelist() if n.endswith(".gpkg")), None)
            if not name:
                raise RuntimeError("Kein GeoPackage im Zip")
            gpath = z.extract(name, tmp)
        os.remove(zpath)
        _set_meta(message="Lese Grenzen …")
        areas, kantone = _read_gpkg(gpath)

    _set_meta(message=f"Speichere {len(areas)} Gebiete …")
    with db.conn() as c:
        cur = c.cursor()
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_ASSIGN_LOCK,))
        cur.execute("DELETE FROM areas")
        cur.execute("DELETE FROM kantone")
        cur.executemany(
            f"""INSERT INTO areas (bfs_nr, name, kind, kanton_nr, country, geom, geom_s)
                SELECT %(bfs)s, %(name)s, %(kind)s, %(kt)s, %(icc)s,
                       ST_Multi(ST_Transform(g, 4326)),
                       ST_Transform(ST_SimplifyPreserveTopology(g, {SIMPLIFY_M}), 4326)
                FROM (SELECT {_GEOM} AS g) x""",
            [{"bfs": b, "name": n, "kind": k, "kt": kt, "icc": i, "wkb": w} for b, n, k, kt, i, w in areas],
        )
        cur.executemany(
            f"""INSERT INTO kantone (nr, abbr, name, geom_s)
                SELECT %(nr)s, %(abbr)s, %(name)s,
                       ST_Transform(ST_SimplifyPreserveTopology({_GEOM}, {SIMPLIFY_M * 2}), 4326)
                ON CONFLICT (nr) DO UPDATE SET geom_s = ST_Union(kantone.geom_s, EXCLUDED.geom_s)""",
            [{"nr": nr, "abbr": KANTON_ABBR.get(nr, str(nr)), "name": n, "wkb": w} for nr, n, w in kantone],
        )
        cur.execute("UPDATE positions SET area = NULL WHERE area IS NOT NULL")
        n = cur.execute("SELECT count(*) AS n FROM areas WHERE kind = 'Gemeindegebiet' AND country = 'CH'"
                        ).fetchone()["n"]
    _set_meta(message="Ordne Positionen zu …")
    while assign(limit=ASSIGN_CHUNK, wait=True) == ASSIGN_CHUNK:
        pass
    return n


def assign(limit: int | None = None, wait: bool = False) -> int:
    """Ordnet noch nicht zugeordnete Positionen einem Gebiet zu. Gibt die Anzahl zurück.
    Ohne geladene Grenzen passiert nichts. Läuft schon eine Zuordnung, wird übersprungen."""
    with db.conn() as c:
        if wait:
            c.execute("SELECT pg_advisory_xact_lock(%s)", (_ASSIGN_LOCK,))
        elif not c.execute("SELECT pg_try_advisory_xact_lock(%s) AS ok", (_ASSIGN_LOCK,)).fetchone()["ok"]:
            return 0
        if not c.execute("SELECT EXISTS (SELECT 1 FROM areas) AS ok").fetchone()["ok"]:
            return 0
        cur = c.execute(
            f"""UPDATE positions p SET area = coalesce((
                    SELECT a.id FROM areas a WHERE ST_Intersects(a.geom, p.geom)
                    ORDER BY (a.kind = 'Gemeindegebiet') DESC, a.id LIMIT 1), 0)
                WHERE p.id IN (SELECT id FROM positions WHERE area IS NULL
                               {"LIMIT %(limit)s" if limit else ""})""",
            {"limit": limit},
        )
        return cur.rowcount


def status() -> dict:
    with db.conn() as c:
        m = c.execute("SELECT * FROM boundaries_meta WHERE id = 1").fetchone() or {}
        todo = c.execute("SELECT count(*) AS n FROM positions WHERE area IS NULL").fetchone()["n"]
    return {**m, "running": is_running(), "unassigned": todo}


def is_running() -> bool:
    return _thread is not None and _thread.is_alive()


def _run() -> None:
    try:
        version, url = latest_release()
        n = load(version, url)
        _set_meta(state="ready", version=version, source=url, loaded_at=datetime.now(timezone.utc),
                  gemeinden=n, message=None)
        log.info("swissBOUNDARIES3D %s geladen (%d Gemeinden)", version, n)
    except Exception as e:  # noqa: BLE001 – Fehler landet im Status
        log.exception("Grenzen laden fehlgeschlagen")
        with db.conn() as c:
            ready = c.execute("SELECT EXISTS (SELECT 1 FROM areas) AS ok").fetchone()["ok"]
        _set_meta(state="ready" if ready else "error", message=f"Laden fehlgeschlagen: {e}")


def start_load() -> bool:
    """Startet das Laden im Hintergrund. False, wenn es schon läuft."""
    global _thread
    with _thread_lock:
        if is_running():
            return False
        _thread = threading.Thread(target=_run, name="boundaries", daemon=True)
        _thread.start()
        return True


def autoload() -> None:
    """Beim Start: Grenzen laden, falls noch keine da sind (abschaltbar mit BOUNDARIES_AUTOLOAD=0)."""
    if os.environ.get("BOUNDARIES_AUTOLOAD", "1").strip().lower() in ("0", "false", "no", "nein"):
        return
    with db.conn() as c:
        if c.execute("SELECT EXISTS (SELECT 1 FROM areas) AS ok").fetchone()["ok"]:
            return
    start_load()
