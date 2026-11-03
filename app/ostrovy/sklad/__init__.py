"""Ostrov E – Sklad: pohyby a zásoby (sekce 7.5 dokumentu Ostrovy)."""
from app.platforma.ostrov import Ostrov

from .endpointy import api
from .kontrakty import CHYBY, MENU, OPRAVNENI
from .stranky import ui

OSTROV = Ostrov(
    nazev="Sklad",
    prefix="sklad",
    api=api,
    ui=ui,
    tabulky=["ObsahPozice", "SkladovyPohyb", "TypPohybu", "StatickeUmisteniDilu", "UpozorneniZasoby"],
    pohledy=["v_ObsahPozice", "v_StatickeMisto", "v_ZasobaDilu", "v_PohybDetail"],
    chyby=CHYBY,
    opravneni=OPRAVNENI,
    menu=MENU,
)
