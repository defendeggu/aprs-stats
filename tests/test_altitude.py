"""Höhenbereinigung, mit Sequenzen aus einem echten aprs.fi-Export (HB3XVA-9, November 2026)."""
from datetime import datetime, timedelta

from aprs_stats.altitude import clean


def pts(rows, day="2026-11-04"):
    return [{"ts": datetime.fromisoformat(f"{day} {t}"), "lat": lat, "lon": lon, "alt": alt}
            for t, lat, lon, alt in rows]


def kept(points):
    return [c for c in clean(points)]


def test_cold_start_ramp_is_removed():
    # Kaltstart: 102 m, dann Hochlaufen bis ~440 m, danach plausibel
    p = pts([
        ("16:14:30", 46.96000, 8.36633, 102), ("16:15:31", 46.96067, 8.36333, 232),
        ("16:16:03", 46.96100, 8.36333, 303), ("16:16:41", 46.96100, 8.36317, 316),
        ("16:17:25", 46.96117, 8.36283, 344), ("16:17:57", 46.96150, 8.36233, 368),
        ("16:18:58", 46.96217, 8.36050, 436), ("16:19:30", 46.96233, 8.35983, 456),
        ("16:20:04", 46.96250, 8.35933, 474), ("16:20:55", 46.96467, 8.35650, 479),
        ("16:21:27", 46.96617, 8.35567, 486), ("16:22:28", 46.97067, 8.35000, 507),
        ("16:24:38", 46.97800, 8.33867, 521), ("16:27:39", 46.98000, 8.33700, 539),
    ])
    out = kept(p)
    assert out[:6] == [None] * 6
    assert out[6:] == [436, 456, 474, 479, 486, 507, 521, 539]


def test_single_spike_mid_trip_is_removed():
    p = pts([
        ("14:02:48", 47.08767, 8.30733, 465), ("14:04:49", 47.08783, 8.30733, 466),
        ("14:08:32", 47.08533, 8.31200, 101), ("14:09:03", 47.08117, 8.30667, 438),
        ("14:09:52", 47.07917, 8.30400, 432), ("14:10:53", 47.07567, 8.29583, 443),
    ], day="2026-11-14")
    assert kept(p) == [465, 466, None, 438, 432, 443]


def test_restart_at_parking_spot_uses_last_good_altitude():
    # Abends am gleichen Ort wieder eingeschaltet: 143 und 358 sind falsch, Referenz 483
    p = pts([
        ("11:03:36", 47.13750, 8.30900, 535), ("11:09:45", 47.16233, 8.28733, 483),
        ("19:48:28", 47.16350, 8.28667, 143), ("19:49:29", 47.16283, 8.28733, 358),
    ], day="2026-11-13")
    assert kept(p) == [535, 483, None, None]


def test_two_low_values_after_stop():
    p = pts([
        ("15:30:58", 47.03500, 8.27733, 495), ("15:32:30", 47.03517, 8.27733, 497),
        ("15:33:31", 47.03533, 8.27567, 483), ("15:41:33", 47.03150, 8.27350, 104),
        ("15:42:34", 47.03217, 8.27350, 124), ("16:59:36", 47.03533, 8.27550, 471),
    ], day="2026-11-14")
    assert kept(p) == [495, 497, 483, None, None, 471]


def test_mountain_road_is_kept():
    # echte Steigung: 533 -> 685 m auf rund 5 km
    p = pts([
        ("14:18:20", 47.08333, 8.24667, 515), ("14:19:21", 47.07933, 8.23250, 533),
        ("14:20:22", 47.07633, 8.21633, 551), ("14:21:23", 47.07350, 8.20483, 568),
        ("14:22:28", 47.07050, 8.19800, 619), ("14:23:01", 47.07050, 8.19650, 636),
        ("14:24:02", 47.06617, 8.18550, 657), ("14:25:03", 47.06683, 8.17267, 685),
    ], day="2026-11-14")
    assert kept(p) == [515, 533, 551, 568, 619, 636, 657, 685]


def test_wrong_reference_recovers():
    # Referenz falsch (Ausreisser am Anfang ohne Einschwingphase): stabile Folge setzt zurück
    base = datetime(2026, 1, 1, 12)
    p = [{"ts": base + timedelta(minutes=i), "lat": 47.0 + i * 0.0001, "lon": 8.0, "alt": a}
         for i, a in enumerate([900] + [420, 421, 419, 420, 422, 421])]
    out = clean(p)
    assert out[-1] == 421


def test_missing_altitude():
    p = pts([("10:00:00", 47.0, 8.0, None), ("10:01:00", 47.001, 8.0, 450)])
    assert kept(p) == [None, 450]
