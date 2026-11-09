"""Služby ostrova E – Sklad: pohyby a zásoby. Jedna operace = @transakce, čtení = @cteni.

Fáze 1: SQL je v `repozitar.py`. Všechny operace ostrova (skladové příkazy, STAT místa, upozornění
zásoby i korekce) zapisují nad SQL Serverem; čtecí funkce rozhraní (`obsah_mist`, `posledni_pohyby`,
`stat_mista`, `nacti_ciselniky`) mají i vzorová data pro běh bez databáze.

Postup každého skladového příkazu ve fázi 1 (jedna transakce, sekce 5.2 a 5.3):
  1. struktura.najdi_vnitrni_pozici pro zdroj i cíl (kód ze štítku, dlouhý tvar se ověří),
  2. struktura.zamkni_mista(spoj, [všechna dotčená místa]) – ještě před čtením obsahu,
  3. obsah, STAT místo a díl (dily.nacti_dily) → kontroly domena.over_* (cíl se ověřuje znovu uvnitř transakce),
  4. zápis ObsahPozice (0 ks = smazání řádku) + SkladovyPohyb se společným TransakceID,
  5. upozornění zásoby podle domena.vyhodnot_upozorneni (UPDLOCK na otevřené upozornění místa).
"""
from __future__ import annotations

from typing import Any

from app.ostrovy.dily import rozhrani as dily
from app.ostrovy.struktura import rozhrani as struktura
from app.platforma.audit import zapis
from app.platforma.chyby import AppError, chyba_vstupu
from app.platforma.db import Spojeni, cteni
from app.platforma.kontrakty import DuvodVstup, Seznam, Strana, Varovani
from app.platforma.transakce import transakce
from app.platforma.typy import Kontext

from . import domena, repozitar, rozhrani
from .kontrakty import (
    VAROVANI_UPOZORNENI,
    KandidatiFiltr,
    KandidatRadek,
    NoveStatMistoVstup,
    PohybRadek,
    PresunVstup,
    PrijemDynVstup,
    PrijemStatVstup,
    SkladovyVysledek,
    StatMistaFiltr,
    StatMistoRadek,
    StavMista,
    UpozorneniFiltr,
    UpozorneniRadek,
    UzavreniUpozorneniVstup,
    VydejVstup,
    ZmenaStatMistaVstup,
)
from .rozhrani import StatMistoInfo

VYSLEDEK_UPOZORNENI = {"ZALOZIT": "ZALOZENO", "AKTUALIZOVAT": "AKTUALIZOVANO", "UZAVRIT": "UZAVRENO", "NIC": None}

# --- čtení ------------------------------------------------------------------------------------


@cteni
def kandidati_dyn(spoj: Spojeni, filtr: KandidatiFiltr) -> Seznam[KandidatRadek]:
    """Volné DYN pozice pro díl na zvoleném regálu (21.1.3), volitelně i z ostatních regálů pracoviště.

    Chyby: VALIDATION_ERROR (regál chybí nebo je zadán dvakrát), NOT_FOUND, PART_HAS_NO_SIZE.
    """
    dil = _nacti_dil(spoj, filtr.dil_id)
    regal_id = _regal(spoj, filtr)
    if dil.potreba is None:
        raise AppError("PART_HAS_NO_SIZE")
    mista = struktura.kandidatni_mista_dyn(spoj, regal_id, dil.potreba.velikost,
                                           cele_pracoviste=filtr.vcetne_ostatnich_regalu)
    obsazene = rozhrani.obsah_mist(spoj, [m.vnitrni_pozice_id for m in mista])
    return Seznam[KandidatRadek](polozky=[
        KandidatRadek(vnitrni_pozice_id=m.vnitrni_pozice_id, kod=m.kod, adresa=m.adresa, box_id=m.box_id,
                      kod_boxu=m.kod_boxu, kod_pozice=m.kod_pozice, velikost=m.velikost, uroven_id=m.uroven_id,
                      regal_id=m.regal_id, jiny_regal=m.regal_id != regal_id)
        for m in domena.vyber_kandidaty(mista, dil.potreba, obsazene, regal_id)])


@cteni
def seznam_stat_mist(spoj: Spojeni, filtr: StatMistaFiltr) -> Strana[StatMistoRadek]:
    if filtr.aktivni is False:   # KOSTRA: vzorová data mají jen aktivní přiřazení
        return Strana[StatMistoRadek](polozky=[], strana=filtr.strana, velikost=filtr.velikost, celkem=0)
    stat = rozhrani.stat_mista(spoj, vnitrni_pozice_ids=[filtr.vnitrni_pozice_id] if filtr.vnitrni_pozice_id else None,
                               dil_ids=[filtr.dil_id] if filtr.dil_id else None)
    radky = [r for r in _stat_radky(spoj, stat) if filtr.stav_zasoby in (None, r.stav_zasoby)]
    return Strana[StatMistoRadek](polozky=radky, strana=filtr.strana, velikost=filtr.velikost, celkem=len(radky))


@cteni
def seznam_upozorneni(spoj: Spojeni, filtr: UpozorneniFiltr) -> Strana[UpozorneniRadek]:
    """Upozornění zásoby, nejnovější první. Výchozí filtr = jen otevřená."""
    radky, celkem = repozitar.seznam_upozorneni(spoj, filtr)
    return Strana[UpozorneniRadek](polozky=_upozorneni_radky(spoj, radky), strana=filtr.strana,
                                   velikost=filtr.velikost, celkem=celkem)


# --- skladové příkazy (requestId) -------------------------------------------------------------------


@transakce("PRIJEM_DYN", skladova=True)
def prijem_dyn(spoj: Spojeni, vstup: PrijemDynVstup, kdo: Kontext) -> SkladovyVysledek:
    """Příjem dávky do prázdné DYN pozice (12.1, 12.4, 21.1.4).

    Chyby: NOT_FOUND, INVALID_BARCODE, WRONG_SCAN_LEVEL, PART_HAS_NO_SIZE, POSITION_BLOCKED,
    POSITION_OCCUPIED, SIZE_MISMATCH, NO_PERMISSION (ruční potvrzení).
    """
    domena.over_zpusob_potvrzeni(vstup.zpusob_potvrzeni, kdo)
    dil = _nacti_dil(spoj, vstup.dil_id)
    cil = struktura.najdi_vnitrni_pozici(spoj, vstup.cil_kod)
    struktura.zamkni_mista(spoj, [cil.vnitrni_pozice_id])
    obsah = rozhrani.obsah_mist(spoj, [cil.vnitrni_pozice_id])
    domena.over_cil_prijmu_dyn(cil, dil.potreba, obsah.get(cil.vnitrni_pozice_id))
    repozitar.nastav_obsah(spoj, cil.vnitrni_pozice_id, dil.dil_id, vstup.pocet_ks)
    return SkladovyVysledek(
        dil_id=dil.dil_id, identifikacni_cislo=dil.identifikacni_cislo, pocet_ks=vstup.pocet_ks,
        pohyby=[_pohyb(spoj, kdo, vstup.poznamka, "PRIJEM", cil, dil.dil_id, 0, vstup.pocet_ks,
                       vstup.zpusob_potvrzeni)],
        zdroj=None, cil=_stav_mista(spoj, cil), stav_zasoby=None, upozorneni=None)


@transakce("PRIJEM_STAT", skladova=True)
def prijem_stat(spoj: Spojeni, vstup: PrijemStatVstup, kdo: Kontext) -> SkladovyVysledek:
    """Uskladnění do STAT místa dílu (12.5, Q-08): z výroby = PRIJEM, z DYN pozice = PRESUN-OUT + PRESUN-IN.

    Stejný díl se přičte, jiný se odmítne, blokovaný cíl se nenahradí jiným (Q-14); nad maximem
    jen varování (Q-11). Chyby: WRONG_PART, POSITION_BLOCKED, INSUFFICIENT_STOCK, VALIDATION_ERROR …
    """
    domena.over_zpusob_potvrzeni(vstup.zpusob_potvrzeni, kdo)
    dil = _nacti_dil(spoj, vstup.dil_id)
    cil = struktura.najdi_vnitrni_pozici(spoj, vstup.cil_kod)
    zdroj = struktura.najdi_vnitrni_pozici(spoj, vstup.zdroj_kod) if vstup.zdroj_kod else None
    ids = [cil.vnitrni_pozice_id] + ([zdroj.vnitrni_pozice_id] if zdroj else [])
    struktura.zamkni_mista(spoj, ids)
    obsah = rozhrani.obsah_mist(spoj, ids)
    stat = _stat_misto_pozice(spoj, cil.vnitrni_pozice_id)
    domena.over_cil_uskladneni_stat(cil, stat, dil.dil_id, obsah.get(cil.vnitrni_pozice_id))
    pohyby = []
    if zdroj is not None:
        if zdroj.typ_boxu != "DYN" or zdroj.vnitrni_pozice_id == cil.vnitrni_pozice_id:
            raise chyba_vstupu("Zdrojem uskladnění do STAT je dynamická pozice.", {"zdrojKod": "Zdroj musí být DYN."})
        zdroj_obsah = domena.over_zdroj(zdroj, obsah.get(zdroj.vnitrni_pozice_id), vstup.pocet_ks, dil_id=dil.dil_id)
        zbyva = zdroj_obsah.pocet_ks - vstup.pocet_ks
        repozitar.nastav_obsah(spoj, zdroj.vnitrni_pozice_id, dil.dil_id, zbyva)
        pohyby.append(_pohyb(spoj, kdo, vstup.poznamka, "PRESUN-OUT", zdroj, dil.dil_id, zdroj_obsah.pocet_ks, zbyva))
    pred = obsah[cil.vnitrni_pozice_id].pocet_ks if cil.vnitrni_pozice_id in obsah else 0
    repozitar.nastav_obsah(spoj, cil.vnitrni_pozice_id, dil.dil_id, pred + vstup.pocet_ks)
    # uskladnění z výroby je PRIJEM, ze DYN pozice PRESUN-OUT + PRESUN-IN se stejným TransakceID (Q-08)
    # cílový pohyb nese ověřený způsob potvrzení (D-18), zdrojový PRESUN-OUT má NULL
    pohyby.append(_pohyb(spoj, kdo, vstup.poznamka, "PRESUN-IN" if zdroj else "PRIJEM", cil, dil.dil_id, pred,
                         pred + vstup.pocet_ks, vstup.zpusob_potvrzeni))
    stav_zasoby, upozorneni = _vyhodnot_stat(spoj, kdo, stat, pred + vstup.pocet_ks)
    varovani = domena.varovani_nad_maximem(pred + vstup.pocet_ks, stat.maximalni_ks, cil.kod)
    return SkladovyVysledek(
        dil_id=dil.dil_id, identifikacni_cislo=dil.identifikacni_cislo, pocet_ks=vstup.pocet_ks, pohyby=pohyby,
        zdroj=_stav_mista(spoj, zdroj) if zdroj else None, cil=_stav_mista(spoj, cil),
        stav_zasoby=stav_zasoby, upozorneni=upozorneni, varovani=(varovani,) if varovani else ())


@transakce("VYDEJ", skladova=True)
def vydej(spoj: Spojeni, vstup: VydejVstup, kdo: Kontext) -> SkladovyVysledek:
    """Výdej z DYN nebo STAT pozice (12.2, 12.6, 21.1.5): 0 < množství ≤ stav, nikdy záporný sklad.

    Při 0 ks se obsah smaže – DYN pozice je volná, STAT přiřazení zůstává. Chyby: POSITION_BLOCKED,
    INSUFFICIENT_STOCK, CONCURRENT_CHANGE (jiný stav, než obsluha viděla), WRONG_SCAN_LEVEL …
    """
    zdroj = struktura.najdi_vnitrni_pozici(spoj, vstup.zdroj_kod)
    struktura.zamkni_mista(spoj, [zdroj.vnitrni_pozice_id])
    obsah = domena.over_zdroj(zdroj, rozhrani.obsah_mist(spoj, [zdroj.vnitrni_pozice_id]).get(zdroj.vnitrni_pozice_id),
                              vstup.pocet_ks, ocekavany_stav_ks=vstup.ocekavany_stav_ks)
    dil = _nacti_dil(spoj, obsah.dil_id)
    zbyva = obsah.pocet_ks - vstup.pocet_ks
    repozitar.nastav_obsah(spoj, zdroj.vnitrni_pozice_id, dil.dil_id, zbyva)
    pohyb = _pohyb(spoj, kdo, vstup.poznamka, "VYDEJ", zdroj, dil.dil_id, obsah.pocet_ks, zbyva)
    stav_zasoby, upozorneni = (None, None)
    if zdroj.typ_boxu == "STAT":
        stav_zasoby, upozorneni = _vyhodnot_stat(spoj, kdo, _stat_misto_pozice(spoj, zdroj.vnitrni_pozice_id), zbyva)
    return SkladovyVysledek(
        dil_id=dil.dil_id, identifikacni_cislo=dil.identifikacni_cislo, pocet_ks=vstup.pocet_ks,
        pohyby=[pohyb], zdroj=_stav_mista(spoj, zdroj), cil=None,
        stav_zasoby=stav_zasoby, upozorneni=upozorneni)


@transakce("PRESUN", skladova=True)
def presun(spoj: Spojeni, vstup: PresunVstup, kdo: Kontext) -> SkladovyVysledek:
    """Přesun celé dávky DYN → DYN v rámci pracoviště (12.3, 21.1.6, Q-07): PRESUN-OUT + PRESUN-IN.

    Chyby: WHOLE_BATCH_ONLY (poslané množství), VALIDATION_ERROR, POSITION_BLOCKED, INSUFFICIENT_STOCK,
    POSITION_OCCUPIED, SIZE_MISMATCH, PART_HAS_NO_SIZE.
    """
    domena.over_zpusob_potvrzeni(vstup.zpusob_potvrzeni, kdo)
    zdroj = struktura.najdi_vnitrni_pozici(spoj, vstup.zdroj_kod)
    cil = struktura.najdi_vnitrni_pozici(spoj, vstup.cil_kod)
    struktura.zamkni_mista(spoj, [zdroj.vnitrni_pozice_id, cil.vnitrni_pozice_id])
    obsah = rozhrani.obsah_mist(spoj, [zdroj.vnitrni_pozice_id, cil.vnitrni_pozice_id])
    zdroj_obsah = obsah.get(zdroj.vnitrni_pozice_id)
    dil = _nacti_dil(spoj, zdroj_obsah.dil_id) if zdroj_obsah else None
    davka = domena.over_presun(zdroj, cil, zdroj_obsah, obsah.get(cil.vnitrni_pozice_id), dil.potreba if dil else None)
    repozitar.nastav_obsah(spoj, zdroj.vnitrni_pozice_id, davka.dil_id, 0)
    repozitar.nastav_obsah(spoj, cil.vnitrni_pozice_id, davka.dil_id, davka.pocet_ks)
    return SkladovyVysledek(
        dil_id=davka.dil_id, identifikacni_cislo=dil.identifikacni_cislo, pocet_ks=davka.pocet_ks,
        pohyby=[_pohyb(spoj, kdo, vstup.poznamka, "PRESUN-OUT", zdroj, davka.dil_id, davka.pocet_ks, 0),
                _pohyb(spoj, kdo, vstup.poznamka, "PRESUN-IN", cil, davka.dil_id, 0, davka.pocet_ks,
                       vstup.zpusob_potvrzeni)],
        zdroj=_stav_mista(spoj, zdroj), cil=_stav_mista(spoj, cil), stav_zasoby=None, upozorneni=None)


# --- STAT místa (STAT_EDIT) -------------------------------------------------------------------------


@transakce("STAT_MISTO_ZALOZENI")
def zaloz_stat_misto(spoj: Spojeni, vstup: NoveStatMistoVstup, kdo: Kontext) -> StatMistoRadek:
    """Přiřadí díl STAT pozici s min/opt/max (kap. 13) – stejný základ jako rozhrani.prirad_stat_misto.

    Služba navíc umí vědomé přepsání velikosti (`prepsatVelikost` + důvod, jen TECH/ADMIN, Q-05).
    Chyby: NOT_FOUND, VALIDATION_ERROR, SIZE_MISMATCH, NO_PERMISSION (přepsání velikosti),
    ALREADY_EXISTS (díl už STAT místo má – Q-12, nebo pozice už je přiřazená).
    """
    stat_id = rozhrani._prirad_stat_misto(
        spoj, kdo, vstup.dil_id, vstup.vnitrni_pozice_id, vstup.minimalni_ks, vstup.optimalni_ks, vstup.maximalni_ks,
        prepsat_velikost=vstup.prepsat_velikost, duvod=vstup.duvod)
    novy = StatMistoInfo(stat_id, vstup.dil_id, vstup.vnitrni_pozice_id, vstup.minimalni_ks, vstup.optimalni_ks,
                         vstup.maximalni_ks)
    return _stat_radky(spoj, [novy])[0]


@transakce("STAT_MISTO_ZMENA")
def zmen_stat_misto(spoj: Spojeni, stat_umisteni_id: int, vstup: ZmenaStatMistaVstup, kdo: Kontext) -> StatMistoRadek:
    """Nové min/opt/max; měněná pole jdou do auditu a upozornění se přehodnotí stejnými pravidly
    (5.8) – výsledek je ve varování. Chyby: NOT_FOUND, VALIDATION_ERROR."""
    stat = _nacti_stat_misto(spoj, stat_umisteni_id)
    struktura.zamkni_mista(spoj, [stat.vnitrni_pozice_id])
    zmena = vstup.zmenena_pole()
    novy = StatMistoInfo(stat.stat_umisteni_id, stat.dil_id, stat.vnitrni_pozice_id,
                         zmena.get("minimalni_ks", stat.minimalni_ks), zmena.get("optimalni_ks", stat.optimalni_ks),
                         zmena.get("maximalni_ks", stat.maximalni_ks))
    domena.over_min_opt_max(novy.minimalni_ks, novy.optimalni_ks, novy.maximalni_ks)
    for pole, sloupec in (("minimalni_ks", "MinimalniPocetKs"), ("optimalni_ks", "OptimalniPocetKs"),
                          ("maximalni_ks", "MaximalniPocetKs")):
        if getattr(novy, pole) != getattr(stat, pole):
            zapis(spoj, kdo, "STAT_UMISTENI", stat_umisteni_id, sloupec, getattr(stat, pole), getattr(novy, pole),
                  vstup.duvod)
    repozitar.zmen_meze(spoj, stat_umisteni_id, novy.minimalni_ks, novy.optimalni_ks, novy.maximalni_ks)
    radek = _stat_radky(spoj, [novy])[0]
    _, upozorneni = _vyhodnot_stat(spoj, kdo, novy, radek.stav_ks)   # přehodnotí a zapíše (5.8)
    if upozorneni is None:
        return radek
    zprava = {"ZALOZENO": "založeno upozornění", "AKTUALIZOVANO": "upozornění změněno",
              "UZAVRENO": "upozornění uzavřeno"}[upozorneni]
    return radek.model_copy(update={"varovani": (Varovani(
        VAROVANI_UPOZORNENI, f"Stav {radek.stav_ks} ks při minimu {novy.minimalni_ks} ks: {zprava}."),)})


@transakce("STAT_MISTO_UKONCENI")
def ukonci_stat_misto(spoj: Spojeni, stat_umisteni_id: int, vstup: DuvodVstup, kdo: Kontext) -> StatMistoRadek:
    """Ukončí přiřazení prázdné pozice (Aktivni = 0, historie zůstává); otevřené upozornění se uzavře
    s poznámkou (Q-13), audit se píše s důvodem. Přetisk štítku bez čísla dílu až na pilotu (Q-19).
    Chyby: NOT_FOUND, NOT_EMPTY."""
    stat = _nacti_stat_misto(spoj, stat_umisteni_id)
    struktura.zamkni_mista(spoj, [stat.vnitrni_pozice_id])
    radek = _stat_radky(spoj, [stat])[0]
    if radek.stav_ks > 0:
        raise AppError("NOT_EMPTY", f"Na {radek.kod} je {radek.stav_ks} ks. Přiřazení se ukončí jen u prázdné pozice.")
    repozitar.ukonci_stat_misto(spoj, stat_umisteni_id)
    zapis(spoj, kdo, "STAT_UMISTENI", stat_umisteni_id, "Aktivni", True, False, vstup.duvod)
    otevrene = repozitar.otevrene_upozorneni(spoj, stat_umisteni_id)
    varovani = ()
    if otevrene is not None:
        repozitar.uzavri_upozorneni(spoj, otevrene["UpozorneniID"], kdo, poznamka=vstup.duvod)
        varovani = (Varovani(VAROVANI_UPOZORNENI, "Otevřené upozornění zásoby bylo uzavřeno."),)
    return radek.model_copy(update={"aktivni": False, "varovani": varovani})


# --- upozornění (UPOZORNENI_UZAVRIT) ------------------------------------------------------------------


@transakce("UPOZORNENI_UZAVRENI")
def uzavri_upozorneni(spoj: Spojeni, upozorneni_id: int, vstup: UzavreniUpozorneniVstup,
                      kdo: Kontext) -> UpozorneniRadek:
    """Ruční uzavření s poznámkou (Q-13); zavírá MISTR nebo ADMIN s UPOZORNENI_UZAVRIT.

    Chyby: NOT_FOUND, CONCURRENT_CHANGE (už uzavřené).
    """
    zadano = repozitar.upozorneni(spoj, upozorneni_id)
    if zadano is None:
        raise AppError("NOT_FOUND", f"Upozornění {upozorneni_id} neexistuje.")
    # otevřené upozornění místa čteme s UPDLOCK – podruhé už otevřené není (souběžné uzavření počká)
    otevrene = repozitar.otevrene_upozorneni(spoj, zadano["StatickeUmisteniID"])
    if otevrene is None or otevrene["UpozorneniID"] != upozorneni_id:
        raise AppError("CONCURRENT_CHANGE", "Upozornění už je uzavřené.")
    repozitar.uzavri_upozorneni(spoj, upozorneni_id, kdo, poznamka=vstup.poznamka)
    return _upozorneni_radky(spoj, [repozitar.upozorneni(spoj, upozorneni_id)])[0]


# --- pomocné -------------------------------------------------------------------------------------


def _nacti_dil(spoj: Spojeni, dil_id: int) -> dily.DilInfo:
    dil = dily.nacti_dily(spoj, [dil_id]).get(dil_id)
    if dil is None or not dil.aktivni:
        raise AppError("NOT_FOUND", f"Díl {dil_id} neexistuje nebo není aktivní.")
    return dil


def _regal(spoj: Spojeni, filtr: KandidatiFiltr) -> int:
    if (filtr.regal_id is None) == (filtr.kod_regalu is None):
        raise chyba_vstupu("Zadejte regál – buď regalId, nebo naskenovaný kodRegalu.",
                           {"regalId": "Zadejte právě jedno z regalId a kodRegalu."})
    if filtr.regal_id is not None:
        return filtr.regal_id
    objekt = struktura.najdi_objekt(spoj, filtr.kod_regalu or "")
    if objekt.typ != "REGAL":
        raise chyba_vstupu("Naskenujte štítek regálu (HOUFEK-PLE-R01).", {"kodRegalu": "Kód není regál."})
    return objekt.regal_id


def _stat_misto_pozice(spoj: Spojeni, vnitrni_pozice_id: int) -> StatMistoInfo | None:
    mista = rozhrani.stat_mista(spoj, vnitrni_pozice_ids=[vnitrni_pozice_id])
    return mista[0] if mista else None


def _nacti_stat_misto(spoj: Spojeni, stat_umisteni_id: int) -> StatMistoInfo:
    stat = next((s for s in rozhrani.stat_mista(spoj) if s.stat_umisteni_id == stat_umisteni_id), None)
    if stat is None:
        raise AppError("NOT_FOUND", f"Statické místo {stat_umisteni_id} neexistuje nebo není aktivní.")
    return stat


def _stat_radky(spoj: Spojeni, stat: list[StatMistoInfo]) -> list[StatMistoRadek]:
    mista = struktura.nacti_mista(spoj, [s.vnitrni_pozice_id for s in stat])
    dil_info = dily.nacti_dily(spoj, [s.dil_id for s in stat])
    obsah = rozhrani.obsah_mist(spoj, [s.vnitrni_pozice_id for s in stat])
    radky = []
    for s in stat:
        stav_ks = obsah[s.vnitrni_pozice_id].pocet_ks if s.vnitrni_pozice_id in obsah else 0
        radky.append(StatMistoRadek(
            stat_umisteni_id=s.stat_umisteni_id, dil_id=s.dil_id,
            identifikacni_cislo=dil_info[s.dil_id].identifikacni_cislo,
            vnitrni_pozice_id=s.vnitrni_pozice_id, kod=mista[s.vnitrni_pozice_id].kod,
            velikost=mista[s.vnitrni_pozice_id].velikost, minimalni_ks=s.minimalni_ks, optimalni_ks=s.optimalni_ks,
            maximalni_ks=s.maximalni_ks, stav_ks=stav_ks, stav_zasoby=domena.stav_zasoby(stav_ks, s.minimalni_ks),
            aktivni=True))
    return radky


def _upozorneni_radky(spoj: Spojeni, radky: list[dict[str, Any]]) -> list[UpozorneniRadek]:
    """Číslo dílu a kód pozice patří ostrovům D a C – doplňují se přes jejich rozhraní."""
    mista = struktura.nacti_mista(spoj, [r["VnitrniPoziceID"] for r in radky])
    dil_info = dily.nacti_dily(spoj, [r["DilID"] for r in radky])
    return [UpozorneniRadek(
        upozorneni_id=r["UpozorneniID"], stat_umisteni_id=r["StatickeUmisteniID"], dil_id=r["DilID"],
        identifikacni_cislo=dil_info[r["DilID"]].identifikacni_cislo, kod=mista[r["VnitrniPoziceID"]].kod,
        typ_stavu=r["TypStavu"], stav_upozorneni=r["StavUpozorneni"], aktualni_pocet_ks=r["AktualniPocetKs"],
        minimalni_pocet_ks=r["MinimalniPocetKs"], datum_vzniku=r["DatumVzniku"], datum_uzavreni=r["DatumUzavreni"],
        poznamka=r["Poznamka"]) for r in radky]


def _vyhodnot_stat(spoj: Spojeni, kdo: Kontext, stat: StatMistoInfo | None,
                   stav_po_ks: int) -> tuple[str | None, str | None]:
    """Zásobový stav STAT místa po operaci a co se stalo s jeho upozorněním (5.8), včetně zápisu."""
    if stat is None:
        return None, None
    return (domena.stav_zasoby(stav_po_ks, stat.minimalni_ks),
            VYSLEDEK_UPOZORNENI[rozhrani._prehodnot_upozorneni(spoj, kdo, stat, stav_po_ks)])


def _pohyb(spoj: Spojeni, kdo: Kontext, poznamka: str | None, typ: str, misto: struktura.MistoInfo, dil_id: int,
           pred: int, po: int, zpusob_potvrzeni: str | None = None) -> PohybRadek:
    """Zapíše pohyb (podepsaná změna, `TransakceID` ze spojení) a vrátí řádek s novým PohybID.

    `zpusob_potvrzeni` (SKEN/RUCNE) se posílá jen u pohybu do cíle, ostatní mají NULL (D-18).
    """
    mnozstvi = po - pred
    pohyb_id = repozitar.pridej_pohyb(
        spoj, typ_pohybu=typ, dil_id=dil_id, vnitrni_pozice_id=misto.vnitrni_pozice_id, mnozstvi=mnozstvi,
        stav_pred=pred, stav_po=po, kdo=kdo, poznamka=poznamka, zpusob_potvrzeni=zpusob_potvrzeni)
    return PohybRadek(pohyb_id=pohyb_id, typ_pohybu=typ, vnitrni_pozice_id=misto.vnitrni_pozice_id, kod=misto.kod,
                      mnozstvi=mnozstvi, stav_pred_ks=pred, stav_po_ks=po)


def _stav_mista(spoj: Spojeni, misto: struktura.MistoInfo) -> StavMista:
    """Pozice a stav jejího boxu po operaci (12.2: po vyprázdnění je box volný, pokud není blokovaný).

    Volá se až po zápisu, takže obsah i počet obsazených pozic čte už nový.
    """
    obsah_boxu = rozhrani.obsah_mist(spoj, struktura.pozice_v_rozsahu(spoj, "BOX", misto.box_id))
    obsah = obsah_boxu.get(misto.vnitrni_pozice_id)
    return StavMista(vnitrni_pozice_id=misto.vnitrni_pozice_id, kod=misto.kod, adresa=misto.adresa,
                     typ_boxu=misto.typ_boxu, dil_id=obsah.dil_id if obsah else None,
                     stav_ks=obsah.pocet_ks if obsah else 0,
                     stav_boxu=struktura.stav_boxu(misto.box_blokovany, len(obsah_boxu)))
