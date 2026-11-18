"""Import von Exporten (aprs.fi CSV/JSON und ähnliche Formate).

Die Spalten werden über ihre Namen erkannt, damit auch leicht abweichende Exporte
funktionieren. Zeiten ohne Zeitzone gelten als UTC (so exportiert aprs.fi).
"""
import csv
import io
import json
import re
from datetime import datetime, timezone

from .aprs import full_call, normalize_callsign

# Spaltennamen (normalisiert: klein, nur a-z0-9) -> Feld
_ALIASES = {
    "ts": ["time", "timestamp", "datetime", "date", "zeit", "datum", "ts", "lasttime", "utc", "timeutc"],
    "lat": ["lat", "latitude", "breite", "breitengrad"],
    "lon": ["lng", "lon", "long", "longitude", "laenge", "lange", "langengrad", "laengengrad"],
    "speed": ["speed", "speedkmh", "geschwindigkeit", "kmh", "spd"],
    "course": ["course", "heading", "kurs", "direction", "crs"],
    "alt": ["altitude", "alt", "altitudem", "hoehe", "hohe", "elevation", "ele"],
    "comment": ["comment", "kommentar", "status"],
    "callsign": ["name", "callsign", "srccall", "call", "source", "station", "rufzeichen", "from"],
    "symbol": ["symbol"],
}


def _norm(h: str) -> str:
    h = h.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    h = re.sub(r"\(.*?\)|\[.*?\]", "", h)
    return re.sub(r"[^a-z0-9]", "", h)


def map_columns(headers: list[str]) -> dict[str, str]:
    """Ordnet Felder den Spalten zu. Erste passende Alias-Reihenfolge gewinnt."""
    normed = {_norm(h): h for h in headers}
    result = {}
    for field, aliases in _ALIASES.items():
        for a in aliases:
            if a in normed:
                result[field] = normed[a]
                break
    return result


def parse_time(v) -> datetime:
    if v is None or v == "":
        raise ValueError("Zeit fehlt")
    if isinstance(v, (int, float)) or re.fullmatch(r"\d+(\.\d+)?", str(v).strip()):
        x = float(v)
        if x > 1e12:  # Millisekunden
            x /= 1000
        return datetime.fromtimestamp(x, tz=timezone.utc)
    s = str(v).strip().replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M",
                "%Y/%m/%d %H:%M:%S"):
        try:
            dt = datetime.fromisoformat(s) if fmt is None else datetime.strptime(s, fmt)
        except ValueError:
            continue
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    raise ValueError(f"Zeit nicht lesbar: {v!r}")


def _num(v) -> float | None:
    if v is None:
        return None
    s = str(v).strip().replace(",", ".") if not isinstance(v, (int, float)) else v
    if s == "" or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _rows_from_csv(text: str) -> list[dict]:
    lines = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    if not lines:
        return []
    sample = "\n".join(lines[:20])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return list(csv.DictReader(io.StringIO("\n".join(lines)), dialect=dialect))


def _rows_from_json(data) -> list[dict]:
    if isinstance(data, dict):
        for key in ("entries", "data", "positions", "items", "points"):
            if isinstance(data.get(key), list):
                return data[key]
        raise ValueError("JSON: keine Liste mit Positionen gefunden")
    if isinstance(data, list):
        return data
    raise ValueError("JSON: unbekanntes Format")


def read_rows(content: bytes, filename: str = "") -> list[dict]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")
    stripped = text.lstrip()
    if filename.lower().endswith(".json") or stripped[:1] in ("[", "{"):
        return _rows_from_json(json.loads(text))
    return _rows_from_csv(text)


def parse_file(content: bytes, filename: str = "", default_call: str | None = None):
    """Liefert (positionen, fehler). Positionen sind dicts für store.insert_position."""
    rows = read_rows(content, filename)
    if not rows:
        raise ValueError("Datei enthält keine Datenzeilen")
    cols = map_columns(list(rows[0].keys()))
    missing = [f for f in ("ts", "lat", "lon") if f not in cols]
    if missing:
        names = {"ts": "Zeit", "lat": "Breite (lat)", "lon": "Länge (lng/lon)"}
        raise ValueError(
            "Spalten nicht erkannt: " + ", ".join(names[m] for m in missing)
            + f". Gefunden: {', '.join(rows[0].keys())}"
        )
    if "callsign" not in cols and not default_call:
        raise ValueError("Die Datei enthält kein Rufzeichen. Bitte beim Import eine Station wählen.")

    default_full = None
    if default_call:
        default_full = full_call(*normalize_callsign(default_call))

    out, errors = [], []
    for i, r in enumerate(rows, start=2):
        try:
            call_raw = (r.get(cols["callsign"]) if "callsign" in cols else None) or default_full
            full = full_call(*normalize_callsign(str(call_raw)))
            lat, lon = _num(r.get(cols["lat"])), _num(r.get(cols["lon"]))
            if lat is None or lon is None:
                raise ValueError("Koordinaten fehlen")
            out.append({
                "callsign": full,
                "ts": parse_time(r.get(cols["ts"])),
                "lat": lat,
                "lon": lon,
                "speed": _num(r.get(cols["speed"])) if "speed" in cols else None,
                "course": _num(r.get(cols["course"])) if "course" in cols else None,
                "alt": _num(r.get(cols["alt"])) if "alt" in cols else None,
                "comment": (str(r.get(cols["comment"])) or None) if "comment" in cols and r.get(cols["comment"]) else None,
                "symbol": (str(r.get(cols["symbol"])) or None) if "symbol" in cols and r.get(cols["symbol"]) else None,
            })
        except (ValueError, TypeError) as e:
            errors.append(f"Zeile {i}: {e}")
    return out, errors
