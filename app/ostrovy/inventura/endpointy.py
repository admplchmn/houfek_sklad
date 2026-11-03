"""HTTP endpointy ostrova F – Inventura (/api/inventura). Kontrakt: sekce 7.6 dokumentu Ostrovy.

Cesty pod /api/inventura ("" = kořen kolekce):
    POST "", GET "", GET /{id}                                                 (INVENTURA)
    POST /{id}/polozky/{vnitrniPoziceId}, POST /{id}/zrusit                    (INVENTURA)
    POST /{id}/dokoncit                                                        (KOREKCE, requestId)
Endpoint dělá jen: vstup → služba → obálka.
"""
from flask import Blueprint

from app.platforma.auth import kontext, vyzaduje
from app.platforma.http import dokumentuj, nacti_parametry, nacti_vstup, odpoved
from app.platforma.kontrakty import DuvodVstup, Strana

from . import sluzby
from .kontrakty import (
    DokonceniVstup,
    DokonceniVysledek,
    InventuraDetail,
    InventuraRadek,
    InventuryFiltr,
    NovaInventuraVstup,
    PolozkaInventury,
    ZapisPolozkyVstup,
)

api = Blueprint("inventura_api", __name__)


@api.get("")
@vyzaduje("INVENTURA")
@dokumentuj(parametry=InventuryFiltr, vystup=Strana[InventuraRadek], popis="Inventury (výchozí: rozpracované).")
def seznam():
    return odpoved(sluzby.seznam_inventur(nacti_parametry(InventuryFiltr)), "Načteno.")


@api.post("")
@vyzaduje("INVENTURA")
@dokumentuj(vstup=NovaInventuraVstup, vystup=InventuraDetail,
            popis="Založí inventuru rozsahu FULL | PRAC | REGAL | UROVEN | BOX | POZICE se snímkem stavu.")
def zaloz():
    inventura = sluzby.zaloz_inventuru(vstup=nacti_vstup(NovaInventuraVstup), kdo=kontext())
    return odpoved(inventura, f"Inventura {inventura.inventura_id} založena ({inventura.pocet_polozek} pozic).")


@api.get("/<int:inventura_id>")
@vyzaduje("INVENTURA")
@dokumentuj(vystup=InventuraDetail, popis="Inventura s položkami; slepá skrývá očekávaný stav nezapsaných položek.")
def detail(inventura_id: int):
    return odpoved(sluzby.detail_inventury(inventura_id), "Načteno.")


@api.post("/<int:inventura_id>/polozky/<int:vnitrni_pozice_id>")
@vyzaduje("INVENTURA")
@dokumentuj(vstup=ZapisPolozkyVstup, vystup=PolozkaInventury,
            popis="Zapíše nalezený díl a počet (nebo prázdné); vrátí vyhodnocení SHODA | ROZDIL | JINY_DIL.")
def zapis(inventura_id: int, vnitrni_pozice_id: int):
    polozka = sluzby.zapis_polozku(inventura_id=inventura_id, vnitrni_pozice_id=vnitrni_pozice_id,
                                   vstup=nacti_vstup(ZapisPolozkyVstup), kdo=kontext())
    return odpoved(polozka, {"SHODA": "Shoda.", "ROZDIL": f"Rozdíl {polozka.rozdil_ks:+d} ks.",
                             "JINY_DIL": "Nalezen jiný díl."}[polozka.vyhodnoceni or "SHODA"])


@api.post("/<int:inventura_id>/zrusit")
@vyzaduje("INVENTURA")
@dokumentuj(vstup=DuvodVstup, vystup=InventuraRadek, popis="Zruší rozpracovanou inventuru bez pohybů.")
def zrus(inventura_id: int):
    return odpoved(sluzby.zrus_inventuru(inventura_id=inventura_id, vstup=nacti_vstup(DuvodVstup), kdo=kontext()),
                   "Inventura zrušena.")


@api.post("/<int:inventura_id>/dokoncit")
@vyzaduje("KOREKCE")
@dokumentuj(vstup=DokonceniVstup, vystup=DokonceniVysledek,
            popis="Zaúčtuje rozdíly v jedné transakci pohyby INVENTURA a uzavře inventuru. Skladový příkaz.")
def dokonci(inventura_id: int):
    vysledek = sluzby.dokonci_inventuru(inventura_id=inventura_id, vstup=nacti_vstup(DokonceniVstup), kdo=kontext())
    return odpoved(vysledek, f"Inventura dokončena: {len(vysledek.pohyby)} korekčních pohybů.")
