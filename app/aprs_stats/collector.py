"""Collector: dauerhaft mit APRS-IS verbunden, speichert Pakete der eingetragenen Stationen.

- Filter wird aus der Tabelle `stations` (track = true) gebildet, z. B. b/HB3XVA*/HB9ABC-7.
- Ändern sich die Stationen, verbindet sich der Collector mit neuem Filter neu.
- Ohne Daten (auch ohne Server-Keepalive) während READ_TIMEOUT wird neu verbunden.
"""
import logging
import os
import select
import socket
import time
from datetime import datetime, timedelta, timezone

import aprslib

from . import __version__, db
from .aprs import build_filter, matches, parse_path
from .altitude import clean_callsign
from .store import ensure_station, insert_position

log = logging.getLogger("collector")

SERVER = os.environ.get("APRS_IS_SERVER", "rotate.aprs2.net")
PORT = int(os.environ.get("APRS_IS_PORT", "14580"))
LOGIN = os.environ.get("APRS_IS_LOGIN", "").strip().upper()
PASSCODE = os.environ.get("APRS_IS_PASSCODE", "-1").strip() or "-1"
READ_TIMEOUT = 120      # s ohne Daten -> neu verbinden
FILTER_CHECK = 15       # s zwischen Prüfungen auf geänderte Stationen
STATUS_EVERY = 20       # s zwischen Status-Updates

NO_POSITION_FORMATS = {"object", "item", "message", "status", "telemetry-message", "bulletin"}


class Collector:
    def __init__(self):
        self.db = db.connect()
        self.packets_total = 0
        self.last_packet_at = None
        self.connected_since = None

    # --- Datenbank -------------------------------------------------------
    def stations(self) -> list[tuple[str, str]]:
        """Live verfolgte Stationen, in der Reihenfolge des Eintragens (erste = Login-Fallback)."""
        rows = self.db.execute(
            "SELECT callsign, ssid FROM stations WHERE track ORDER BY auto, id"
        ).fetchall()
        return [(r["callsign"], r["ssid"]) for r in rows]

    def status(self, state: str, *, flt: str | None = None, error: str | None = None, login: str | None = None):
        try:
            self.db.execute(
                """
                INSERT INTO collector_status (id, state, server, filter, login, connected_since,
                                              last_packet_at, packets_total, last_error, updated_at)
                VALUES (1, %(state)s, %(server)s, %(filter)s, %(login)s, %(since)s, %(last)s, %(total)s, %(err)s, now())
                ON CONFLICT (id) DO UPDATE SET
                    state = EXCLUDED.state, server = EXCLUDED.server,
                    filter = COALESCE(EXCLUDED.filter, collector_status.filter),
                    login = COALESCE(EXCLUDED.login, collector_status.login),
                    connected_since = EXCLUDED.connected_since,
                    last_packet_at = COALESCE(EXCLUDED.last_packet_at, collector_status.last_packet_at),
                    packets_total = collector_status.packets_total + EXCLUDED.packets_total,
                    last_error = COALESCE(EXCLUDED.last_error, collector_status.last_error),
                    updated_at = now()
                """,
                {"state": state, "server": f"{SERVER}:{PORT}", "filter": flt, "login": login,
                 "since": self.connected_since, "last": self.last_packet_at,
                 "total": self.packets_total, "err": error},
            )
            self.packets_total = 0  # als Delta gezählt
        except Exception:  # Status darf den Collector nie stoppen
            log.exception("Status konnte nicht geschrieben werden")
            self.db = db.connect()

    def store(self, raw: str, stations: list[tuple[str, str]]) -> None:
        now = datetime.now(timezone.utc)
        try:
            pkt = aprslib.parse(raw)
        except (aprslib.ParseError, aprslib.UnknownFormat) as e:
            pkt = getattr(e, "packet", None) or {}
            if not pkt.get("from"):
                head = raw.split(":", 1)[0]
                src, _, rest = head.partition(">")
                parts = rest.split(",")
                pkt = {"from": src, "to": parts[0] if parts else None, "path": parts[1:], "format": "unparsed"}
        src = (pkt.get("from") or "").upper()
        if not src or not matches(src, stations):
            return  # z. B. HB3XVAB bei Filter b/HB3XVA*
        p = parse_path(pkt.get("path") or [])

        with self.db.transaction():
            cur = self.db.cursor()
            cur.execute(
                """INSERT INTO packets (received_at, source, callsign, tocall, raw, path, digis,
                                        qconstruct, igate, format)
                   VALUES (%s, 'aprs_is', %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (now, src, pkt.get("to"), raw, pkt.get("path"), p["digis"], p["qconstruct"],
                 p["igate"], pkt.get("format")),
            )
            packet_id = cur.fetchone()["id"]
            ensure_station(cur, src)
            lat, lon = pkt.get("latitude"), pkt.get("longitude")
            if lat is not None and lon is not None and pkt.get("format") not in NO_POSITION_FORMATS:
                symbol = (pkt.get("symbol_table") or "") + (pkt.get("symbol") or "") or None
                try:
                    if insert_position(
                        cur, callsign=src, ts=now, lat=float(lat), lon=float(lon), source="aprs_is",
                        speed=pkt.get("speed"), course=pkt.get("course"), alt=pkt.get("altitude"),
                        comment=pkt.get("comment"), symbol=symbol, packet_id=packet_id,
                    ) and pkt.get("altitude") is not None:
                        clean_callsign(cur, src, since=now - timedelta(hours=3))
                except ValueError:
                    pass
        self.packets_total += 1
        self.last_packet_at = now
        log.info("%s", raw)

    # --- Verbindung ------------------------------------------------------
    def session(self, stations: list[tuple[str, str]], flt: str) -> None:
        # Ohne APRS_IS_LOGIN: Rufzeichen der zuerst eingetragenen Station
        login = LOGIN or stations[0][0]
        log.info("Verbinde mit %s:%s als %s, Filter %s", SERVER, PORT, login, flt)
        self.status("connecting", flt=flt, login=login)
        sock = socket.create_connection((SERVER, PORT), timeout=30)
        try:
            sock.sendall(
                f"user {login} pass {PASSCODE} vers aprs-stats {__version__} filter {flt}\r\n".encode()
            )
            self.connected_since = datetime.now(timezone.utc)
            buf = b""
            last_rx = last_check = last_status = time.monotonic()
            self.status("connected", flt=flt, login=login)
            while True:
                ready, _, _ = select.select([sock], [], [], 5)
                now = time.monotonic()
                if ready:
                    data = sock.recv(65536)
                    if not data:
                        raise ConnectionError("Server hat die Verbindung geschlossen")
                    last_rx = now
                    buf += data
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        text = line.decode("utf-8", errors="replace").strip("\r\n")
                        if not text:
                            continue
                        if text.startswith("#"):
                            if "logresp" in text:
                                log.info("%s", text)
                                self.status("connected", flt=flt, login=f"{login} ({text.split('logresp', 1)[1].strip()})")
                            continue
                        try:
                            self.store(text, stations)
                        except Exception:
                            log.exception("Paket nicht gespeichert: %s", text)
                            self.db = db.connect()
                if now - last_rx > READ_TIMEOUT:
                    raise TimeoutError(f"{READ_TIMEOUT} s keine Daten vom Server")
                if now - last_check > FILTER_CHECK:
                    last_check = now
                    if self.stations() != stations:
                        log.info("Stationen geändert, verbinde neu")
                        return
                if now - last_status > STATUS_EVERY:
                    last_status = now
                    self.status("connected", flt=flt)
        finally:
            self.connected_since = None
            sock.close()

    def run(self) -> None:
        backoff = 5
        while True:
            stations = self.stations()
            flt = build_filter(stations)
            if not flt:
                self.status("idle", flt="", error=None)
                time.sleep(FILTER_CHECK)
                continue
            try:
                self.session(stations, flt)
                backoff = 5
            except Exception as e:  # Netz, Server, DB
                log.warning("Verbindung beendet: %s", e)
                try:
                    self.status("error", flt=flt, error=f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC: {e}")
                except Exception:
                    self.db = db.connect()
                time.sleep(backoff)
                backoff = min(backoff * 2, 120)


def main():
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db.init_schema()
    Collector().run()


if __name__ == "__main__":
    main()
