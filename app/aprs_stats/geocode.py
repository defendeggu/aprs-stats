"""Reverse-Geocoding über OpenStreetMap Nominatim, nur auf Knopfdruck.

Nutzungsregeln: https://operations.osmfoundation.org/policies/nominatim/
(höchstens 1 Anfrage pro Sekunde, eindeutiger User-Agent, Quellenangabe © OpenStreetMap).
"""
import json
import os
import threading
import time
import urllib.parse
import urllib.request

from . import __version__

NOMINATIM_URL = (os.environ.get("NOMINATIM_URL", "").strip() or "https://nominatim.openstreetmap.org").rstrip("/")
NOMINATIM_EMAIL = os.environ.get("NOMINATIM_EMAIL", "").strip()
USER_AGENT = f"aprs-stats/{__version__} (self-hosted)"
ATTRIBUTION = "© OpenStreetMap-Mitwirkende, ODbL"
MIN_INTERVAL_S = 1.1

_lock = threading.Lock()
_last = 0.0
_cache: dict[tuple[float, float], dict] = {}

LOCALITY_KEYS = ("village", "town", "city", "hamlet", "suburb", "municipality")


def suggestion(res: dict) -> str:
    """Kurzer Ortsname aus einer Nominatim-Antwort: 'Name, Ort' oder 'Strasse Nr, Ort'."""
    a = res.get("address") or {}
    locality = next((a[k] for k in LOCALITY_KEYS if a.get(k)), "")
    name = (res.get("name") or "").strip()
    road = " ".join(x for x in (a.get("road") or a.get("pedestrian") or a.get("path"), a.get("house_number")) if x)
    first = name or road
    if first and locality and first != locality:
        return f"{first}, {locality}"
    return first or locality or (res.get("display_name") or "").split(",")[0].strip()


def reverse(lat: float, lon: float) -> dict:
    key = (round(lat, 5), round(lon, 5))
    if key in _cache:
        return _cache[key]
    params = {"format": "jsonv2", "lat": f"{lat:.6f}", "lon": f"{lon:.6f}", "zoom": "18",
              "addressdetails": "1", "accept-language": "de"}
    if NOMINATIM_EMAIL:
        params["email"] = NOMINATIM_EMAIL
    url = f"{NOMINATIM_URL}/reverse?{urllib.parse.urlencode(params)}"
    global _last
    with _lock:
        wait = _last + MIN_INTERVAL_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=15) as r:
                res = json.load(r)
        finally:
            _last = time.monotonic()
    if res.get("error"):
        raise LookupError(res["error"])
    out = {"suggestion": suggestion(res), "display_name": res.get("display_name"),
           "category": res.get("category"), "type": res.get("type"), "attribution": ATTRIBUTION}
    _cache[key] = out
    return out
