"""Bereinigung der GPS-Höhe.

Typisches Fehlerbild von APRS-Trackern:
- Nach dem Einschalten (Kaltstart) meldet das GPS zuerst eine viel zu tiefe Höhe
  (z. B. 102 m) und läuft dann über einige Minuten zur echten Höhe hoch
  (102 -> 232 -> 303 -> ... -> 436).
- Nach einem kurzen Neustart unterwegs erscheint einzeln ein solcher Wert mitten in der Fahrt.

Regel: Eine Höhe ist plausibel, wenn sie von der letzten plausiblen Höhe höchstens
BASE_M + MAX_GRADE * horizontale Distanz abweicht (Strassen steigen kaum mehr als 12 %).

- Beginnt eine Sitzung (Pause > SESSION_GAP_S) am Ort, an dem die letzte plausible
  Höhe gemessen wurde (≤ SAME_PLACE_M), dient diese als Referenz.
- Sonst dient der Punkt als Referenz, dessen Höhe dem Median der Sitzung am nächsten liegt
  (Kaltstart-Werte sind in der Minderheit). Von dort wird rückwärts und vorwärts geprüft.
- Weichen mindestens RESET_RUN Punkte in Folge ab, liegen aber eng beieinander (≤ RESET_SPREAD_M),
  war die Referenz falsch: Die Punkte gelten als plausibel und werden neue Referenz.

Die Rohwerte bleiben in `altitude_raw` erhalten, `altitude_m` enthält den bereinigten Wert.
"""
import math
from datetime import datetime

BASE_M = 30.0
MAX_GRADE = 0.12
SESSION_GAP_S = 10 * 60
SAME_PLACE_M = 500.0
RESET_RUN = 5
RESET_SPREAD_M = 40.0


def _dist_m(a: dict, b: dict) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def _ok(p: dict, ref: dict) -> bool:
    return abs(p["alt"] - ref["alt"]) <= BASE_M + MAX_GRADE * _dist_m(p, ref)


def _secs(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds()


def clean(points: list[dict]) -> list[float | None]:
    """points: nach Zeit sortiert, je {ts, lat, lon, alt}. Liefert bereinigte Höhen (None = verworfen)."""
    out: list[float | None] = [None] * len(points)
    idx = [i for i, p in enumerate(points) if p["alt"] is not None]
    if not idx:
        return out

    # Sitzungen bilden (nur Punkte mit Höhe)
    sessions, cur = [], [idx[0]]
    for a, b in zip(idx, idx[1:]):
        if _secs(points[a]["ts"], points[b]["ts"]) > SESSION_GAP_S:
            sessions.append(cur)
            cur = []
        cur.append(b)
    sessions.append(cur)

    anchor: dict | None = None  # letzter plausibler Punkt

    def forward(ids: list[int]) -> None:
        nonlocal anchor
        run: list[int] = []
        for i in ids:
            p = points[i]
            if anchor is None or _ok(p, anchor):
                out[i] = p["alt"]
                anchor = p
                run = []
                continue
            run.append(i)
            alts = [points[j]["alt"] for j in run]
            if len(run) >= RESET_RUN and max(alts) - min(alts) <= RESET_SPREAD_M:
                for j in run:
                    out[j] = points[j]["alt"]
                anchor = points[run[-1]]
                run = []

    for s in sessions:
        first = points[s[0]]
        if anchor is not None and _dist_m(first, anchor) <= SAME_PLACE_M:
            forward(s)
            continue
        # Referenz: Punkt mit der Höhe am nächsten beim Median der Sitzung
        # (Kaltstart-Werte sind in der Minderheit); bei Gleichstand der spätere
        alts = sorted(points[i]["alt"] for i in s)
        med = alts[len(alts) // 2]
        k = min(range(len(s)), key=lambda n: (abs(points[s[n]]["alt"] - med), -n))
        ref = points[s[k]]
        out[s[k]] = ref["alt"]
        for i in reversed(s[:k]):
            if _ok(points[i], ref):
                out[i] = points[i]["alt"]
                ref = points[i]
        anchor = points[s[k]]
        forward(s[k + 1:])
    return out


def clean_callsign(cur, callsign: str, since: datetime | None = None) -> int:
    """Höhen eines Rufzeichens neu bereinigen (ab `since`, sonst alles). Gibt Anzahl Änderungen zurück."""
    if since is not None:
        # eine Stunde Vorlauf, damit eine laufende Sitzung als Ganzes betrachtet wird
        cur.execute(
            """SELECT id, ts, lat, lon, altitude_raw AS alt, altitude_m FROM positions
               WHERE callsign = %s AND ts >= %s::timestamptz - interval '1 hour' ORDER BY ts""",
            (callsign, since),
        )
    else:
        cur.execute(
            """SELECT id, ts, lat, lon, altitude_raw AS alt, altitude_m FROM positions
               WHERE callsign = %s ORDER BY ts""",
            (callsign,),
        )
    rows = cur.fetchall()
    cleaned = clean(rows)
    changes = [(c, r["id"]) for r, c in zip(rows, cleaned) if c != r["altitude_m"]]
    if changes:
        cur.executemany("UPDATE positions SET altitude_m = %s WHERE id = %s", changes)
    return len(changes)


def clean_all(cur) -> int:
    cur.execute("SELECT DISTINCT callsign FROM positions")
    return sum(clean_callsign(cur, r["callsign"]) for r in cur.fetchall())
