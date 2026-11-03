"""Ostrov G – Přehledy a navigace (sekce 7.7 dokumentu Ostrovy). Jen čte, nic nezapisuje."""
from app.platforma.ostrov import Ostrov

from .endpointy import api
from .kontrakty import CHYBY, MENU, OPRAVNENI
from .stranky import ui

OSTROV = Ostrov(
    nazev="Přehledy",
    prefix="prehledy",
    api=api,
    ui=ui,
    chyby=CHYBY,
    opravneni=OPRAVNENI,
    menu=MENU,
)
