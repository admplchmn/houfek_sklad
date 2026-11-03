"""Ostrov D – Díly a číselníky (sekce 7.4 dokumentu Ostrovy)."""
from app.platforma.ostrov import Ostrov

from .endpointy import api
from .kontrakty import CHYBY, MENU, OPRAVNENI
from .stranky import ui

OSTROV = Ostrov(
    nazev="Díly",
    prefix="dily",
    api=api,
    ui=ui,
    tabulky=["Dil", "Material", "TloustkaMaterialu", "PrvniVyrobniOperace"],
    pohledy=["v_Dil"],
    chyby=CHYBY,
    opravneni=OPRAVNENI,
    menu=MENU,
)
