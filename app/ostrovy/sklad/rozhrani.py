"""VEŘEJNÉ ROZHRANÍ ostrova E – Sklad: pohyby a zásoby (sekce 7.5).

KOLIK: jediný ostrov, který mění počty kusů. Jiný ostrov mění stav jen přes `zauctuj_korekci`.
`stav_zasoby` je hotová (pravidlo 5.8); funkce nad DB jsou ve fázi 0 kostra.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.platforma.db import Spojeni
from app.platforma.typy import Kontext, PolozkaCiselniku

from . import domena

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


# --- čtení (fáze 0: kostra se vzorovými daty) ------------------------------------------------

def obsah_mist(spoj: Spojeni, vnitrni_pozice_ids: list[int]) -> dict[int, ObsahInfo]:
    """Aktuální obsah pozic; prázdná pozice ve výsledku chybí."""
    from . import ukazky  # KOSTRA (fáze 0)

    return {i: ukazky.OBSAH[i] for i in vnitrni_pozice_ids if i in ukazky.OBSAH}


def posledni_pohyby(spoj: Spojeni, vnitrni_pozice_ids: list[int]) -> dict[int, int | None]:
    """PohybID posledního pohybu na každé pozici (None = nikdy). Pro PREPOCITAT v inventuře (Q-16)."""
    from . import ukazky  # KOSTRA (fáze 0)

    return {i: ukazky.POSLEDNI_POHYBY.get(i) for i in vnitrni_pozice_ids}


def nacti_ciselniky(spoj: Spojeni) -> dict[str, tuple[PolozkaCiselniku, ...]]:
    """Číselníky skladu pro filtry: "typyPohybu" (PRIJEM, VYDEJ, PRESUN-OUT …)."""
    from . import ukazky  # KOSTRA (fáze 0)

    return {"typyPohybu": tuple(PolozkaCiselniku(i, kod, nazev, True) for i, kod, nazev in ukazky.TYPY_POHYBU)}


def stat_mista(spoj: Spojeni, *, vnitrni_pozice_ids: list[int] | None = None,
               dil_ids: list[int] | None = None) -> list[StatMistoInfo]:
    """Aktivní statická umístění podle pozic nebo dílů (nejvýše 1 na díl, Q-12). Bez filtru = všechna."""
    from . import ukazky  # KOSTRA (fáze 0)

    return [s for s in ukazky.STAT_MISTA
            if (vnitrni_pozice_ids is None or s.vnitrni_pozice_id in vnitrni_pozice_ids)
            and (dil_ids is None or s.dil_id in dil_ids)]


# --- zápis (v transakci volajícího; volající už drží zámek pozice) ----------------------------

def zauctuj_korekci(spoj: Spojeni, kdo: Kontext, vnitrni_pozice_id: int, dil_id: int, novy_stav_ks: int,
                    typ_pohybu: str, poznamka: str | None = None) -> PohybInfo:
    """Nastaví stav dílu na pozici na `novy_stav_ks` a zapíše rozdíl jako pohyb.

    typ_pohybu: INVENTURA | KOREKCE | POCAT-STAV. Upraví ObsahPozice (0 ks = smazání řádku)
    a přehodnotí upozornění zásoby. Volající musí předem zavolat struktura.zamkni_mista().
    Chyby: VALIDATION_ERROR (záporný stav, neznámý typ), WRONG_PART (STAT pozice jiného dílu),
    POSITION_OCCUPIED (na pozici je jiný díl).
    """
    raise NotImplementedError("Ostrov E – fáze 1")


def prirad_stat_misto(spoj: Spojeni, kdo: Kontext, dil_id: int, vnitrni_pozice_id: int, minimalni_ks: int,
                      optimalni_ks: int | None, maximalni_ks: int | None, duvod: str | None = None) -> int:
    """Přiřadí díl STAT pozici s min/max (migrace i administrace). Vrací StatickeUmisteniID.

    Kontroluje velikost (Q-05), volnost pozice a 1 místo na díl (Q-12); zapíše audit.
    Chyby: ALREADY_EXISTS, SIZE_MISMATCH, NOT_FOUND, VALIDATION_ERROR.
    """
    raise NotImplementedError("Ostrov E – fáze 1")
