"""HTTP endpointy ostrova E – Sklad: pohyby a zásoby (/api/sklad). Kontrakt: sekce 7.5 dokumentu Ostrovy.

Cesty pod /api/sklad:
    GET /kandidati-dyn?dilId=&regalId=|kodRegalu=&vcetneOstatnichRegalu=       (SKLAD_PRIJEM)
    POST /prijem-dyn, POST /prijem-stat                                        (SKLAD_PRIJEM, requestId)
    POST /vydej                                                                (SKLAD_VYDEJ, requestId)
    POST /presun                                                               (SKLAD_PRESUN, requestId)
    GET|POST /stat-mista, PATCH /stat-mista/{id}, POST /stat-mista/{id}/ukoncit (STAT_EDIT)
    GET /upozorneni                                                            (DIL_CIST)
    POST /upozorneni/{id}/uzavrit                                              (UPOZORNENI_UZAVRIT)
Endpoint dělá jen: vstup → služba → obálka. Opakované odeslání se stejným requestId vrátí
stejnou odpověď i transakceId a nic nezapíše (docs/adr/0004).
"""
from flask import Blueprint

from app.platforma.auth import kontext, vyzaduje
from app.platforma.http import dokumentuj, nacti_parametry, nacti_vstup, odpoved
from app.platforma.kontrakty import DuvodVstup, Seznam, Strana

from . import sluzby
from .kontrakty import (
    KandidatiFiltr,
    KandidatRadek,
    NoveStatMistoVstup,
    PresunVstup,
    PrijemDynVstup,
    PrijemStatVstup,
    SkladovyVysledek,
    StatMistaFiltr,
    StatMistoRadek,
    UpozorneniFiltr,
    UpozorneniRadek,
    UzavreniUpozorneniVstup,
    VydejVstup,
    ZmenaStatMistaVstup,
)

api = Blueprint("sklad_api", __name__)

# --- příjem, výdej, přesun ------------------------------------------------------------------------


@api.get("/kandidati-dyn")
@vyzaduje("SKLAD_PRIJEM")
@dokumentuj(parametry=KandidatiFiltr, vystup=Seznam[KandidatRadek],
            popis="Volné DYN pozice pro díl: zvolený regál, pak ostatní regály pracoviště; podle čísla boxu.")
def kandidati_dyn():
    vysledek = sluzby.kandidati_dyn(nacti_parametry(KandidatiFiltr))
    return odpoved(vysledek, f"Volných pozic: {len(vysledek.polozky)}." if vysledek.polozky else "Žádná volná pozice.")


@api.post("/prijem-dyn")
@vyzaduje("SKLAD_PRIJEM")
@dokumentuj(vstup=PrijemDynVstup, vystup=SkladovyVysledek, popis="Příjem dávky do prázdné DYN pozice (21.1.4).")
def prijem_dyn():
    vysledek = sluzby.prijem_dyn(vstup=nacti_vstup(PrijemDynVstup), kdo=kontext())
    return odpoved(vysledek, f"Přijato {vysledek.pocet_ks} ks na {vysledek.cil.kod}.")


@api.post("/prijem-stat")
@vyzaduje("SKLAD_PRIJEM")
@dokumentuj(vstup=PrijemStatVstup, vystup=SkladovyVysledek,
            popis="Uskladnění do STAT místa dílu – z výroby nebo z DYN pozice; nad maximem varování (Q-11).")
def prijem_stat():
    vysledek = sluzby.prijem_stat(vstup=nacti_vstup(PrijemStatVstup), kdo=kontext())
    return odpoved(vysledek, f"Uskladněno {vysledek.pocet_ks} ks na {vysledek.cil.kod}.")


@api.post("/vydej")
@vyzaduje("SKLAD_VYDEJ")
@dokumentuj(vstup=VydejVstup, vystup=SkladovyVysledek, popis="Výdej z pozice; nikdy do záporného stavu (21.1.5).")
def vydej():
    vysledek = sluzby.vydej(vstup=nacti_vstup(VydejVstup), kdo=kontext())
    return odpoved(vysledek, f"Vydáno {vysledek.pocet_ks} ks z {vysledek.zdroj.kod}.")


@api.post("/presun")
@vyzaduje("SKLAD_PRESUN")
@dokumentuj(vstup=PresunVstup, vystup=SkladovyVysledek,
            popis="Přesun celé dávky DYN → DYN v rámci pracoviště; množství se neposílá (21.1.6).")
def presun():
    vysledek = sluzby.presun(vstup=nacti_vstup(PresunVstup), kdo=kontext())
    return odpoved(vysledek, f"Přesunuto {vysledek.pocet_ks} ks z {vysledek.zdroj.kod} na {vysledek.cil.kod}.")


# --- STAT místa (STAT_EDIT) -------------------------------------------------------------------------


@api.get("/stat-mista")
@vyzaduje("STAT_EDIT")
@dokumentuj(parametry=StatMistaFiltr, vystup=Strana[StatMistoRadek], popis="Statická umístění dílů s min/max a stavem.")
def stat_mista():
    return odpoved(sluzby.seznam_stat_mist(nacti_parametry(StatMistaFiltr)), "Načteno.")


@api.post("/stat-mista")
@vyzaduje("STAT_EDIT")
@dokumentuj(vstup=NoveStatMistoVstup, vystup=StatMistoRadek,
            popis="Přiřadí díl STAT pozici (nejvýše 1 místo na díl, Q-12; velikost Q-05).")
def zaloz_stat_misto():
    radek = sluzby.zaloz_stat_misto(vstup=nacti_vstup(NoveStatMistoVstup), kdo=kontext())
    return odpoved(radek, f"Díl {radek.identifikacni_cislo} přiřazen na {radek.kod}.")


@api.patch("/stat-mista/<int:stat_umisteni_id>")
@vyzaduje("STAT_EDIT")
@dokumentuj(vstup=ZmenaStatMistaVstup, vystup=StatMistoRadek,
            popis="Změní min/opt/max; upozornění se přehodnotí (výsledek ve varování).")
def zmen_stat_misto(stat_umisteni_id: int):
    return odpoved(sluzby.zmen_stat_misto(stat_umisteni_id=stat_umisteni_id,
                                          vstup=nacti_vstup(ZmenaStatMistaVstup), kdo=kontext()), "Uloženo.")


@api.post("/stat-mista/<int:stat_umisteni_id>/ukoncit")
@vyzaduje("STAT_EDIT")
@dokumentuj(vstup=DuvodVstup, vystup=StatMistoRadek, popis="Ukončí přiřazení prázdné STAT pozice.")
def ukonci_stat_misto(stat_umisteni_id: int):
    radek = sluzby.ukonci_stat_misto(stat_umisteni_id=stat_umisteni_id, vstup=nacti_vstup(DuvodVstup), kdo=kontext())
    return odpoved(radek, f"Přiřazení {radek.kod} ukončeno.")


# --- upozornění ------------------------------------------------------------------------------------


@api.get("/upozorneni")
@vyzaduje("DIL_CIST")
@dokumentuj(parametry=UpozorneniFiltr, vystup=Strana[UpozorneniRadek], popis="Upozornění zásoby (výchozí: otevřená).")
def upozorneni():
    return odpoved(sluzby.seznam_upozorneni(nacti_parametry(UpozorneniFiltr)), "Načteno.")


@api.post("/upozorneni/<int:upozorneni_id>/uzavrit")
@vyzaduje("UPOZORNENI_UZAVRIT")
@dokumentuj(vstup=UzavreniUpozorneniVstup, vystup=UpozorneniRadek, popis="Ruční uzavření upozornění s poznámkou.")
def uzavri_upozorneni(upozorneni_id: int):
    return odpoved(sluzby.uzavri_upozorneni(upozorneni_id=upozorneni_id, vstup=nacti_vstup(UzavreniUpozorneniVstup),
                                            kdo=kontext()), "Upozornění uzavřeno.")
