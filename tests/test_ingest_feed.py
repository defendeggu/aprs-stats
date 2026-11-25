"""Anlieferung über Funk (POST /api/ingest) und inkrementelle Feeds, gegen eine echte PostGIS-Datenbank.

Läuft nur mit TEST_DATABASE_URL (leere Wegwerf-Datenbank), siehe README, Abschnitt Entwicklung.
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

TEST_DB = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL nicht gesetzt")

TOKEN = "test-token-0123456789abcdef"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
# Mic-E und unkomprimierte Position, Rufzeichen anonymisiert
MOBILE = "N0CALL-9>APDR16,WIDE1-1,WIDE2-1:=4703.50N/00818.00E>088/036/A=001500 mobil"
OTHER = "N0OTHER>APRS:!4703.50N/00818.00E-"


@pytest.fixture(scope="module")
def client():
    os.environ["DATABASE_URL"] = TEST_DB
    os.environ["APRS_STATS_API_TOKEN"] = TOKEN
    os.environ["BOUNDARIES_AUTOLOAD"] = "0"
    from fastapi.testclient import TestClient

    from aprs_stats import db, web
    db.DATABASE_URL = TEST_DB          # andere Tests haben das Modul schon mit der Vorgabe importiert
    db._pool = None
    web.API_TOKEN = TOKEN
    with TestClient(web.app) as c:
        with web.db.conn() as conn:
            conn.execute("TRUNCATE positions, packets, stations RESTART IDENTITY CASCADE")
        r = c.post("/api/stations", json={"callsign": "N0CALL", "ssid": "*"})
        assert r.status_code == 201
        yield c


def test_token_required(client):
    assert client.post("/api/ingest", json={"raw": MOBILE}).status_code == 401
    assert client.post("/api/ingest", json={"raw": MOBILE},
                       headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/feed/packets").status_code == 401
    assert client.get("/api/feed/positions", headers=AUTH).status_code == 200


def test_ingest_rf_only_for_stations(client):
    when = datetime.now(timezone.utc) - timedelta(minutes=30)
    r = client.post("/api/ingest", headers=AUTH,
                    json={"raw": MOBILE, "received_at": when.isoformat(), "ext_ref": "uuid-rf-1"})
    assert r.status_code == 200
    body = r.json()
    assert body["stored"] and body["position"] == "new" and body["callsign"] == "N0CALL-9"
    r = client.post("/api/ingest", headers=AUTH, json={"raw": OTHER})
    assert r.json() == {"stored": False, "callsign": "N0OTHER", "packet_id": None, "position": None}
    assert client.post("/api/ingest", headers=AUTH, json={"raw": "kein paket"}).status_code == 422
    assert client.post("/api/ingest", headers=AUTH, json={"raw": MOBILE, "source": "aprs_is"}).status_code == 422


def test_internet_twin_is_duplicate_and_marked(client):
    from aprs_stats import db
    from aprs_stats.ingest import store_packet
    when = datetime.now(timezone.utc) - timedelta(minutes=30, seconds=-20)   # 20 s nach dem Funk-Paket
    raw = MOBILE.replace("WIDE2-1", "WIDE2-1,qAR,N0GATE-10")
    with db.conn() as c:
        res = store_packet(c.cursor(), raw, when, "aprs_is", [("N0CALL", "*")])
    assert res["stored"] and res["position"] == "duplicate"

    feed = client.get("/api/feed/packets", headers=AUTH, params={"after_id": 0}).json()
    rf, net = feed["items"]
    assert rf["source"] == "rf" and rf["ext_ref"] == "uuid-rf-1" and rf["position_id"] is not None
    assert net["source"] == "aprs_is" and net["igate"] == "N0GATE-10" and net["also_rf"] is True
    assert net["position_id"] is None and net["twin_position_id"] == rf["position_id"]
    assert feed["next"] == net["id"] and feed["pending"] is False
    again = client.get("/api/feed/packets", headers=AUTH, params={"after_id": feed["next"]}).json()
    assert again == {"items": [], "next": feed["next"], "pending": False}


def test_fresh_internet_packet_waits(client):
    from aprs_stats import db
    from aprs_stats.ingest import store_packet
    last = client.get("/api/feed/packets", headers=AUTH).json()["next"]
    with db.conn() as c:
        store_packet(c.cursor(), MOBILE.replace("mobil", "neu") + "", datetime.now(timezone.utc), "aprs_is",
                     [("N0CALL", "*")])
    feed = client.get("/api/feed/packets", headers=AUTH, params={"after_id": last}).json()
    assert feed["items"] == [] and feed["pending"] is True and feed["next"] == last


def test_positions_feed_has_imports_only(client):
    from aprs_stats import db
    from aprs_stats.store import insert_position
    with db.conn() as c:
        assert insert_position(c.cursor(), callsign="N0CALL-7", ts=datetime(2026, 1, 5, 10, tzinfo=timezone.utc),
                               lat=46.95, lon=7.45, source="import", speed=0)
    feed = client.get("/api/feed/positions", headers=AUTH).json()
    assert [p["source"] for p in feed["items"]] == ["import"]
    assert feed["items"][0]["callsign"] == "N0CALL-7" and feed["items"][0]["gemeinde"] is None


def test_summary_counts_by_source(client):
    s = client.get("/api/stats/summary").json()
    assert s["by_source"].get("rf") == 1 and s["by_source"].get("import") == 1
    pk = client.get("/api/packets").json()
    assert {p["source"] for p in pk} == {"rf", "aprs_is"}
