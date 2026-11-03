"""Služby = operace ostrova. Jedna operace = jedna transakce (@transakce) nebo jen čtení (@cteni).

Cizí ostrov se volá jen přes jeho rozhrani, importované jako modul:
    from app.ostrovy.struktura import rozhrani as struktura
    misto = struktura.najdi_vnitrni_pozici(spoj, vstup.kod)
"""
from __future__ import annotations

from app.platforma.chyby import AppError
from app.platforma.db import Spojeni, cteni
from app.platforma.transakce import transakce
from app.platforma.typy import Kontext

from . import domena, repozitar
from .kontrakty import PolozkaVstup, PolozkaVysledek


@transakce("SABLONA_ZALOZ", skladova=True)
def zaloz_polozku(spoj: Spojeni, vstup: PolozkaVstup, kdo: Kontext) -> PolozkaVysledek:
    domena.over_pocet(vstup.pocet_ks)                       # čisté pravidlo, bez DB
    polozka_id = repozitar.vloz_polozku(spoj, vstup.kod, vstup.pocet_ks)
    radek = repozitar.nacti_polozku(spoj, polozka_id)
    return _vysledek(radek)


@cteni
def nacti_polozku(spoj: Spojeni, polozka_id: int) -> PolozkaVysledek:
    radek = repozitar.nacti_polozku(spoj, polozka_id)
    if radek is None:
        raise AppError("NOT_FOUND", f"Položka {polozka_id} neexistuje.")
    return _vysledek(radek)


def _vysledek(radek: dict) -> PolozkaVysledek:
    return PolozkaVysledek(polozka_id=radek["PolozkaID"], kod=radek["Kod"], pocet_ks=radek["PocetKs"],
                           zalozeno=radek["Zalozeno"])
