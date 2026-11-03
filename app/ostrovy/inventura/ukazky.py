"""Vzorová data ostrova F pro kostru služeb a testy (koncový ostrov nemá rozhraní, takže ani jeho kostru).

Navazují na vzory ostrovů C, D a E:

    1  BOX 38 (BPLE038)    ROZPRACOVANÁ, slepá   G zapsáno prázdné · H, CH čekají ·
                                                 I zapsáno 7 ks, ale od zápisu pohyb → PŘEPOČÍTAT
    2  POZICE 502          DOKONČENÁ
    3  BOX 137 (BSTAT037)  ROZPRACOVANÁ, slepá   vše zapsáno; na BSTAT037-1 nalezen jiný díl (12 místo 14) → cíl povinný
    4  POZICE 101          ROZPRACOVANÁ          zapsáno 38 ks místo 40, pak výdej 5001 → PŘEPOČÍTAT
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.platforma.kostra import jen_ve_vyvoji

jen_ve_vyvoji(__name__)  # v provozu vzorová data nikdy (app/platforma/kostra.py)


@dataclass(frozen=True)
class VzorPolozky:
    vnitrni_pozice_id: int
    kod: str
    typ_boxu: str
    ocekavany_dil_id: int | None
    ocekavany_pocet_ks: int
    skutecny_dil_id: int | None = None
    skutecny_pocet_ks: int | None = None          # None = nezapsáno
    pohyb_pri_zapisu: int | None = None           # PosledniPohybID v okamžiku zápisu (Q-16, D8)
    datum_kontroly: datetime | None = None


@dataclass(frozen=True)
class VzorInventury:
    inventura_id: int
    typ_rozsahu: str
    cil_id: int | None
    stav_inventury: str
    slepa: bool
    datum_zahajeni: datetime
    datum_dokonceni: datetime | None
    zalozil_uzivatel_id: int
    polozky: tuple[VzorPolozky, ...]
    poznamka: str | None = None


_RANO = datetime(2026, 10, 30, 6, 30)
_KONTROLA = datetime(2026, 10, 30, 7, 5)

INVENTURY = {i.inventura_id: i for i in (
    VzorInventury(1, "BOX", 38, "ROZPRACOVANA", True, _RANO, None, 1, (
        VzorPolozky(381, "BPLE038-G", "DYN", None, 0, None, 0, None, _KONTROLA),
        VzorPolozky(382, "BPLE038-H", "DYN", None, 0),
        VzorPolozky(383, "BPLE038-CH", "DYN", None, 0),
        VzorPolozky(384, "BPLE038-I", "DYN", 14, 10, 14, 7, 5002, _KONTROLA),   # pak výdej 5004
    )),
    VzorInventury(2, "POZICE", 502, "DOKONCENA", False, datetime(2026, 10, 28, 14, 0),
                  datetime(2026, 10, 28, 14, 20), 2, (
        VzorPolozky(502, "BSTAT037-2", "STAT", None, 0, None, 0, 4990, datetime(2026, 10, 28, 14, 10)),
    ), "Kontrola po vyprázdnění."),
    VzorInventury(3, "BOX", 137, "ROZPRACOVANA", True, _RANO, None, 1, (
        VzorPolozky(504, "BSTAT037-4", "STAT", None, 0, None, 0, None, _KONTROLA),
        VzorPolozky(503, "BSTAT037-3", "STAT", None, 0, None, 0, None, _KONTROLA),
        VzorPolozky(501, "BSTAT037-1", "STAT", 14, 12, 12, 3, 5003, _KONTROLA),
        VzorPolozky(502, "BSTAT037-2", "STAT", None, 0, None, 0, 4990, _KONTROLA),
    )),
    VzorInventury(4, "POZICE", 101, "ROZPRACOVANA", False, datetime(2026, 10, 29, 9, 0), None, 2, (
        VzorPolozky(101, "BPLE037-A", "DYN", 12, 40, 12, 38, 4999, datetime(2026, 10, 29, 9, 30)),
    )),
)}
