"""VEŘEJNÉ ROZHRANÍ ostrova D – Díly a číselníky (sekce 7.4).

CO: kmenová data dílu, která sklad potřebuje. Normalizace identifikačního čísla je hotová
(jedna pro hledání, import i kontrolu duplicity). Všechny funkce pracují nad DB; vzorová data
(`ukazky`) slouží jen tam, kde SQL Server není – vývoj a testy bez DB (`spoj` je None nebo
sqlite), stejný vzor jako ostrov B.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.platforma.audit import zapis
from app.platforma.chyby import AppError
from app.platforma.db import Spojeni
from app.platforma.typy import Kontext, PolozkaCiselniku, PotrebaMista, Rozmer

from . import domena, repozitar
from .kontrakty import TYPY_CISELNIKU


@dataclass(frozen=True)
class DilInfo:
    dil_id: int
    identifikacni_cislo: str           # "CE21RA 10 100194"
    nazev: str | None
    material: str | None               # kód, např. "S235"
    tloustka_mm: Decimal | None
    prvni_operace: str | None          # kód, např. "LASER"
    standardni_davka_ks: int | None
    potreba: PotrebaMista | None       # None = díl nemá velikost pozice (do DYN nelze, Q-26)
    vault_url: str | None              # Vault zatím jen připraveno
    aktivni: bool


@dataclass(frozen=True)
class NovyDil:
    """Data pro založení dílu (migrace). Kódy číselníků musí existovat."""

    identifikacni_cislo: str
    nazev: str | None = None
    material: str | None = None
    tloustka_mm: Decimal | None = None
    prvni_operace: str | None = None
    standardni_davka_ks: int | None = None
    potreba: PotrebaMista | None = None
    vault_url: str | None = None
    poznamka: str | None = None        # pokyn pro obsluhu (JINÉ INFORMACE z XLSM)


def normalizuj_identifikacni_cislo(text: str) -> str:
    """Ořez, sloučení mezer, velká písmena: ' ce21ra  10 100194 ' → 'CE21RA 10 100194'."""
    return re.sub(r"\s+", " ", text or "").strip().upper()


def najdi_dil(spoj: Spojeni, identifikacni_cislo: str) -> DilInfo:
    """Aktivní díl podle identifikačního čísla (normalizuje se). Chyby: NOT_FOUND."""
    cislo = normalizuj_identifikacni_cislo(identifikacni_cislo)
    if spoj is not None and spoj.dialekt == "mssql":
        radek = repozitar.najdi_dil_podle_cisla(spoj, cislo, jen_aktivni=True)
        if radek is None:
            raise AppError("NOT_FOUND", f"Díl {cislo} neexistuje nebo není aktivní.")
        return _dil_info(radek)

    from . import ukazky  # KOSTRA (fáze 0)

    for dil in ukazky.DIL_INFO.values():
        if dil.identifikacni_cislo == cislo and dil.aktivni:
            return dil
    raise AppError("NOT_FOUND", f"Díl {cislo} neexistuje nebo není aktivní.")


def nacti_dily(spoj: Spojeni, dil_ids: list[int]) -> dict[int, DilInfo]:
    """Hromadné načtení podle ID (i neaktivní); neexistující ve výsledku chybí."""
    if spoj is not None and spoj.dialekt == "mssql":
        return {radek["DilID"]: _dil_info(radek) for radek in repozitar.nacti_dily_podle_id(spoj, dil_ids)}

    from . import ukazky  # KOSTRA (fáze 0)

    return {i: ukazky.DIL_INFO[i] for i in dil_ids if i in ukazky.DIL_INFO}


def hledej_dily(spoj: Spojeni, text: str, *, material: str | None = None, tloustka_mm: Decimal | None = None,
                prvni_operace: str | None = None, limit: int = 50) -> list[DilInfo]:
    """Hledání podle části identifikačního čísla nebo názvu (pro sken a hledání v ostrově Přehledy).

    Jen aktivní díly, seřazené podle identifikačního čísla; filtry jsou kódy číselníků.
    """
    hledany = normalizuj_identifikacni_cislo(text)
    if spoj is not None and spoj.dialekt == "mssql":
        return [_dil_info(radek) for radek in repozitar.hledani_dilu(
            spoj, hledany, material=material, tloustka_mm=tloustka_mm, prvni_operace=prvni_operace, limit=limit)]

    from . import ukazky  # KOSTRA (fáze 0)

    nalezene = [d for d in ukazky.DIL_INFO.values()
                if d.aktivni and (hledany in d.identifikacni_cislo or hledany.casefold() in (d.nazev or "").casefold())
                and material in (None, d.material) and tloustka_mm in (None, d.tloustka_mm)
                and prvni_operace in (None, d.prvni_operace)]
    return sorted(nalezene, key=lambda d: d.identifikacni_cislo)[:limit]


def nacti_ciselniky(spoj: Spojeni) -> dict[str, tuple[PolozkaCiselniku, ...]]:
    """Číselníky dílů pro filtry: klíče "materialy", "tloustky", "operace" (i vyřazené položky)."""
    if spoj is not None and spoj.dialekt == "mssql":
        return {typ: tuple(PolozkaCiselniku(p["id"], p["kod"], p["nazev"], bool(p["aktivni"]))
                           for p in repozitar.polozky_ciselniku(spoj, typ)) for typ in TYPY_CISELNIKU}

    from . import ukazky  # KOSTRA (fáze 0)

    return {typ: tuple(PolozkaCiselniku(p.id, p.kod, p.nazev, p.aktivni) for p in polozky)
            for typ, polozky in ukazky.CISELNIKY.items()}


def zaloz_dil(spoj: Spojeni, kdo: Kontext, dil: NovyDil) -> int:
    """Založí díl v transakci volajícího (migrace) a zapíše audit. Vrací DilID.

    Chyby: ALREADY_EXISTS, NOT_FOUND (neznámý kód číselníku), VALIDATION_ERROR.

    Transakci otevírá i uzavírá volající (P5) – proto tady žádný @transakce není a nic se
    nekommituje. Kódy číselníků se překládají na ID a rozměr dílu odpovídá jeho velikosti.
    """
    cislo = normalizuj_identifikacni_cislo(dil.identifikacni_cislo)
    if repozitar.existuje_dil(spoj, cislo):
        raise AppError("ALREADY_EXISTS", f"Díl {cislo} už existuje.")
    velikost = dil.potreba.velikost if dil.potreba else None
    rozmer = dil.potreba.rozmer if dil.potreba else None
    delka = rozmer.delka_mm if rozmer else None
    hloubka = rozmer.hloubka_mm if rozmer else None
    id_velikosti = _id_velikosti(spoj, velikost)
    material_id = _id_polozky(spoj, "materialy", dil.material)
    tloustka_id = _id_polozky(spoj, "tloustky", dil.tloustka_mm)
    operace_id = _id_polozky(spoj, "operace", dil.prvni_operace)
    domena.potreba_mista(velikost, delka, hloubka)          # rozměr musí sedět k velikosti (Q-01)
    dil_id = repozitar.vloz_dil(spoj, identifikacni_cislo=cislo, nazev=dil.nazev, material_id=material_id,
                                tloustka_id=tloustka_id, prvni_operace_id=operace_id,
                                standardni_davka_ks=dil.standardni_davka_ks, velikost_pozice_id=id_velikosti,
                                potrebna_delka_mm=delka, potrebna_hloubka_mm=hloubka, vault_url=dil.vault_url,
                                poznamka=dil.poznamka)
    zapis(spoj, kdo, "DIL", dil_id, "IdentifikacniCislo", None, cislo)
    return dil_id


def _dil_info(radek: dict[str, Any]) -> DilInfo:
    """Řádek dotazu na Dil → DilInfo; velikost a rozměr se skládají na potřebu místa."""
    delka, hloubka = radek["PotrebnaDelkaMM"], radek["PotrebnaHloubkaMM"]
    rozmer = Rozmer(delka, hloubka) if delka is not None and hloubka is not None else None
    potreba = PotrebaMista(radek["Velikost"], rozmer) if radek["Velikost"] else None
    return DilInfo(
        dil_id=radek["DilID"], identifikacni_cislo=radek["IdentifikacniCislo"], nazev=radek["NazevDilu"],
        material=radek["KodMaterialu"], tloustka_mm=radek["TloustkaMM"], prvni_operace=radek["KodOperace"],
        standardni_davka_ks=radek["StandardniDavkaKs"], potreba=potreba,
        vault_url=radek["VaultVykresURL"], aktivni=bool(radek["Aktivni"]))


def _id_velikosti(spoj: Spojeni, kod: str | None) -> int | None:
    """Velikost „V1“–„V6“ → ID; velikosti D nevlastní, čte je z pohledu v_VelikostPozice (P2)."""
    if kod is None:
        return None
    id_velikosti = repozitar.id_velikosti_podle_kodu(spoj, kod)
    if id_velikosti is None:
        raise AppError("NOT_FOUND", f"Velikost pozice {kod} neexistuje.")
    return id_velikosti


def _id_polozky(spoj: Spojeni, typ: str, kod: object | None) -> int | None:
    """Kód položky číselníku → ID, neznámý kód je NOT_FOUND (tloušťka přichází jako Decimal).

    Kód se před hledáním normalizuje stejně jako při zápisu, proto „3,00“ najde tloušťku 3.00.
    """
    if kod is None:
        return None
    normalizovany = domena.normalizuj_kod_ciselniku(typ, str(kod))
    polozka = repozitar.polozka_ciselniku_podle_kodu(spoj, typ, normalizovany)
    if polozka is None:
        raise AppError("NOT_FOUND", f"Položka {normalizovany} číselníku {typ} neexistuje.")
    return polozka["id"]
