"""HTTP endpointy ostrova D – Díly a číselníky (/api/dily). Kontrakt: sekce 7.4 dokumentu Ostrovy.

Cesty pod /api/dily ("" = kořen kolekce):
    GET "", GET /{id}, GET /ciselniky/{typ}                               (DIL_CIST)
    POST "", PATCH /{id}, POST /{id}/deaktivovat, PATCH /{id}/velikost    (KMEN_EDIT)
    POST /ciselniky/{typ}, PATCH /ciselniky/{typ}/{id},
    POST /ciselniky/{typ}/{id}/deaktivovat                                (KMEN_EDIT)
{typ} = materialy | tloustky | operace. Endpoint dělá jen: vstup → služba → obálka.
"""
from flask import Blueprint

from app.platforma.auth import kontext, vyzaduje
from app.platforma.http import dokumentuj, nacti_parametry, nacti_vstup, odpoved
from app.platforma.kontrakty import CiselnikRadek, DuvodVstup, Seznam, Strana

from . import sluzby
from .kontrakty import (
    DilRadek,
    DilyFiltr,
    NovyCiselnikVstup,
    NovyDilVstup,
    ZmenaCiselnikuVstup,
    ZmenaDiluVstup,
    ZmenaVelikostiVstup,
)

api = Blueprint("dily_api", __name__)

# --- čtení (DIL_CIST) ----------------------------------------------------------------------------


@api.get("")
@vyzaduje("DIL_CIST")
@dokumentuj(parametry=DilyFiltr, vystup=Strana[DilRadek], popis="Díly s filtrem a stránkováním.")
def seznam():
    return odpoved(sluzby.seznam_dilu(nacti_parametry(DilyFiltr)), "Načteno.")


@api.get("/<int:dil_id>")
@vyzaduje("DIL_CIST")
@dokumentuj(vystup=DilRadek, popis="Kmenová data dílu. Kartu se zásobou vrací /api/prehledy/dily/{id}/karta.")
def detail(dil_id: int):
    return odpoved(sluzby.detail_dilu(dil_id), "Načteno.")


@api.get("/ciselniky/<string:typ>")
@vyzaduje("DIL_CIST")
@dokumentuj(vystup=Seznam[CiselnikRadek], popis="Číselník materiálů, tlouštěk nebo prvních operací.")
def ciselnik(typ: str):
    return odpoved(sluzby.ciselnik(typ), "Načteno.")


# --- díl (KMEN_EDIT) -----------------------------------------------------------------------------


@api.post("")
@vyzaduje("KMEN_EDIT")
@dokumentuj(vstup=NovyDilVstup, vystup=DilRadek, popis="Založí díl. Identifikační číslo se normalizuje.")
def zaloz():
    dil = sluzby.zaloz_dil(vstup=nacti_vstup(NovyDilVstup), kdo=kontext())
    return odpoved(dil, f"Díl {dil.identifikacni_cislo} založen.")


@api.patch("/<int:dil_id>")
@vyzaduje("KMEN_EDIT")
@dokumentuj(vstup=ZmenaDiluVstup, vystup=DilRadek, popis="Změní poslaná pole dílu; důvod jde do auditu.")
def zmen(dil_id: int):
    return odpoved(sluzby.zmen_dil(dil_id=dil_id, vstup=nacti_vstup(ZmenaDiluVstup), kdo=kontext()), "Uloženo.")


@api.post("/<int:dil_id>/deaktivovat")
@vyzaduje("KMEN_EDIT")
@dokumentuj(vstup=DuvodVstup, vystup=DilRadek, popis="Vyřadí díl, který nemá obsah na žádné pozici.")
def deaktivuj(dil_id: int):
    return odpoved(sluzby.deaktivuj_dil(dil_id=dil_id, vstup=nacti_vstup(DuvodVstup), kdo=kontext()), "Díl vyřazen.")


@api.patch("/<int:dil_id>/velikost")
@vyzaduje("KMEN_EDIT")
@dokumentuj(vstup=ZmenaVelikostiVstup, vystup=DilRadek,
            popis="Změní velikost pozice dílu; zakázáno, dokud má díl obsah v DYN (Q-28).")
def zmen_velikost(dil_id: int):
    dil = sluzby.zmen_velikost(dil_id=dil_id, vstup=nacti_vstup(ZmenaVelikostiVstup), kdo=kontext())
    return odpoved(dil, "Velikost změněna.")


# --- číselníky (KMEN_EDIT) -----------------------------------------------------------------------


@api.post("/ciselniky/<string:typ>")
@vyzaduje("KMEN_EDIT")
@dokumentuj(vstup=NovyCiselnikVstup, vystup=CiselnikRadek, popis="Přidá položku číselníku.")
def zaloz_polozku(typ: str):
    polozka = sluzby.zaloz_polozku_ciselniku(typ=typ, vstup=nacti_vstup(NovyCiselnikVstup), kdo=kontext())
    return odpoved(polozka, f"Položka {polozka.kod} přidána.")


@api.patch("/ciselniky/<string:typ>/<int:polozka_id>")
@vyzaduje("KMEN_EDIT")
@dokumentuj(vstup=ZmenaCiselnikuVstup, vystup=CiselnikRadek, popis="Změní kód nebo název položky číselníku.")
def zmen_polozku(typ: str, polozka_id: int):
    polozka = sluzby.zmen_polozku_ciselniku(typ=typ, polozka_id=polozka_id, vstup=nacti_vstup(ZmenaCiselnikuVstup),
                                            kdo=kontext())
    return odpoved(polozka, "Uloženo.")


@api.post("/ciselniky/<string:typ>/<int:polozka_id>/deaktivovat")
@vyzaduje("KMEN_EDIT")
@dokumentuj(vstup=DuvodVstup, vystup=CiselnikRadek, popis="Vyřadí položku číselníku pro nové díly.")
def deaktivuj_polozku(typ: str, polozka_id: int):
    polozka = sluzby.deaktivuj_polozku_ciselniku(typ=typ, polozka_id=polozka_id, vstup=nacti_vstup(DuvodVstup),
                                                 kdo=kontext())
    return odpoved(polozka, f"Položka {polozka.kod} vyřazena.")
