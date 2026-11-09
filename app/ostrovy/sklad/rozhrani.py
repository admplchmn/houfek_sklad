"""VEŘEJNÉ ROZHRANÍ ostrova E – Sklad: pohyby a zásoby (sekce 7.5).

KOLIK: jediný ostrov, který mění počty kusů. Jiný ostrov mění stav jen přes `zauctuj_korekci`.
`stav_zasoby` je hotová (pravidlo 5.8); čtení volá repozitar.py, jakmile je spojení nad SQL Serverem.
Bez spojení nebo mimo mssql zůstávají vzorová data z ukazky.py, aby testy kostry i ostrovů
běžely bez databáze (stejný způsob jako ostrovy B, C a D).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.ostrovy.dily import rozhrani as dily
from app.ostrovy.struktura import rozhrani as struktura
from app.platforma.audit import zapis
from app.platforma.chyby import AppError, chyba_vstupu
from app.platforma.db import Spojeni
from app.platforma.typy import Kontext, PolozkaCiselniku

from . import domena, repozitar

TYPY_KOREKCE = ("INVENTURA", "KOREKCE", "POCAT-STAV")


@dataclass(frozen=True)
class ObsahInfo:
    vnitrni_pozice_id: int
    dil_id: int
    pocet_ks: int


@dataclass(frozen=True)
class StatMistoInfo:
    stat_umisteni_id: int
    dil_id: int
    vnitrni_pozice_id: int
    minimalni_ks: int
    optimalni_ks: int | None
    maximalni_ks: int | None


@dataclass(frozen=True)
class PohybInfo:
    pohyb_id: int
    transakce_id: uuid.UUID | None
    typ_pohybu: str              # PRIJEM | VYDEJ | PRESUN-OUT | PRESUN-IN | INVENTURA | KOREKCE | POCAT-STAV
    dil_id: int
    vnitrni_pozice_id: int
    mnozstvi: int                # podepsaná změna (+ příjem, − výdej)
    stav_pred_ks: int
    stav_po_ks: int


# --- čisté funkce (hotové) -------------------------------------------------------------------

def stav_zasoby(stav_ks: int, minimum_ks: int) -> str:
    """Zásobový stav STAT místa v pořadí z analýzy 5.8 (řeší i minimum 0, N-08).

    VYCERPANO | POD_MINIMEM | NA_MINIMU | OK. Stejnou logiku má pohled v_ZasobaDilu;
    shodu hlídá test ostrova E. Pravidlo je v domena.stav_zasoby.
    """
    return domena.stav_zasoby(stav_ks, minimum_ks)


# --- čtení (nad SQL Serverem repozitář, jinak vzorová data) ---------------------------------------

def obsah_mist(spoj: Spojeni, vnitrni_pozice_ids: list[int]) -> dict[int, ObsahInfo]:
    """Aktuální obsah pozic; prázdná pozice ve výsledku chybí."""
    if spoj is not None and spoj.dialekt == "mssql":
        return repozitar.obsah_mist(spoj, vnitrni_pozice_ids)
    from . import ukazky  # KOSTRA (fáze 0)

    return {i: ukazky.OBSAH[i] for i in vnitrni_pozice_ids if i in ukazky.OBSAH}


def posledni_pohyby(spoj: Spojeni, vnitrni_pozice_ids: list[int]) -> dict[int, int | None]:
    """PohybID posledního pohybu na každé pozici (None = nikdy). Pro PREPOCITAT v inventuře (Q-16)."""
    if spoj is not None and spoj.dialekt == "mssql":
        return repozitar.posledni_pohyby(spoj, vnitrni_pozice_ids)
    from . import ukazky  # KOSTRA (fáze 0)

    return {i: ukazky.POSLEDNI_POHYBY.get(i) for i in vnitrni_pozice_ids}


def nacti_ciselniky(spoj: Spojeni) -> dict[str, tuple[PolozkaCiselniku, ...]]:
    """Číselníky skladu pro filtry: "typyPohybu" (PRIJEM, VYDEJ, PRESUN-OUT …)."""
    if spoj is not None and spoj.dialekt == "mssql":
        return repozitar.nacti_ciselniky(spoj)
    from . import ukazky  # KOSTRA (fáze 0)

    return {"typyPohybu": tuple(PolozkaCiselniku(i, kod, nazev, True) for i, kod, nazev in ukazky.TYPY_POHYBU)}


def stat_mista(spoj: Spojeni, *, vnitrni_pozice_ids: list[int] | None = None,
               dil_ids: list[int] | None = None) -> list[StatMistoInfo]:
    """Aktivní statická umístění podle pozic nebo dílů (nejvýše 1 na díl, Q-12). Bez filtru = všechna."""
    if spoj is not None and spoj.dialekt == "mssql":
        return repozitar.stat_mista(spoj, vnitrni_pozice_ids=vnitrni_pozice_ids, dil_ids=dil_ids)
    from . import ukazky  # KOSTRA (fáze 0)

    return [s for s in ukazky.STAT_MISTA
            if (vnitrni_pozice_ids is None or s.vnitrni_pozice_id in vnitrni_pozice_ids)
            and (dil_ids is None or s.dil_id in dil_ids)]


# --- zápis (v transakci volajícího; volající už drží zámek pozice) ----------------------------

def _prehodnot_upozorneni(spoj: Spojeni, kdo: Kontext, stat: StatMistoInfo, stav_po_ks: int) -> str:
    """Přehodnotí upozornění zásoby STAT místa po změně stavu (5.8), zapíše ho a vrátí název akce.

    Otevřené upozornění se čte s UPDLOCK – dvě operace nad týmž místem tak nevytvoří dvě.
    """
    otevrene = repozitar.otevrene_upozorneni(spoj, stat.stat_umisteni_id)
    akce = domena.vyhodnot_upozorneni(stav_po_ks, stat.minimalni_ks, otevrene["TypStavu"] if otevrene else None)
    if akce.akce == "ZALOZIT":
        repozitar.zaloz_upozorneni(spoj, stat.stat_umisteni_id, stav_po_ks, stat.minimalni_ks, akce.typ_stavu)
    elif akce.akce == "AKTUALIZOVAT":
        repozitar.obnov_upozorneni(spoj, otevrene["UpozorneniID"], stav_po_ks, stat.minimalni_ks, akce.typ_stavu)
    elif akce.akce == "UZAVRIT":
        repozitar.uzavri_upozorneni(spoj, otevrene["UpozorneniID"], kdo)
    return akce.akce


def zauctuj_korekci(spoj: Spojeni, kdo: Kontext, vnitrni_pozice_id: int, dil_id: int, novy_stav_ks: int,
                    typ_pohybu: str, poznamka: str | None = None) -> PohybInfo:
    """Nastaví stav dílu na pozici na `novy_stav_ks` a zapíše rozdíl jako pohyb.

    typ_pohybu: INVENTURA | KOREKCE | POCAT-STAV. Upraví ObsahPozice (0 ks = smazání řádku)
    a přehodnotí upozornění zásoby. Volající musí předem zavolat struktura.zamkni_mista().
    Chyby: VALIDATION_ERROR (záporný stav, neznámý typ), WRONG_PART (STAT pozice jiného dílu),
    POSITION_OCCUPIED (na pozici je jiný díl).
    """
    if typ_pohybu not in TYPY_KOREKCE:
        raise chyba_vstupu(f"Typ korekce {typ_pohybu} neznámý.",
                           {"typPohybu": f"Pošlete jeden z: {', '.join(TYPY_KOREKCE)}."})
    if novy_stav_ks < 0:
        raise chyba_vstupu("Stav na pozici nesmí být záporný.", {"novyStavKs": "Nejnižší možný stav je 0 ks."})
    misto = struktura.nacti_mista(spoj, [vnitrni_pozice_id]).get(vnitrni_pozice_id)
    if misto is None:
        raise AppError("NOT_FOUND", f"Pozice {vnitrni_pozice_id} neexistuje nebo není aktivní.")
    mista = stat_mista(spoj, vnitrni_pozice_ids=[vnitrni_pozice_id])
    stat = mista[0] if mista else None
    if misto.typ_boxu == "STAT" and (stat is None or stat.dil_id != dil_id):
        raise AppError("WRONG_PART", f"{misto.kod} je statická pozice přiřazená jinému dílu.")
    obsah = obsah_mist(spoj, [vnitrni_pozice_id]).get(vnitrni_pozice_id)
    if obsah is not None and obsah.dil_id != dil_id:
        raise AppError("POSITION_OCCUPIED", f"Na pozici {misto.kod} je {obsah.pocet_ks} ks jiného dílu.")
    pred = obsah.pocet_ks if obsah else 0
    if novy_stav_ks == pred:      # pohyb s nulovým množstvím schéma nedovolí (CK_SkladovyPohyb_Mnozstvi)
        raise chyba_vstupu("Nový stav je stejný jako současný, korekce nemá co zapsat.",
                           {"novyStavKs": f"Na pozici {misto.kod} už je {pred} ks tohoto dílu."})
    repozitar.nastav_obsah(spoj, vnitrni_pozice_id, dil_id, novy_stav_ks)
    pohyb_id = repozitar.pridej_pohyb(spoj, typ_pohybu=typ_pohybu, dil_id=dil_id, vnitrni_pozice_id=vnitrni_pozice_id,
                                      mnozstvi=novy_stav_ks - pred, stav_pred=pred, stav_po=novy_stav_ks, kdo=kdo,
                                      poznamka=poznamka)
    if stat is not None:
        _prehodnot_upozorneni(spoj, kdo, stat, novy_stav_ks)
    return PohybInfo(pohyb_id, spoj.transakce_id, typ_pohybu, dil_id, vnitrni_pozice_id, novy_stav_ks - pred, pred,
                     novy_stav_ks)


def _prirad_stat_misto(spoj: Spojeni, kdo: Kontext, dil_id: int, vnitrni_pozice_id: int, minimalni_ks: int,
                       optimalni_ks: int | None, maximalni_ks: int | None, *, prepsat_velikost: bool,
                       duvod: str | None) -> int:
    """Přiřadí díl STAT pozici a zapíše audit; pozici zamkne jako skladové příkazy. Vrací StatickeUmisteniID.

    Společný základ `prirad_stat_misto` (migrace, velikost se přísně kontroluje) a služby
    `zaloz_stat_misto` (administrace umí vědomé přepsání velikosti `prepsat_velikost` + důvod, Q-05).
    Upozornění zásoby se při založení nezakládá – stav se vyhodnotí až první operací.
    """
    struktura.zamkni_mista(spoj, [vnitrni_pozice_id])
    dil = dily.nacti_dily(spoj, [dil_id]).get(dil_id)
    if dil is None or not dil.aktivni:
        raise AppError("NOT_FOUND", f"Díl {dil_id} neexistuje nebo není aktivní.")
    misto = struktura.nacti_mista(spoj, [vnitrni_pozice_id]).get(vnitrni_pozice_id)
    if misto is None:
        raise AppError("NOT_FOUND", f"Pozice {vnitrni_pozice_id} neexistuje nebo není aktivní.")
    domena.over_min_opt_max(minimalni_ks, optimalni_ks, maximalni_ks)
    domena.over_stat_pozici(misto, dil.potreba, prepsat_velikost=prepsat_velikost, kdo=kdo, duvod=duvod)
    if stat_mista(spoj, dil_ids=[dil_id]):
        raise AppError("ALREADY_EXISTS",
                       f"Díl {dil.identifikacni_cislo} už má aktivní STAT místo (nejvýše jedno, Q-12).")
    if stat_mista(spoj, vnitrni_pozice_ids=[vnitrni_pozice_id]):
        raise AppError("ALREADY_EXISTS", f"Pozice {misto.kod} už je přiřazená jinému dílu.")
    stat_id = repozitar.vloz_stat_misto(spoj, dil_id, vnitrni_pozice_id, minimalni_ks, optimalni_ks, maximalni_ks)
    zapis(spoj, kdo, "STAT_UMISTENI", stat_id, "DilID", None, dil_id, duvod)
    if prepsat_velikost and dil.potreba is not None and dil.potreba.velikost != misto.velikost:
        zapis(spoj, kdo, "STAT_UMISTENI", stat_id, "VelikostPoziceID", misto.velikost, dil.potreba.velikost, duvod)
    return stat_id


def prirad_stat_misto(spoj: Spojeni, kdo: Kontext, dil_id: int, vnitrni_pozice_id: int, minimalni_ks: int,
                      optimalni_ks: int | None, maximalni_ks: int | None, duvod: str | None = None) -> int:
    """Přiřadí díl STAT pozici s min/max (migrace i administrace). Vrací StatickeUmisteniID.

    Kontroluje velikost (Q-05), volnost pozice a 1 místo na díl (Q-12); zapíše audit.
    Chyby: ALREADY_EXISTS, SIZE_MISMATCH, NOT_FOUND, VALIDATION_ERROR.
    """
    return _prirad_stat_misto(spoj, kdo, dil_id, vnitrni_pozice_id, minimalni_ks, optimalni_ks, maximalni_ks,
                              prepsat_velikost=False, duvod=duvod)
