"""HTTP endpointy ostrova. Endpoint dělá jen 3 kroky: načti vstup → zavolej službu → vrať obálku.

Žádná skladová logika ani SQL tady nepatří.
"""
from flask import Blueprint

from app.platforma.auth import kontext, vyzaduje
from app.platforma.http import dokumentuj, nacti_vstup, odpoved

from . import sluzby
from .kontrakty import PolozkaVstup, PolozkaVysledek

api = Blueprint("sablona_api", __name__)


@api.post("/polozky")
@vyzaduje("SABLONA_ZAPIS")
@dokumentuj(vstup=PolozkaVstup, vystup=PolozkaVysledek, popis="Založí položku (vzor skladového příkazu).")
def zaloz_polozku():
    vstup = nacti_vstup(PolozkaVstup)
    vysledek = sluzby.zaloz_polozku(vstup=vstup, kdo=kontext())
    return odpoved(vysledek, f"Založeno {vysledek.pocet_ks} ks {vysledek.kod}.")


@api.get("/polozky/<int:polozka_id>")
@dokumentuj(vystup=PolozkaVysledek, popis="Detail položky (vzor čtení).")
def detail_polozky(polozka_id: int):
    return odpoved(sluzby.nacti_polozku(polozka_id))
