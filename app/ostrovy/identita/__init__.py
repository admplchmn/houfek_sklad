"""Ostrov B – Identita (sekce 7.2 dokumentu Ostrovy)."""
from app.platforma.ostrov import Ostrov

from .endpointy import api
from .kontrakty import CHYBY, MENU, OPRAVNENI
from .sluzby import over_kontext
from .stranky import ui

OSTROV = Ostrov(
    nazev="Identita",
    prefix="identita",
    api=api,
    ui=ui,
    tabulky=["Uzivatel", "Role", "Opravneni", "RoleOpravneni", "Terminal"],
    pohledy=["v_Uzivatel", "v_Terminal"],
    chyby=CHYBY,
    opravneni=OPRAVNENI,
    menu=MENU,
    overeni_kontextu=over_kontext,   # aktivita a aktuální oprávnění při každém požadavku (docs/adr/0007)
)
