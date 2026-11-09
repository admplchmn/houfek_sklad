"""Čistá pravidla ostrova F – Inventura: bez DB a bez Flasku (zadání kap. 18, 21.1.7, analýza 5.11).

- rozsah inventury (stejná pravidla jako CHECK CK_Inventura_Rozsah),
- zápis a vyhodnocení položky SHODA / ROZDIL / JINY_DIL,
- stav položky CEKA / ZAPSANO / PREPOCITAT za provozu (D-26): počítá se z pohybů po vodoznaku
  InventuraPolozka.PosledniPohybID (migrace 005), do databáze se nikdy neukládá,
- kontrola dokončení, cíl pro nalezený jiný díl (D-27, S-22) a plán korekcí
  (rozdíl se nikdy nepřepíše potichu – vždy pohyb INVENTURA).
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from app.ostrovy.struktura import rozhrani as struktura
from app.platforma.chyby import AppError, chyba_vstupu

if TYPE_CHECKING:
    from app.ostrovy.sklad.rozhrani import ObsahInfo, StatMistoInfo
    from app.platforma.typy import PotrebaMista

ROZSAHY = ("FULL", "PRAC", "REGAL", "UROVEN", "BOX", "POZICE")
POLE_CIL = {"cileJinyDil": "Cílem je volná neblokovaná DYN pozice, do které se díl vejde, "
                           "nebo aktivní STAT místo nalezeného dílu."}


@dataclass(frozen=True)
class Polozka:
    """Položka inventury pro pravidla (vstup kontroly dokončení a plánu korekcí)."""

    vnitrni_pozice_id: int
    kod: str                          # štítek pozice, nebo její ID, pokud pozice mezitím zmizela
    typ_boxu: str                     # DYN | STAT (prázdný řetězec u neaktivní pozice)
    ocekavany_dil_id: int | None      # None = pozice měla být prázdná
    ocekavany_pocet_ks: int
    skutecny_dil_id: int | None       # None = obsluha zapsala „prázdné“
    skutecny_pocet_ks: int | None     # None = ještě nezapsáno
    aktualni_pocet_ks: int            # aktuální počet očekávaného dílu na pozici (0 = prázdná/jiný díl)
    stav: str                         # CEKA | ZAPSANO | PREPOCITAT
    datum_kontroly: datetime | None = None


@dataclass(frozen=True)
class Pohyb:
    """Skladový pohyb na pozici po jejím vodoznaku (z pohledu v_PohybDetail, D-26)."""

    dil_id: int
    stav_po_ks: int                   # stav po pohybu; 0 = pozice byla vyprázdněná


@dataclass(frozen=True)
class Korekce:
    """Jeden korekční zápis přes sklad.zauctuj_korekci: nový stav dílu na pozici."""

    vnitrni_pozice_id: int
    dil_id: int
    novy_stav_ks: int | None          # absolutní nový stav (počítaná pozice)
    pricist_ks: int | None = None     # cíl JINY_DIL: přičte se k aktuálnímu stavu cíle


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


def jiny_dil(p: Polozka) -> bool:
    """Položka má nalezený díl, který systém nečekal – taková položka potřebuje cíl (D-27, S-22)."""
    return (p.skutecny_dil_id is not None and p.skutecny_pocet_ks is not None
            and vyhodnot(p.ocekavany_dil_id, p.ocekavany_pocet_ks, p.skutecny_dil_id, p.skutecny_pocet_ks)[0]
            == "JINY_DIL")


def stav_polozky(*, zapsano: bool, dil_id: int | None, vysledek: str | None, rozdil_ks: int,
                 aktualni_pocet_ks: int, pohyby: Sequence[Pohyb], aktivni: bool) -> str:
    """CEKA | ZAPSANO | PREPOCITAT za provozu (D-26).

    `dil_id` je očekávaný díl položky, `rozdil_ks` a `vysledek` z vyhodnot(), `aktualni_pocet_ks`
    aktuální počet očekávaného dílu na pozici a `pohyby` vše, co bylo na pozici od zápisu.
    Zapsáno zůstává, když se nic nedělo, nebo když všechny pohyby jsou týž díl, žádný z nich
    pozici nevyprázdnil (StavPo 0, po kterém někdo další přiložil) a dopočet
    „aktuální stav + rozdíl“ není záporný – korekce se pak dopočítá (planuj_korekce).
    Přepočítává se jiný díl, vyprázdnění a znovuobsazení, neaktivní pozice po rekonfiguraci,
    záporný dopočet a jakýkoli pohyb u JINY_DIL. Zjištěný díl ani počet pohyb nikdy nepřepíše.
    """
    if not zapsano:
        return "CEKA"
    if not aktivni:
        return "PREPOCITAT"
    if not pohyby:
        return "ZAPSANO"
    if vysledek == "JINY_DIL" or any(p.dil_id != dil_id for p in pohyby):
        return "PREPOCITAT"
    if any(p.stav_po_ks == 0 for p in pohyby[:-1]):
        return "PREPOCITAT"
    return "PREPOCITAT" if aktualni_pocet_ks + rozdil_ks < 0 else "ZAPSANO"


def over_cil_jiny_dil(cil: struktura.MistoInfo, *, nalezeny_dil_id: int, potreba: PotrebaMista | None,
                      obsah_cilu: ObsahInfo | None, stat_misto_cilu: StatMistoInfo | None,
                      kod_pozice: str) -> None:
    """Cíl pro jiný díl nalezený při inventuře (D-27, S-22): volná neblokovaná DYN pozice, do které
    se díl vejde, nebo aktivní STAT místo právě nalezeného dílu.

    `obsah_cilu` je obsah cíle; None = cíl je po odúčtování očekávaného dílu volný, takže jím může
    být i současná pozice položky (volá ji služba). Blokovaná pozice cílem není ani jako současná
    pozice – přísná varianta otevřeného detailu D-27 (Q-09 × Q-17); jiné místo se za obsluhu
    nenabízí. Chyby: VALIDATION_ERROR (pole cileJinyDil).
    """
    if cil.blokovano:
        raise chyba_vstupu(f"{cil.kod} je blokovaný – inventura jiné místo sama nevybere.", POLE_CIL)
    if cil.typ_boxu == "DYN":
        if obsah_cilu is not None:
            raise chyba_vstupu(f"Na {cil.kod} už je {obsah_cilu.pocet_ks} ks dílu "
                               f"{obsah_cilu.dil_id} – cíl musí být volný.", POLE_CIL)
        if potreba is None:
            raise chyba_vstupu(f"Nalezený díl {nalezeny_dil_id} z {kod_pozice} nemá velikost pozice, "
                               f"do DYN {cil.kod} se nedává.", POLE_CIL)
        if not struktura.vejde_se(cil, potreba):
            raise chyba_vstupu(f"{cil.kod} má velikost {cil.velikost}, nalezený díl potřebuje "
                               f"{potreba.velikost}.", POLE_CIL)
    elif stat_misto_cilu is None or stat_misto_cilu.dil_id != nalezeny_dil_id:
        raise chyba_vstupu(f"{cil.kod} není aktivní STAT místo nalezeného dílu {nalezeny_dil_id}.", POLE_CIL)


def over_dokonceni(polozky: Sequence[Polozka], cile_jiny_dil: Mapping[int, str]) -> None:
    """Dokončit jde jen inventuru, kde je všechno zapsané, nic nečeká na přepočet a každý nalezený
    jiný díl má cíl (D-27, S-22). Chyby: VALIDATION_ERROR, INVENTORY_RECOUNT."""
    cekaji = [p.kod for p in polozky if p.stav == "CEKA"]
    if cekaji:
        raise chyba_vstupu(f"Nezapsané pozice ({len(cekaji)}): {_vycet(cekaji)}.")
    prepocet = [p.kod for p in polozky if p.stav == "PREPOCITAT"]
    if prepocet:
        raise AppError("INVENTORY_RECOUNT", f"Přepočítejte pozice {_vycet(prepocet)} – od zápisu na nich "
                                            "proběhl skladový pohyb.", data={"pozice": prepocet})
    bez_cile = [p.kod for p in polozky if jiny_dil(p) and p.vnitrni_pozice_id not in cile_jiny_dil]
    if bez_cile:
        raise chyba_vstupu(f"Nalezený jiný díl na pozici {_vycet(bez_cile)} potřebuje cíl (volná DYN "
                           "pozice stejné velikosti, nebo STAT místo nalezeného dílu).", POLE_CIL)


def planuj_korekce(polozky: Sequence[Polozka], cile_jiny_dil: Mapping[int, int]) -> list[Korekce]:
    """Korekce pro dokončení (vše v jedné transakci): ROZDIL = aktuální stav + rozdíl (D-26);
    JINY_DIL = odúčtovat očekávaný díl a nalezený přičíst na cíl, kterým může být i současná
    pozice (D-27). Bez rozdílu nic."""
    korekce: list[Korekce] = []
    for p in polozky:
        if p.skutecny_pocet_ks is None:
            continue
        vysledek, rozdil = vyhodnot(p.ocekavany_dil_id, p.ocekavany_pocet_ks, p.skutecny_dil_id,
                                    p.skutecny_pocet_ks)
        if vysledek == "ROZDIL" and p.ocekavany_dil_id is not None:
            korekce.append(Korekce(p.vnitrni_pozice_id, p.ocekavany_dil_id, p.aktualni_pocet_ks + rozdil))
        elif vysledek == "JINY_DIL" and p.skutecny_dil_id is not None:
            if p.ocekavany_dil_id is not None:
                korekce.append(Korekce(p.vnitrni_pozice_id, p.ocekavany_dil_id, 0))
            korekce.append(Korekce(cile_jiny_dil[p.vnitrni_pozice_id], p.skutecny_dil_id, None,
                                   pricist_ks=p.skutecny_pocet_ks))
    return korekce


def souhrn(polozky: Sequence[Polozka]) -> dict[str, int]:
    """Počty SHODA / ROZDIL / JINY_DIL zapsaných položek."""
    pocty = {"SHODA": 0, "ROZDIL": 0, "JINY_DIL": 0}
    for p in polozky:
        if p.skutecny_pocet_ks is not None:
            pocty[vyhodnot(p.ocekavany_dil_id, p.ocekavany_pocet_ks, p.skutecny_dil_id, p.skutecny_pocet_ks)[0]] += 1
    return pocty


def _vycet(kody: Sequence[str], nejvic: int = 10) -> str:
    return ", ".join(kody[:nejvic]) + (f" a dalších {len(kody) - nejvic}" if len(kody) > nejvic else "")
