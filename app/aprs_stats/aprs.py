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
