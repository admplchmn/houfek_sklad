"""Čistá pravidla ostrova F – Inventura: bez DB a bez Flasku (zadání kap. 18, 21.1.7, analýza 5.11).

Hotová ve fázi 0:
- rozsah inventury (stejná pravidla jako CHECK CK_Inventura_Rozsah),
- zápis a vyhodnocení položky SHODA / ROZDIL / JINY_DIL, stav položky CEKA / ZAPSANO / PREPOCITAT,
- kontrola dokončení a plán korekcí (rozdíl se nikdy nepřepíše potichu – vždy pohyb INVENTURA).

Navržená výchozí řešení k potvrzení (Q-16, Q-17): přepočet po pohybu od zápisu; JINY_DIL ve STAT
pozici potřebuje cíl pro nalezený díl. Ve schématu G1 chybí InventuraPolozka.PosledniPohybID
a StavPolozky (D8) – doplní migrace před fází 1.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.platforma.chyby import AppError, chyba_vstupu

ROZSAHY = ("FULL", "PRAC", "REGAL", "UROVEN", "BOX", "POZICE")


@dataclass(frozen=True)
class Polozka:
    """Položka inventury pro pravidla (vstup kontroly dokončení a plánu korekcí)."""

    vnitrni_pozice_id: int
    kod: str
    typ_boxu: str                     # DYN | STAT
    ocekavany_dil_id: int | None      # None = pozice měla být prázdná
    ocekavany_pocet_ks: int
    skutecny_dil_id: int | None       # None = obsluha zapsala „prázdné“
    skutecny_pocet_ks: int | None     # None = ještě nezapsáno
    stav: str                         # CEKA | ZAPSANO | PREPOCITAT


@dataclass(frozen=True)
class Korekce:
    """Jeden korekční zápis přes sklad.zauctuj_korekci: nový stav dílu na pozici."""

    vnitrni_pozice_id: int
    dil_id: int
    novy_stav_ks: int | None          # absolutní nový stav (počítaná pozice)
    pricist_ks: int | None = None     # cíl JINY_DIL ve STAT: přičte se k aktuálnímu stavu cíle


def over_rozsah(typ_rozsahu: str, cil_id: int | None) -> None:
    """FULL nemá cíl, ostatní rozsahy ho mají povinný (CK_Inventura_Rozsah)."""
    if typ_rozsahu == "FULL" and cil_id is not None:
        raise chyba_vstupu("Celá inventura skladu nemá cíl.", {"cilId": "U rozsahu FULL se neposílá."})
    if typ_rozsahu != "FULL" and cil_id is None:
        raise chyba_vstupu(f"Rozsah {typ_rozsahu} potřebuje cíl.", {"cilId": "Povinný údaj."})


def over_zapis(skutecny_dil_id: int | None, skutecny_pocet_ks: int) -> None:
    """„Prázdné“ = bez dílu a 0 ks; nalezený díl = aspoň 1 ks."""
    if skutecny_dil_id is None and skutecny_pocet_ks != 0:
        raise chyba_vstupu("Bez dílu je pozice prázdná – počet musí být 0.", {"skutecnyPocetKs": "Má být 0."})
    if skutecny_dil_id is not None and skutecny_pocet_ks <= 0:
        raise chyba_vstupu("Nalezený díl musí mít aspoň 1 ks; prázdnou pozici zapište bez dílu.",
                           {"skutecnyPocetKs": "Musí být větší než 0."})


def vyhodnot(ocekavany_dil_id: int | None, ocekavany_pocet_ks: int, skutecny_dil_id: int | None,
             skutecny_pocet_ks: int) -> tuple[str, int]:
    """Vyhodnocení položky (21.1.7) → (SHODA | ROZDIL | JINY_DIL, rozdíl skutečný − očekávaný počet).

    Stejný díl (i obě prázdné) = SHODA nebo ROZDIL; nalezeno prázdné místo očekávaného dílu = ROZDIL;
    jiný díl, než čekal systém (i na pozici, která měla být prázdná) = JINY_DIL.
    """
    rozdil = skutecny_pocet_ks - ocekavany_pocet_ks
    if skutecny_dil_id == ocekavany_dil_id or skutecny_dil_id is None:
        return ("SHODA" if rozdil == 0 else "ROZDIL"), rozdil
    return "JINY_DIL", rozdil


def stav_polozky(zapsano: bool, pohyb_pri_zapisu: int | None, posledni_pohyb: int | None) -> str:
    """CEKA (nezapsáno) | ZAPSANO | PREPOCITAT (od zápisu proběhl na pozici skladový pohyb, Q-16)."""
    if not zapsano:
        return "CEKA"
    return "ZAPSANO" if pohyb_pri_zapisu == posledni_pohyb else "PREPOCITAT"


def over_dokonceni(polozky: Sequence[Polozka], cile_jiny_dil: Mapping[int, object]) -> None:
    """Dokončit jde jen inventuru, kde je všechno zapsané, nic nečeká na přepočet a každý JINY_DIL
    ve STAT pozici má cíl pro nalezený díl (Q-17). Chyby: VALIDATION_ERROR, INVENTORY_RECOUNT."""
    cekaji = [p.kod for p in polozky if p.stav == "CEKA"]
    if cekaji:
        raise chyba_vstupu(f"Nezapsané pozice ({len(cekaji)}): {_vycet(cekaji)}.")
    prepocet = [p.kod for p in polozky if p.stav == "PREPOCITAT"]
    if prepocet:
        raise AppError("INVENTORY_RECOUNT", f"Přepočítejte pozice {_vycet(prepocet)} – od zápisu na nich "
                                            "proběhl skladový pohyb.", data={"pozice": prepocet})
    bez_cile = [p.kod for p in polozky if _jiny_dil_ve_stat(p) and p.vnitrni_pozice_id not in cile_jiny_dil]
    if bez_cile:
        raise chyba_vstupu(f"Nalezený jiný díl na STAT pozici {_vycet(bez_cile)} potřebuje cíl (DYN pozici "
                           "stejné velikosti nebo STAT místo nalezeného dílu).",
                           {"cileJinyDil": "Doplňte cíl pro každou STAT pozici s jiným dílem."})


def planuj_korekce(polozky: Sequence[Polozka], cile_jiny_dil: Mapping[int, int]) -> list[Korekce]:
    """Korekce pro dokončení (vše v jedné transakci): ROZDIL = nový stav; JINY_DIL = odúčtovat očekávaný
    díl a zaúčtovat nalezený (v DYN na stejné pozici, ve STAT na zvolený cíl – Q-17). Bez rozdílu nic."""
    korekce: list[Korekce] = []
    for p in polozky:
        if p.skutecny_pocet_ks is None:
            continue
        vysledek, _ = vyhodnot(p.ocekavany_dil_id, p.ocekavany_pocet_ks, p.skutecny_dil_id, p.skutecny_pocet_ks)
        if vysledek == "ROZDIL" and p.ocekavany_dil_id is not None:
            korekce.append(Korekce(p.vnitrni_pozice_id, p.ocekavany_dil_id, p.skutecny_pocet_ks))
        elif vysledek == "JINY_DIL" and p.skutecny_dil_id is not None:
            if p.ocekavany_dil_id is not None:
                korekce.append(Korekce(p.vnitrni_pozice_id, p.ocekavany_dil_id, 0))
            if _jiny_dil_ve_stat(p):
                korekce.append(Korekce(cile_jiny_dil[p.vnitrni_pozice_id], p.skutecny_dil_id, None,
                                       pricist_ks=p.skutecny_pocet_ks))
            else:
                korekce.append(Korekce(p.vnitrni_pozice_id, p.skutecny_dil_id, p.skutecny_pocet_ks))
    return korekce


def souhrn(polozky: Sequence[Polozka]) -> dict[str, int]:
    """Počty SHODA / ROZDIL / JINY_DIL zapsaných položek."""
    pocty = {"SHODA": 0, "ROZDIL": 0, "JINY_DIL": 0}
    for p in polozky:
        if p.skutecny_pocet_ks is not None:
            pocty[vyhodnot(p.ocekavany_dil_id, p.ocekavany_pocet_ks, p.skutecny_dil_id, p.skutecny_pocet_ks)[0]] += 1
    return pocty


def _jiny_dil_ve_stat(p: Polozka) -> bool:
    return (p.typ_boxu == "STAT" and p.skutecny_dil_id is not None and p.skutecny_pocet_ks is not None
            and vyhodnot(p.ocekavany_dil_id, p.ocekavany_pocet_ks, p.skutecny_dil_id, p.skutecny_pocet_ks)[0]
            == "JINY_DIL")


def _vycet(kody: Sequence[str], nejvic: int = 10) -> str:
    return ", ".join(kody[:nejvic]) + (f" a dalších {len(kody) - nejvic}" if len(kody) > nejvic else "")
