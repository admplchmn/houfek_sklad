"""Vzorová data ostrova G pro kostru služeb a testy (koncový ostrov nemá rozhraní, takže ani jeho kostru).

Historie pohybů a skladových transakcí – ostatní data G skládá z rozhraní ostrovů B, C, D a E.
PohybID a časy navazují na vzory E (POSLEDNI_POHYBY) a F (inventury, PREPOCITAT).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.platforma.kostra import jen_ve_vyvoji

jen_ve_vyvoji(__name__)  # v provozu vzorová data nikdy (app/platforma/kostra.py)


def transakce_id(pohyb_id: int) -> uuid.UUID:
    return uuid.UUID(f"8b0d5c1e-0000-4000-8000-{pohyb_id:012d}")


@dataclass(frozen=True)
class VzorPohybu:
    pohyb_id: int
    datum_cas: datetime
    typ_pohybu: str
    dil_id: int
    vnitrni_pozice_id: int
    mnozstvi: int
    stav_pred_ks: int
    stav_po_ks: int
    uzivatel_id: int
    terminal_id: int | None
    typ_operace: str              # @transakce(…) – SkladovaTransakce.TypOperace
    poznamka: str | None = None


POHYBY = [
    VzorPohybu(4990, datetime(2026, 10, 28, 7, 15), "VYDEJ", 13, 502, -5, 5, 0, 2, None, "VYDEJ"),
    VzorPohybu(4999, datetime(2026, 10, 29, 8, 40), "PRIJEM", 12, 101, 40, 0, 40, 1, 1, "PRIJEM_DYN"),
    VzorPohybu(5001, datetime(2026, 10, 29, 10, 12), "VYDEJ", 12, 101, -10, 40, 30, 1, 1, "VYDEJ",
               "Na ohraňování"),
    VzorPohybu(5002, datetime(2026, 10, 29, 11, 30), "PRIJEM", 14, 384, 10, 0, 10, 1, 1, "PRIJEM_DYN"),
    VzorPohybu(5003, datetime(2026, 10, 29, 13, 40), "PRIJEM", 14, 501, 4, 8, 12, 1, 1, "PRIJEM_STAT"),
    VzorPohybu(5004, datetime(2026, 10, 30, 7, 20), "VYDEJ", 14, 384, -2, 10, 8, 1, 1, "VYDEJ"),
]
