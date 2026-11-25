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
from datetime import datetime, timezone

from . import __version__, db
from .aprs import build_filter, full_call, position_packet, split_full
from .ingest import store_packet

log = logging.getLogger("collector")

SERVER = os.environ.get("APRS_IS_SERVER", "rotate.aprs2.net")
PORT = int(os.environ.get("APRS_IS_PORT", "14580"))
LOGIN = os.environ.get("APRS_IS_LOGIN", "").strip().upper()
PASSCODE = os.environ.get("APRS_IS_PASSCODE", "-1").strip() or "-1"
READ_TIMEOUT = 120      # s ohne Daten -> neu verbinden
BEACON_CHECK = 5        # s zwischen Prüfungen auf fällige Baken
BEACON_MIN_GAP = 60     # s Mindestabstand zwischen zwei Sendungen derselben Bake
FILTER_CHECK = 15       # s zwischen Prüfungen auf geänderte Stationen
STATUS_EVERY = 20       # s zwischen Status-Updates


class Collector:
    def __init__(self):
        self.db = db.connect()
        self.packets_total = 0
        self.last_packet_at = None
        self.connected_since = None
        self.verified = False

    # --- Datenbank -------------------------------------------------------
    def stations(self) -> list[tuple[str, str]]:
        """Live verfolgte Stationen, in der Reihenfolge des Eintragens (erste = Login-Fallback)."""
        rows = self.db.execute(
            "SELECT callsign, ssid FROM stations WHERE track ORDER BY auto, id"
        ).fetchall()
        return [(r["callsign"], r["ssid"]) for r in rows]

    def beacons_enabled(self) -> bool:
        return bool(self.db.execute("SELECT 1 FROM beacons WHERE enabled LIMIT 1").fetchone())

    def send_beacons(self, sock: socket.socket, login: str) -> None:
        """Fällige Baken senden. Nur mit verifiziertem Login und nur für das eigene Rufzeichen."""
        due = self.db.execute(
            """SELECT * FROM beacons
               WHERE enabled AND (next_due_at IS NULL OR next_due_at <= now())
                 AND (last_sent_at IS NULL OR last_sent_at <= now() - make_interval(secs => %s))
               ORDER BY id""",
            (BEACON_MIN_GAP,),
        ).fetchall()
        for b in due:
            full = full_call(b["callsign"], b["ssid"])
            error = None
            if not self.verified:
                error = ("APRS-IS-Login nicht verifiziert: APRS_IS_LOGIN und APRS_IS_PASSCODE in .env prüfen")
            elif split_full(login)[0] != b["callsign"]:
                error = f"Rufzeichen {b['callsign']} passt nicht zum APRS-IS-Login {login}"
            if error:
                self.db.execute(
                    "UPDATE beacons SET last_error = %s, next_due_at = now() + interval '5 minutes' WHERE id = %s",
                    (error, b["id"]),
                )
                continue
            try:
                pkt = position_packet(full, b["lat"], b["lon"], b["symbol_table"], b["symbol_code"],
                                      b["comment"], b["altitude_m"], b["ambiguity"])
                sock.sendall((pkt + "\r\n").encode("utf-8"))
            except ValueError as e:
                self.db.execute("UPDATE beacons SET last_error = %s, enabled = false WHERE id = %s",
                                (f"Ungültige Bake, deaktiviert: {e}", b["id"]))
                continue
            now = datetime.now(timezone.utc)
            with self.db.transaction():
                self.db.execute(
                    """UPDATE beacons SET last_sent_at = %s, sent_count = sent_count + 1, last_packet = %s,
                              last_error = NULL, next_due_at = %s + make_interval(mins => interval_min)
                       WHERE id = %s""",
                    (now, pkt, now, b["id"]),
                )
                self.db.execute(
                    """INSERT INTO packets (received_at, source, callsign, tocall, raw, format)
                       VALUES (%s, 'beacon', %s, %s, %s, 'uncompressed')""",
                    (now, full, pkt.split(">", 1)[1].split(",", 1)[0], pkt),
                )
            log.info("Bake gesendet: %s", pkt)

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
        with self.db.transaction():
            result = store_packet(self.db.cursor(), raw, now, "aprs_is", stations)
        if not result["stored"]:
            return  # z. B. HB3XVAB bei Filter b/HB3XVA*
        self.packets_total += 1
        self.last_packet_at = now
        log.info("%s", raw)

    # --- Verbindung ------------------------------------------------------
    def session(self, stations: list[tuple[str, str]], flt: str, beacons: bool) -> None:
        # Ohne APRS_IS_LOGIN: Rufzeichen der zuerst eingetragenen Station
        login = LOGIN or (stations[0][0] if stations else "N0CALL")
        log.info("Verbinde mit %s:%s als %s, Filter %s", SERVER, PORT, login, flt or "(keiner)")
        self.status("connecting", flt=flt, login=login)
        sock = socket.create_connection((SERVER, PORT), timeout=30)
        self.verified = False
        logged_in = False
        try:
            sock.sendall(
                f"user {login} pass {PASSCODE} vers aprs-stats {__version__}"
                f"{' filter ' + flt if flt else ''}\r\n".encode()
            )
            self.connected_since = datetime.now(timezone.utc)
            buf = b""
            last_rx = last_check = last_status = last_beacon = time.monotonic()
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
                                resp = text.split("logresp", 1)[1].strip()
                                self.verified = " verified" in f" {resp}" and "unverified" not in resp
                                logged_in = True
                                self.status("connected", flt=flt, login=f"{login} ({resp})")
                            continue
                        try:
                            self.store(text, stations)
                        except Exception:
                            log.exception("Paket nicht gespeichert: %s", text)
                            self.db = db.connect()
                if now - last_rx > READ_TIMEOUT:
                    raise TimeoutError(f"{READ_TIMEOUT} s keine Daten vom Server")
                if logged_in and now - last_beacon > BEACON_CHECK:
                    last_beacon = now
                    self.send_beacons(sock, login)
                if now - last_check > FILTER_CHECK:
                    last_check = now
                    if self.stations() != stations or self.beacons_enabled() != beacons:
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
            beacons = self.beacons_enabled()
            if not flt and not beacons:
                self.status("idle", flt="", error=None)
                time.sleep(FILTER_CHECK)
                continue
            try:
                self.session(stations, flt, beacons)
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
