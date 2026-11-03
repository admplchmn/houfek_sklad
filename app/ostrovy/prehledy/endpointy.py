"""HTTP endpointy ostrova G – Přehledy a navigace (/api/prehledy). Kontrakt: sekce 7.7 dokumentu Ostrovy.

Cesty pod /api/prehledy (vše DIL_CIST, jen čtení):
    GET /sken/{kod}, GET /hledat?q=
    GET /urovne/{id}/rozlozeni
    GET /dily/{id}/karta
    GET /zasoby, GET /laser
    GET /pohyby, GET /transakce/{id}
    GET /ciselniky
Endpoint dělá jen: vstup → služba → obálka.
"""
import uuid

from flask import Blueprint

from app.platforma.auth import vyzaduje
from app.platforma.http import dokumentuj, nacti_parametry, odpoved
from app.platforma.kontrakty import Strana

from . import sluzby
from .kontrakty import (
    CiselnikyVystup,
    HledaniFiltr,
    KartaDilu,
    LaserFiltr,
    LaserRadek,
    PohybHistorie,
    PohybyFiltr,
    RozlozeniVystup,
    TransakceDetail,
    Vysledky,
    ZasobyFiltr,
    ZasobyVystup,
)

api = Blueprint("prehledy_api", __name__)


def _zprava_vysledku(vysledky: Vysledky) -> str:
    return "Nic nenalezeno." if not vysledky.polozky else f"Nalezeno: {len(vysledky.polozky)}."


@api.get("/sken/<string:kod>")
@vyzaduje("DIL_CIST")
@dokumentuj(vystup=Vysledky, popis="Naskenovaný kód: místo skladu (se zvýrazněním) nebo číslo dílu.")
def sken(kod: str):
    vysledky = sluzby.sken(kod)
    return odpoved(vysledky, _zprava_vysledku(vysledky))


@api.get("/hledat")
@vyzaduje("DIL_CIST")
@dokumentuj(parametry=HledaniFiltr, vystup=Vysledky, popis="Univerzální hledání s filtry dílu a umístění (21.1.2).")
def hledat():
    vysledky = sluzby.hledej(nacti_parametry(HledaniFiltr))
    return odpoved(vysledky, _zprava_vysledku(vysledky))


@api.get("/urovne/<int:uroven_id>/rozlozeni")
@vyzaduje("DIL_CIST")
@dokumentuj(vystup=RozlozeniVystup, popis="SVG úrovně: geometrie boxů v mm, obsah pozic a barva boxů (17.1).")
def rozlozeni(uroven_id: int):
    return odpoved(sluzby.rozlozeni(uroven_id), "Načteno.")


@api.get("/dily/<int:dil_id>/karta")
@vyzaduje("DIL_CIST")
@dokumentuj(vystup=KartaDilu, popis="Karta dílu: kmenová data, zásoba STAT a DYN, umístění, poslední pohyby.")
def karta(dil_id: int):
    return odpoved(sluzby.karta_dilu(dil_id), "Načteno.")


@api.get("/zasoby")
@vyzaduje("DIL_CIST")
@dokumentuj(parametry=ZasobyFiltr, vystup=ZasobyVystup, popis="Centrální monitoring zásob se souhrnem (13.1).")
def zasoby():
    return odpoved(sluzby.zasoby(nacti_parametry(ZasobyFiltr)), "Načteno.")


@api.get("/laser")
@vyzaduje("DIL_CIST")
@dokumentuj(parametry=LaserFiltr, vystup=Strana[LaserRadek], popis="Díly k doplnění na laser (kap. 14, Q-22).")
def laser():
    return odpoved(sluzby.laser(nacti_parametry(LaserFiltr)), "Načteno.")


@api.get("/pohyby")
@vyzaduje("DIL_CIST")
@dokumentuj(parametry=PohybyFiltr, vystup=Strana[PohybHistorie], popis="Historie skladových pohybů, nejnovější první.")
def pohyby():
    return odpoved(sluzby.pohyby(nacti_parametry(PohybyFiltr)), "Načteno.")


@api.get("/transakce/<uuid:transakce_id>")
@vyzaduje("DIL_CIST")
@dokumentuj(vystup=TransakceDetail, popis="Skladová transakce a její pohyby (např. přesun OUT + IN).")
def transakce(transakce_id: uuid.UUID):
    return odpoved(sluzby.transakce(transakce_id), "Načteno.")


@api.get("/ciselniky")
@vyzaduje("DIL_CIST")
@dokumentuj(vystup=CiselnikyVystup, popis="Všechny číselníky pro filtry najednou.")
def ciselniky():
    return odpoved(sluzby.ciselniky(), "Načteno.")
