"""Čistá pravidla ostrova E – Sklad: pohyby a zásoby. Bez DB a bez Flasku.

Hotová ve fázi 0 (zadání kap. 12, 13 a 21.1.3–21.1.6, analýza 5.8):
- zásobový stav a upozornění zásoby (jedno otevřené, žádný spam, uzavření nad minimem, Q-13),
- kontroly cíle příjmu do DYN a uskladnění do STAT, zdroje výdeje a přesunu celé dávky,
- výběr a řazení kandidátních DYN pozic (12.1, Q-10), min/opt/max a velikost STAT místa (Q-05),
- měkké maximum (Q-11) a způsob potvrzení cíle (Q-15).
Pravidla označená (Q-xx, G2) jsou navržená výchozí řešení – do brány G2 je potvrdí vlastník procesu.
Modul nesmí importovat vlastní rozhrani.py za běhu (rozhraní používá tato pravidla, ne naopak).
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.ostrovy.struktura import rozhrani as struktura
from app.platforma.chyby import AppError, chyba_vstupu
from app.platforma.kontrakty import Varovani
from app.platforma.typy import Kontext, PotrebaMista

if TYPE_CHECKING:
    from .rozhrani import ObsahInfo, StatMistoInfo

STAVY_PROBLEMU = ("NA_MINIMU", "POD_MINIMEM", "VYCERPANO")   # UpozorneniZasoby.TypStavu
VAROVANI_NAD_MAXIMEM = "NAD_MAXIMEM"                         # Q-11: příjem nad maximum proběhne s varováním
OPRAVNENI_RUCNI_POTVRZENI = "RUCNI_POTVRZENI"                # Q-15: cíl bez skenu jen na PC s oprávněním


@dataclass(frozen=True)
class AkceUpozorneni:
    """Co udělat s upozorněním zásoby po změně stavu STAT místa (analýza 5.8)."""

    akce: str                      # ZALOZIT | AKTUALIZOVAT | UZAVRIT | NIC
    typ_stavu: str | None = None   # nový TypStavu u ZALOZIT a AKTUALIZOVAT


# --- zásobový stav a upozornění (kap. 13, analýza 5.8) ---------------------------------------------


def stav_zasoby(stav_ks: int, minimum_ks: int) -> str:
    """VYCERPANO | POD_MINIMEM | NA_MINIMU | OK v pořadí z analýzy 5.8 (stav 0 i při minimu 0, N-08).

    Stejnou logiku má pohled v_ZasobaDilu; shodu hlídá test ostrova E.
    """
    if stav_ks <= 0:
        return "VYCERPANO"
    if stav_ks < minimum_ks:
        return "POD_MINIMEM"
    if stav_ks == minimum_ks:
        return "NA_MINIMU"
    return "OK"


def vyhodnot_upozorneni(stav_ks: int, minimum_ks: int, otevrene_typ: str | None) -> AkceUpozorneni:
    """Jedno otevřené upozornění na STAT místo (Q-13):

    přechod OK → problém = ZALOZIT se snímkem stavu a minima; změna mezi problémy = AKTUALIZOVAT
    TypStavu; další výdej beze změny stavu = NIC (žádný spam); doplnění nad minimum = UZAVRIT.
    Stejně se přehodnotí po změně minima v administraci. `otevrene_typ` = TypStavu otevřeného
    upozornění, nebo None.
    """
    stav = stav_zasoby(stav_ks, minimum_ks)
    if stav == "OK":
        return AkceUpozorneni("UZAVRIT") if otevrene_typ is not None else AkceUpozorneni("NIC")
    if otevrene_typ is None:
        return AkceUpozorneni("ZALOZIT", stav)
    if otevrene_typ != stav:
        return AkceUpozorneni("AKTUALIZOVAT", stav)
    return AkceUpozorneni("NIC")


def varovani_nad_maximem(stav_po_ks: int, maximum_ks: int | None, kod_mista: str) -> Varovani | None:
    """Maximum je měkké (Q-11, G2): příjem nad maximum proběhne, odpověď nese varování."""
    if maximum_ks is None or stav_po_ks <= maximum_ks:
        return None
    return Varovani(VAROVANI_NAD_MAXIMEM, f"Na {kod_mista} je teď {stav_po_ks} ks, maximum je {maximum_ks} ks.")


# --- cíl a zdroj skladové operace (kap. 12, 21.1.4–21.1.6) ------------------------------------------


def over_zpusob_potvrzeni(zpusob: str, kdo: Kontext) -> None:
    """Na terminálu se cíl skenuje; ruční potvrzení (výběr na PC) jen s RUCNI_POTVRZENI (Q-15, G2)."""
    if zpusob == "RUCNE" and not kdo.ma(OPRAVNENI_RUCNI_POTVRZENI):
        raise AppError("NO_PERMISSION", "Cíl je potřeba naskenovat. Ruční potvrzení vyžaduje oprávnění "
                                        f"{OPRAVNENI_RUCNI_POTVRZENI}.",
                       data={"chybiOpravneni": [OPRAVNENI_RUCNI_POTVRZENI]})


def over_cil_prijmu_dyn(misto: struktura.MistoInfo, potreba: PotrebaMista | None,
                        obsah_cile: ObsahInfo | None, *, pole: str = "cilKod") -> None:
    """Cíl příjmu do DYN (12.1, 21.1.4): DYN pozice, neblokovaná, prázdná, stejné velikosti (u V6 se vejde).

    Chyby: PART_HAS_NO_SIZE (Q-26), VALIDATION_ERROR (STAT pozice), POSITION_BLOCKED (Q-09),
    POSITION_OCCUPIED, SIZE_MISMATCH.
    """
    if potreba is None:
        raise AppError("PART_HAS_NO_SIZE")
    if misto.typ_boxu != "DYN":
        raise chyba_vstupu(f"{misto.kod} je statická pozice. Pro ni použijte uskladnění do STAT.",
                           {pole: "Cíl musí být dynamická pozice."})
    if misto.blokovano:
        raise AppError("POSITION_BLOCKED", f"Pozice {misto.kod} je blokovaná.")
    if obsah_cile is not None:
        raise AppError("POSITION_OCCUPIED", f"Na pozici {misto.kod} už je {obsah_cile.pocet_ks} ks jiné dávky.")
    if not struktura.vejde_se(misto, potreba):
        raise AppError("SIZE_MISMATCH", f"Pozice {misto.kod} má velikost {misto.velikost}, díl potřebuje "
                                        f"{potreba.velikost}.")


def over_cil_uskladneni_stat(misto: struktura.MistoInfo, stat_misto: StatMistoInfo | None, dil_id: int,
                             obsah_cile: ObsahInfo | None) -> None:
    """Cíl uskladnění do STAT (12.5, 21.1.4): aktivní STAT místo právě tohoto dílu, neblokované.

    Blokovaný cíl se nikdy nenahradí jiným místem (Q-14). Chyby: VALIDATION_ERROR (DYN pozice),
    WRONG_PART (místo bez přiřazení nebo jiného dílu), POSITION_BLOCKED.
    """
    if misto.typ_boxu != "STAT":
        raise chyba_vstupu(f"{misto.kod} je dynamická pozice. Pro ni použijte příjem do DYN.",
                           {"cilKod": "Cíl musí být statická pozice."})
    if stat_misto is None:
        raise AppError("WRONG_PART", f"Pozice {misto.kod} nemá přiřazený žádný díl.")
    if stat_misto.dil_id != dil_id or (obsah_cile is not None and obsah_cile.dil_id != dil_id):
        raise AppError("WRONG_PART")
    if misto.blokovano:
        raise AppError("POSITION_BLOCKED", f"Pozice {misto.kod} je blokovaná. Dávka zůstává, kde je; "
                                           "jiné místo se automaticky nenabízí (Q-14).")


def over_zdroj(misto: struktura.MistoInfo, obsah: ObsahInfo | None, pocet_ks: int | None, *,
               ocekavany_stav_ks: int | None = None, dil_id: int | None = None, pole: str = "zdrojKod") -> ObsahInfo:
    """Zdroj výdeje nebo přesunu (12.2, 12.6, 21.1.5): neblokovaný, s obsahem, 0 < množství ≤ stav.

    pocet_ks None = celá dávka (přesun). ocekavany_stav_ks = stav, který obsluha viděla – jiný
    znamená souběžnou změnu (CONCURRENT_CHANGE). dil_id = díl, který má na zdroji být (uskladnění
    do STAT ze zdroje). Chyby: POSITION_BLOCKED, INSUFFICIENT_STOCK, CONCURRENT_CHANGE, WRONG_PART.
    """
    if misto.blokovano:
        raise AppError("POSITION_BLOCKED", f"Pozice {misto.kod} je blokovaná.")
    if obsah is None:
        raise AppError("INSUFFICIENT_STOCK", f"Pozice {misto.kod} je prázdná.")
    if dil_id is not None and obsah.dil_id != dil_id:
        raise AppError("WRONG_PART", f"Na pozici {misto.kod} je jiný díl.")
    if ocekavany_stav_ks is not None and ocekavany_stav_ks != obsah.pocet_ks:
        raise AppError("CONCURRENT_CHANGE", f"Stav pozice {misto.kod} se mezitím změnil: čekali jste "
                                            f"{ocekavany_stav_ks} ks, je tam {obsah.pocet_ks} ks.")
    if pocet_ks is not None and pocet_ks > obsah.pocet_ks:
        raise AppError("INSUFFICIENT_STOCK", f"Na pozici {misto.kod} je jen {obsah.pocet_ks} ks.")
    return obsah


def over_presun(zdroj: struktura.MistoInfo, cil: struktura.MistoInfo, obsah_zdroje: ObsahInfo | None,
                obsah_cile: ObsahInfo | None, potreba: PotrebaMista | None) -> ObsahInfo:
    """Přesun celé dávky DYN → DYN v rámci pracoviště (12.3, Q-07, G2); mezi pracovišti = výdej + příjem.

    Chyby: VALIDATION_ERROR (stejná pozice, STAT, jiné pracoviště), POSITION_BLOCKED,
    INSUFFICIENT_STOCK, POSITION_OCCUPIED, SIZE_MISMATCH, PART_HAS_NO_SIZE.
    """
    if zdroj.vnitrni_pozice_id == cil.vnitrni_pozice_id:
        raise chyba_vstupu("Zdroj a cíl jsou stejná pozice.", {"cilKod": "Naskenujte jinou pozici."})
    if zdroj.typ_boxu != "DYN":
        raise chyba_vstupu(f"{zdroj.kod} je statická pozice. Ze STAT se díl vydává (výdej).",
                           {"zdrojKod": "Přesouvá se jen z dynamické pozice."})
    if cil.typ_boxu == "DYN" and cil.pracoviste != zdroj.pracoviste:
        raise chyba_vstupu(f"Přesun mezi pracovišti {zdroj.pracoviste} a {cil.pracoviste} není možný – "
                           "udělejte výdej a příjem.", {"cilKod": "Cíl je na jiném pracovišti."})
    obsah = over_zdroj(zdroj, obsah_zdroje, None)
    over_cil_prijmu_dyn(cil, potreba, obsah_cile)
    return obsah


def vyber_kandidaty(mista: Sequence[struktura.MistoInfo], potreba: PotrebaMista | None, obsazene: Iterable[int],
                    regal_id: int) -> list[struktura.MistoInfo]:
    """Volné DYN pozice pro příjem dílu (12.1, 21.1.3): neblokované, prázdné, vejde se.

    Řazení: nejdřív zvolený regál, pak ostatní regály pracoviště (Q-10, G2); v rámci regálu podle
    čísla boxu vzestupně (BPLE001 před BPLE010) a pořadí pozice v boxu. Chyby: PART_HAS_NO_SIZE.
    """
    if potreba is None:
        raise AppError("PART_HAS_NO_SIZE")
    obsazene = set(obsazene)
    volna = [m for m in mista if m.typ_boxu == "DYN" and not m.blokovano and m.vnitrni_pozice_id not in obsazene
             and struktura.vejde_se(m, potreba)]
    return sorted(volna, key=lambda m: (m.regal_id != regal_id, int(m.kod_boxu[-3:]), m.poradi_v_boxu))


# --- STAT místo (kap. 13, Q-05, Q-12) ----------------------------------------------------------------


def over_min_opt_max(minimum: int, optimum: int | None, maximum: int | None) -> None:
    """Stejná pravidla jako CHECK v tabulce StatickeUmisteniDilu – s chybou u konkrétního pole."""
    chyby = {}
    if minimum < 0:
        chyby["minimalniKs"] = "Minimum nesmí být záporné."
    if maximum is not None and maximum < minimum:
        chyby["maximalniKs"] = "Maximum nesmí být menší než minimum."
    if optimum is not None and (optimum < minimum or (maximum is not None and optimum > maximum)):
        chyby["optimalniKs"] = "Optimum musí být mezi minimem a maximem."
    if chyby:
        raise chyba_vstupu("Zkontrolujte minimum, optimum a maximum.", chyby)


def over_stat_pozici(misto: struktura.MistoInfo, potreba: PotrebaMista | None, *, prepsat_velikost: bool,
                     kdo: Kontext, duvod: str | None) -> None:
    """Pozice pro statické přiřazení: STAT box a velikost dílu = velikost pozice (Q-05).

    Vědomé přepsání velikosti jen TECH nebo ADMIN s důvodem (audit). Díl bez velikosti se do STAT
    přiřadit smí (Q-26). Chyby: VALIDATION_ERROR, SIZE_MISMATCH, NO_PERMISSION.
    """
    if misto.typ_boxu != "STAT":
        raise chyba_vstupu(f"{misto.kod} není statická pozice.", {"vnitrniPoziceId": "Vyberte pozici STAT boxu."})
    if potreba is None or potreba.velikost == misto.velikost:
        return
    if not prepsat_velikost:
        raise AppError("SIZE_MISMATCH", f"Pozice {misto.kod} má velikost {misto.velikost}, díl {potreba.velikost}. "
                                        "Přiřazení jiné velikosti je vědomé přepsání (prepsatVelikost + důvod).")
    if kdo.kod_role not in ("TECH", "ADMIN"):
        raise AppError("NO_PERMISSION", "Přepsat velikost smí jen technolog nebo administrátor (Q-05).")
    if not duvod:
        raise chyba_vstupu("Přepsání velikosti vyžaduje důvod.", {"duvod": "Povinný údaj při přepsání velikosti."})
