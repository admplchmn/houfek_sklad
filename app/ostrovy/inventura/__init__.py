"""Ostrov F – Inventura (sekce 7.6 dokumentu Ostrovy). Koncový ostrov: rozdíly účtuje jen přes
sklad.zauctuj_korekci() v jedné transakci dokončení."""
from app.platforma.ostrov import Ostrov

from .endpointy import api
from .kontrakty import CHYBY, MENU, OPRAVNENI
from .stranky import ui

OSTROV = Ostrov(
    nazev="Inventura",
    prefix="inventura",
    api=api,
    ui=ui,
    tabulky=["Inventura", "InventuraPolozka"],
    chyby=CHYBY,
    opravneni=OPRAVNENI,
    menu=MENU,
)
