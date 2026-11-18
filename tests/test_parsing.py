from datetime import datetime, timezone

import pytest

from aprs_stats.aprs import build_filter, matches, normalize_callsign, parse_path
from aprs_stats.importer import map_columns, parse_file, parse_time


def test_normalize_callsign():
    assert normalize_callsign("hb3xva-9") == ("HB3XVA", "9")
    assert normalize_callsign("HB3XVA") == ("HB3XVA", "")
    assert normalize_callsign("HB3XVA-0") == ("HB3XVA", "")
    with pytest.raises(ValueError):
        normalize_callsign("HB 3XVA")
    with pytest.raises(ValueError):
        normalize_callsign("HB3XVA-123")


def test_filter_and_match():
    st = [("HB3XVA", "*"), ("HB9ABC", "7"), ("HB9DEF", "")]
    assert build_filter(st) == "b/HB3XVA*/HB9ABC-7/HB9DEF"
    assert matches("HB3XVA-9", st)
    assert matches("HB3XVA", st)
    assert not matches("HB3XVAB-9", st)  # Präfix-Filter liefert auch das
    assert matches("HB9ABC-7", st)
    assert not matches("HB9ABC-9", st)
    assert matches("HB9DEF", st)
    assert not matches("HB9DEF-1", st)


def test_parse_path_digis_and_igate():
    p = parse_path(["HB9F*", "WIDE2-1", "qAR", "HB9XX-10"])
    assert p == {"digis": ["HB9F"], "qconstruct": "qAR", "igate": "HB9XX-10", "tcpip": False}

    p = parse_path(["HB9F", "HB9G-1", "WIDE2*", "qAO", "HB9YY"])
    assert p["digis"] == ["HB9F", "HB9G-1"]

    p = parse_path(["WIDE1-1", "WIDE2-1", "qAR", "HB9XX-10"])
    assert p["digis"] == [] and p["igate"] == "HB9XX-10"

    p = parse_path(["TCPIP*", "qAC", "T2SWISS"])
    assert p["tcpip"] and p["qconstruct"] == "qAC" and p["digis"] == []


def test_parse_time():
    assert parse_time("2026-05-01 12:00:00") == datetime(2026, 5, 1, 12, tzinfo=timezone.utc)
    assert parse_time(1777636800) == datetime(2026, 5, 1, 12, tzinfo=timezone.utc)
    assert parse_time("1777636800000") == datetime(2026, 5, 1, 12, tzinfo=timezone.utc)
    assert parse_time("2026-05-01T14:00:00+02:00").astimezone(timezone.utc).hour == 12


def test_map_columns_aprsfi_like():
    cols = map_columns(["time", "lasttime", "lat", "lng", "speed (km/h)", "course", "altitude (m)", "comment"])
    assert cols["ts"] == "time" and cols["lon"] == "lng" and cols["speed"] == "speed (km/h)"
    assert cols["alt"] == "altitude (m)"


def test_parse_csv_with_callsign_column():
    data = (
        "name,time,lat,lng,speed,course,altitude,comment\n"
        "HB3XVA-9,2026-05-01 12:00:00,47.1,8.3,50,90,450,hallo\n"
        "HB3XVA-9,2026-05-01 12:01:00,47.11,8.31,,,,\n"
        "HB3XVA-9,kaputt,47.1,8.3,,,,\n"
    ).encode()
    rows, errors = parse_file(data, "x.csv")
    assert len(rows) == 2 and len(errors) == 1
    assert rows[0]["callsign"] == "HB3XVA-9" and rows[0]["speed"] == 50 and rows[0]["comment"] == "hallo"
    assert rows[1]["speed"] is None


def test_parse_csv_semicolon_without_callsign():
    data = "Zeit;Breite;Länge;Höhe\n2026-05-01 12:00:00;47,1;8,3;500\n".encode()
    with pytest.raises(ValueError, match="Rufzeichen"):
        parse_file(data, "x.csv")
    rows, errors = parse_file(data, "x.csv", default_call="hb3xva-7")
    assert rows[0]["callsign"] == "HB3XVA-7" and rows[0]["lat"] == 47.1 and rows[0]["alt"] == 500


def test_parse_json():
    data = b'{"entries":[{"name":"HB3XVA-9","time":1777636800,"lat":"47.1","lng":"8.3"}]}'
    rows, errors = parse_file(data, "x.json")
    assert rows[0]["ts"].year == 2026 and not errors


def test_position_packet():
    import aprslib
    from aprs_stats.aprs import format_lat, format_lon, position_packet
    assert format_lat(47.16233) == "4709.74N"
    assert format_lon(8.28733) == "00817.24E"
    assert format_lat(-33.5) == "3330.00S" and format_lon(-70.25) == "07015.00W"
    assert format_lat(47.16233, 2) == "4709.  N"
    assert format_lon(8.28733, 1) == "00817.2 E"
    pkt = position_packet("HB3XVA-10", 47.16233, 8.28733, "/", "-", "QRV 2m/70cm", 470)
    assert pkt == "HB3XVA-10>APZSTA,TCPIP*:!4709.74N/00817.24E-/A=001542QRV 2m/70cm"
    p = aprslib.parse(pkt)
    assert abs(p["latitude"] - 47.16233) < 0.0001 and p["symbol"] == "-" and p["symbol_table"] == "/"
    assert round(p["altitude"]) == 470
    # Overlay auf alternativer Tafel
    assert ":!4709.74NI00817.24E&" in position_packet("HB3XVA", 47.16233, 8.28733, "I", "&")
    with pytest.raises(ValueError):
        position_packet("HB3XVA", 47.1, 8.2, "x", "-")
    with pytest.raises(ValueError):
        position_packet("HB3XVA", 47.1, 8.2, "/", "-", "x" * 44)
