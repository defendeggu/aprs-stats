"""Hilfsfunktionen rund um Rufzeichen und APRS-Pfade (ohne Datenbank, testbar)."""
import re

CALL_RE = re.compile(r"^[A-Z0-9]{1,9}$")
SSID_RE = re.compile(r"^[A-Z0-9]{1,2}$")

# Generische Aliase, die keine Digipeater-Rufzeichen sind
_ALIAS_RE = re.compile(
    r"^(WIDE|RELAY|TRACE|TCPIP|TCPXX|NOGATE|RFONLY|ECHO|GATE|HOP|ARISS|SGATE|BEACON)\d*(-\d+)?\*?$"
)
_QCONSTRUCT_RE = re.compile(r"^qA[A-Za-z]$")


def normalize_ssid(ssid: str | None) -> str:
    """'' = ohne SSID, '*' = alle SSIDs, sonst 1–2 Zeichen. '0' gilt als ohne SSID."""
    s = (ssid or "").strip().upper().lstrip("-")
    if s in ("", "0"):
        return ""
    if s == "*":
        return "*"
    if not SSID_RE.match(s):
        raise ValueError(f"Ungültige SSID: {ssid!r}")
    return s


def normalize_callsign(callsign: str) -> tuple[str, str]:
    """'hb3xva-9' -> ('HB3XVA', '9'); 'HB3XVA' -> ('HB3XVA', '')."""
    c = (callsign or "").strip().upper()
    base, _, ssid = c.partition("-")
    if not CALL_RE.match(base):
        raise ValueError(f"Ungültiges Rufzeichen: {callsign!r}")
    return base, normalize_ssid(ssid)


def full_call(base: str, ssid: str) -> str:
    return f"{base}-{ssid}" if ssid and ssid != "*" else base


def split_full(full: str) -> tuple[str, str]:
    base, _, ssid = full.upper().partition("-")
    return base, "" if ssid in ("", "0") else ssid


def build_filter(stations: list[tuple[str, str]]) -> str:
    """APRS-IS-Budlist-Filter aus (callsign, ssid)-Paaren, z. B. 'b/HB3XVA*/HB9ABC-7'."""
    parts = []
    for base, ssid in sorted(set(stations)):
        if ssid == "*":
            parts.append(f"{base}*")
        else:
            parts.append(full_call(base, ssid))
    return "b/" + "/".join(parts) if parts else ""


def matches(full: str, stations: list[tuple[str, str]]) -> bool:
    """Gehört ein empfangenes Rufzeichen zu einer der Stationen? (b/CALL* ist ein Präfix-Filter)"""
    base, ssid = split_full(full)
    for sb, ss in stations:
        if sb != base:
            continue
        if ss == "*" or ss == ssid:
            return True
    return False


def parse_path(path: list[str]) -> dict:
    """Pfad zerlegen: benutzte Digipeater, q-Konstrukt und iGate.

    Beispiel: ['HB9F*', 'WIDE2-1', 'qAR', 'HB9XX-10']
      -> digis=['HB9F'], qconstruct='qAR', igate='HB9XX-10'
    Benutzt sind alle Einträge bis und mit dem letzten mit '*' (H-Bit).
    """
    path = [p for p in (path or []) if p]
    q_idx = next((i for i, p in enumerate(path) if _QCONSTRUCT_RE.match(p)), None)
    rf = path[:q_idx] if q_idx is not None else path
    qconstruct = path[q_idx] if q_idx is not None else None
    igate = path[q_idx + 1] if q_idx is not None and q_idx + 1 < len(path) else None

    last_used = max((i for i, p in enumerate(rf) if p.endswith("*")), default=-1)
    digis = []
    for p in rf[: last_used + 1]:
        name = p.rstrip("*")
        if _ALIAS_RE.match(p) or not re.match(r"^[A-Z0-9]{1,9}(-[A-Z0-9]{1,2})?$", name):
            continue
        digis.append(name)
    via_tcpip = any(p.rstrip("*") in ("TCPIP", "TCPXX") for p in rf)
    return {"digis": digis, "qconstruct": qconstruct, "igate": igate, "tcpip": via_tcpip}


# --- Baken (eigene Position senden) ----------------------------------------

TOCALL = "APZSTA"  # APZ… = experimentelle Software (APRS-Spezifikation)
OVERLAY_RE = re.compile(r"^[0-9A-Z]$")
MAX_COMMENT_BYTES = 43


def validate_symbol(table: str, code: str) -> tuple[str, str]:
    """Symboltafel '/' (primär), '\\' (alternativ) oder Overlay-Zeichen 0-9/A-Z (alternativ mit Overlay)."""
    table = (table or "")[:1]
    if table not in ("/", "\\") and not OVERLAY_RE.match(table or ""):
        raise ValueError("Ungültige Symboltafel (erlaubt: / \\ oder Overlay 0-9, A-Z)")
    if not code or len(code) != 1 or not (33 <= ord(code) <= 126):
        raise ValueError("Ungültiger Symbolcode")
    return table, code


def _ambiguate(s: str, level: int) -> str:
    """Positionsunschärfe: die letzten `level` Ziffern der Minuten durch Leerzeichen ersetzen."""
    if not level:
        return s
    chars = list(s)
    digits = [i for i, c in enumerate(chars) if c.isdigit()]
    # nur Minutenstellen (die letzten 4 Ziffern: MM.mm)
    for i in reversed(digits[-4:][-level:] if level <= 4 else digits[-4:]):
        chars[i] = " "
    return "".join(chars)


def format_lat(lat: float, ambiguity: int = 0) -> str:
    if not -90 <= lat <= 90:
        raise ValueError("Breite ausserhalb -90…90")
    hemi = "N" if lat >= 0 else "S"
    lat = abs(lat)
    deg = int(lat)
    minutes = round((lat - deg) * 60, 2)
    if minutes >= 60:
        deg, minutes = deg + 1, 0.0
    return _ambiguate(f"{deg:02d}{minutes:05.2f}", ambiguity) + hemi


def format_lon(lon: float, ambiguity: int = 0) -> str:
    if not -180 <= lon <= 180:
        raise ValueError("Länge ausserhalb -180…180")
    hemi = "E" if lon >= 0 else "W"
    lon = abs(lon)
    deg = int(lon)
    minutes = round((lon - deg) * 60, 2)
    if minutes >= 60:
        deg, minutes = deg + 1, 0.0
    return _ambiguate(f"{deg:03d}{minutes:05.2f}", ambiguity) + hemi


def clean_comment(comment: str | None) -> str:
    c = "".join(ch for ch in (comment or "") if ch.isprintable() and ch not in "|~").strip()
    if len(c.encode("utf-8")) > MAX_COMMENT_BYTES:
        raise ValueError(f"Kommentar zu lang (höchstens {MAX_COMMENT_BYTES} Zeichen)")
    return c


def position_packet(full: str, lat: float, lon: float, table: str, code: str,
                    comment: str | None = None, altitude_m: float | None = None,
                    ambiguity: int = 0) -> str:
    """APRS-Positionspaket ohne Messaging ('!'), unkomprimiert, für APRS-IS."""
    table, code = validate_symbol(table, code)
    body = f"!{format_lat(lat, ambiguity)}{table}{format_lon(lon, ambiguity)}{code}"
    if altitude_m is not None:
        feet = round(altitude_m / 0.3048)
        if not -99999 <= feet <= 999999:
            raise ValueError("Höhe ausserhalb des gültigen Bereichs")
        body += f"/A={feet:06d}" if feet >= 0 else f"/A=-{abs(feet):05d}"
    body += clean_comment(comment)
    return f"{full}>{TOCALL},TCPIP*:{body}"
