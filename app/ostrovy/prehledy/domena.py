"""Čistá pravidla ostrova G – Přehledy: bez DB a bez Flasku.

Hotová ve fázi 0: barva boxu (zadání 7.2), souhrn monitoringu zásob (13.1), text umístění dílu,
pořadí umístění pro zvýraznění v SVG (16) a doporučení pro laser (kap. 14, Q-22).
Otevřené: zda „doporučeno vyrobit“ odečítá rozpracované DYN (kap. 14, 28) – proto přepínač odecitat_dyn.
"""
from __future__ import annotations

import math
from collections.abc import Iterable

STAVY_ZASOBY = ("OK", "NA_MINIMU", "POD_MINIMEM", "VYCERPANO")
PROBLEMOVE = ("NA_MINIMU", "POD_MINIMEM", "VYCERPANO")


def barva_boxu(stav_boxu: str, typ_boxu: str) -> str:
    """Barva boxu v SVG podle zadání (7.2, 17.1 krok 7), v pořadí priority: blokovaný červená,
    úplně prázdný zelená, DYN s obsahem modrá (17.1, rozhodnuto 3. 11., Q-31), STAT s obsahem šedá.
    Minimum a maximum zásoby barvu nemění (samostatná výstraha).

    stav_boxu z struktura.stav_boxu(): VOLNY | OBSAZENY | BLOKOVANY; typ_boxu: DYN | STAT.
    Vrací kód barvy, CSS ho převede: CERVENA, ZELENA, MODRA, SEDA.
    """
    if stav_boxu == "BLOKOVANY":
        return "CERVENA"
    if stav_boxu == "VOLNY":
        return "ZELENA"
    return "SEDA" if typ_boxu == "STAT" else "MODRA"


def souhrn_zasob(stavy: Iterable[str]) -> dict[str, int]:
    """Souhrn nad monitoringem (13.1): počet sledovaných dílů a počet v každém zásobovém stavu."""
    pocty = {"sledovane": 0, **{stav: 0 for stav in STAVY_ZASOBY}}
    for stav in stavy:
        pocty["sledovane"] += 1
        pocty[stav] += 1
    return pocty


def text_umisteni(ma_stat: bool, pocet_dyn: int) -> str:
    """„STAT + 2× DYN“, „STAT + DYN“, „STAT“, „DYN“ (13.1); bez umístění pomlčka."""
    casti = (["STAT"] if ma_stat else []) + ([("DYN" if pocet_dyn == 1 else f"{pocet_dyn}× DYN")] if pocet_dyn else [])
    return " + ".join(casti) or "–"


def poradi_umisteni(typ_boxu: str, kod_boxu: str, poradi_v_boxu: int) -> tuple[int, int, int]:
    """Klíč řazení umístění dílu: nejdřív STAT místo, pak DYN podle čísla boxu a pořadí v boxu.

    První umístění je to, na které SVG po vyhledání dílu přepne a které zvýrazní (kap. 16).
    """
    return (0 if typ_boxu == "STAT" else 1, int(kod_boxu[-3:]), poradi_v_boxu)


def doporuceni_laser(maximum_ks: int, stat_ks: int, dyn_ks: int, davka_ks: int | None, *,
                     odecitat_dyn: bool) -> tuple[int, int]:
    """(Chybí ve STAT, Doporučeno vyrobit) podle Q-22.

    Chybí ve STAT = max(0, Maximum − STAT) – definováno zadáním (kap. 14).
    Doporučeno = max(0, Maximum − STAT − [DYN]) zaokrouhleno nahoru na standardní dávku;
    odečtení rozpracovaného DYN je přepínač, dokud ho vlastník procesu nerozhodne.
    """
    chybi = max(0, maximum_ks - stat_ks)
    doporuceno = max(0, chybi - (dyn_ks if odecitat_dyn else 0))
    if davka_ks and doporuceno > 0:
        doporuceno = math.ceil(doporuceno / davka_ks) * davka_ks
    return chybi, doporuceno
