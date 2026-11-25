"""Ein APRS-Paket speichern: Rohpaket, Station und (falls vorhanden) Position.

Gemeinsam für den Collector (Quelle `aprs_is`) und die Anlieferung über Funk
(Quelle `rf`, POST /api/ingest, z. B. von RadioMoni). Gespeichert wird nur,
was zu einer eingetragenen Station gehört.
"""
from datetime import datetime, timedelta

import aprslib

from .altitude import clean_callsign
from .aprs import matches, parse_path
from .store import ensure_station, insert_position

# Formate ohne eigene Position des Absenders
NO_POSITION_FORMATS = {"object", "item", "message", "status", "telemetry-message", "bulletin"}


def parse(raw: str) -> dict:
    """aprslib-Ergebnis; bei unbekanntem Format wenigstens Absender, Ziel und Pfad."""
    try:
        return aprslib.parse(raw)
    except (aprslib.ParseError, aprslib.UnknownFormat) as e:
        pkt = getattr(e, "packet", None) or {}
        if not pkt.get("from"):
            head = raw.split(":", 1)[0]
            src, _, rest = head.partition(">")
            parts = rest.split(",")
            pkt = {"from": src, "to": parts[0] if parts else None, "path": parts[1:], "format": "unparsed"}
        return pkt


def store_packet(cur, raw: str, received_at: datetime, source: str,
                 stations: list[tuple[str, str]], ext_ref: str | None = None) -> dict:
    """Paket speichern, wenn der Absender zu einer Station gehört.

    Rückgabe: {"stored": bool, "callsign": str, "packet_id": int|None, "position": "new"|"duplicate"|None}
    """
    pkt = parse(raw)
    src = (pkt.get("from") or "").upper()
    if not src or not matches(src, stations):
        return {"stored": False, "callsign": src, "packet_id": None, "position": None}
    p = parse_path(pkt.get("path") or [])
    cur.execute(
        """INSERT INTO packets (received_at, source, callsign, tocall, raw, path, digis,
                                qconstruct, igate, format, ext_ref)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (received_at, source, src, pkt.get("to"), raw, pkt.get("path"), p["digis"], p["qconstruct"],
         p["igate"], pkt.get("format"), ext_ref),
    )
    packet_id = cur.fetchone()["id"]
    ensure_station(cur, src)
    position = None
    lat, lon = pkt.get("latitude"), pkt.get("longitude")
    if lat is not None and lon is not None and pkt.get("format") not in NO_POSITION_FORMATS:
        symbol = (pkt.get("symbol_table") or "") + (pkt.get("symbol") or "") or None
        try:
            new = insert_position(
                cur, callsign=src, ts=received_at, lat=float(lat), lon=float(lon), source=source,
                speed=pkt.get("speed"), course=pkt.get("course"), alt=pkt.get("altitude"),
                comment=pkt.get("comment"), symbol=symbol, packet_id=packet_id, ext_ref=ext_ref,
            )
            position = "new" if new else "duplicate"
            if new and pkt.get("altitude") is not None:
                clean_callsign(cur, src, since=received_at - timedelta(hours=3))
        except ValueError:
            position = None
    return {"stored": True, "callsign": src, "packet_id": packet_id, "position": position}
