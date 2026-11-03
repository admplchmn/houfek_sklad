"""Ostrov C – Struktura skladu a kódy (sekce 7.3 dokumentu Ostrovy)."""
from app.platforma.ostrov import Ostrov

from .endpointy import api
from .kontrakty import CHYBY, MENU, OPRAVNENI
from .stranky import ui

OSTROV = Ostrov(
    nazev="Struktura",
    prefix="struktura",
    api=api,
    ui=ui,
    tabulky=["Firma", "Pracoviste", "Regal", "Uroven", "Pozice", "Box", "VnitrniPoziceBoxu",
             "TypBoxu", "CleneniBoxu", "SablonaCleneni", "VelikostPozice"],
    pohledy=["v_Misto", "v_VelikostPozice"],
    chyby=CHYBY,
    opravneni=OPRAVNENI,
    menu=MENU,
)
