import struct

import pytest

from aprs_stats.boundaries import KANTON_ABBR, gpkg_to_wkb
from aprs_stats.geocode import suggestion


def _gpkg(wkb: bytes, envelope: int) -> bytes:
    flags = 0x01 | (envelope << 1)                     # little endian
    size = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[envelope]
    return b"GP" + bytes([0, flags]) + struct.pack("<i", 2056) + b"\0" * size + wkb


@pytest.mark.parametrize("envelope", [0, 1, 2, 3, 4])
def test_gpkg_to_wkb(envelope):
    wkb = b"\x01" + struct.pack("<I", 1006) + b"rest"
    assert gpkg_to_wkb(_gpkg(wkb, envelope)) == wkb


def test_gpkg_to_wkb_rejects_other():
    with pytest.raises(ValueError):
        gpkg_to_wkb(b"\x01\x02\x03\x04" + b"\0" * 10)
    with pytest.raises(ValueError):
        gpkg_to_wkb(b"GP\x00" + bytes([0x01 | (6 << 1)]) + b"\0" * 10)


def test_kantone_complete():
    assert len(KANTON_ABBR) == 26
    assert KANTON_ABBR[9] == "ZG" and KANTON_ABBR[26] == "JU"


def test_suggestion_name_and_locality():
    res = {"name": "Coop", "address": {"road": "Bahnhofstrasse", "house_number": "1", "town": "Zug"}}
    assert suggestion(res) == "Coop, Zug"


def test_suggestion_address():
    res = {"name": "", "address": {"road": "Bahnhofstrasse", "house_number": "12", "village": "Cham"}}
    assert suggestion(res) == "Bahnhofstrasse 12, Cham"


def test_suggestion_only_locality():
    assert suggestion({"address": {"city": "Luzern"}}) == "Luzern"
    assert suggestion({"name": "Luzern", "address": {"city": "Luzern"}}) == "Luzern"


def test_suggestion_fallback_display_name():
    assert suggestion({"display_name": "Irgendwo, Schweiz", "address": {}}) == "Irgendwo"
