"""HTTP kontrakty ostrova: vstupy, výstupy, chybové kódy, oprávnění a menu.

Po zmrazení (K1) se tu jen přidává (P10).
"""
from __future__ import annotations

from pydantic import Field

from app.platforma.chyby import Chyba
from app.platforma.kontrakty import Cas, SkladovyVstup, Vystup
from app.platforma.ostrov import PolozkaMenu


class PolozkaVstup(SkladovyVstup):
    """Založení položky – skladový příkaz, proto requestId povinný."""

    kod: str = Field(..., min_length=1, max_length=20)
    pocet_ks: int = Field(..., gt=0)


class PolozkaVysledek(Vystup):
    polozka_id: int
    kod: str
    pocet_ks: int
    zalozeno: Cas


CHYBY = [
    Chyba("SABLONA_PRILIS_MNOHO", 409, "Počet kusů je nad limitem šablony."),
]

OPRAVNENI = ["SABLONA_ZAPIS"]

MENU = [
    PolozkaMenu("Šablona", "/ui/sablona/ukazka", opravneni="SABLONA_ZAPIS"),
]
