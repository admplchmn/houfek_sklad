"""VEŘEJNÉ ROZHRANÍ ostrova D – Díly a číselníky (sekce 7.4).

CO: kmenová data dílu, která sklad potřebuje. Normalizace identifikačního čísla je hotová
(jedna pro hledání, import i kontrolu duplicity); funkce nad DB jsou ve fázi 0 kostra.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from app.platforma.chyby import AppError
from app.platforma.db import Spojeni
from app.platforma.typy import Kontext, PolozkaCiselniku, PotrebaMista


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
    from . import ukazky  # KOSTRA (fáze 0)

    cislo = normalizuj_identifikacni_cislo(identifikacni_cislo)
    for dil in ukazky.DIL_INFO.values():
        if dil.identifikacni_cislo == cislo and dil.aktivni:
            return dil
    raise AppError("NOT_FOUND", f"Díl {cislo} neexistuje nebo není aktivní.")


def nacti_dily(spoj: Spojeni, dil_ids: list[int]) -> dict[int, DilInfo]:
    """Hromadné načtení podle ID (i neaktivní); neexistující ve výsledku chybí."""
    from . import ukazky  # KOSTRA (fáze 0)

    return {i: ukazky.DIL_INFO[i] for i in dil_ids if i in ukazky.DIL_INFO}


def hledej_dily(spoj: Spojeni, text: str, *, material: str | None = None, tloustka_mm: Decimal | None = None,
                prvni_operace: str | None = None, limit: int = 50) -> list[DilInfo]:
    """Hledání podle části identifikačního čísla nebo názvu (pro sken a hledání v ostrově Přehledy).

    Jen aktivní díly, seřazené podle identifikačního čísla; filtry jsou kódy číselníků.
    """
    from . import ukazky  # KOSTRA (fáze 0)

    hledany = normalizuj_identifikacni_cislo(text)
    nalezene = [d for d in ukazky.DIL_INFO.values()
                if d.aktivni and (hledany in d.identifikacni_cislo or hledany.casefold() in (d.nazev or "").casefold())
                and material in (None, d.material) and tloustka_mm in (None, d.tloustka_mm)
                and prvni_operace in (None, d.prvni_operace)]
    return sorted(nalezene, key=lambda d: d.identifikacni_cislo)[:limit]


def nacti_ciselniky(spoj: Spojeni) -> dict[str, tuple[PolozkaCiselniku, ...]]:
    """Číselníky dílů pro filtry: klíče "materialy", "tloustky", "operace" (i vyřazené položky)."""
    from . import ukazky  # KOSTRA (fáze 0)

    return {typ: tuple(PolozkaCiselniku(p.id, p.kod, p.nazev, p.aktivni) for p in polozky)
            for typ, polozky in ukazky.CISELNIKY.items()}


def zaloz_dil(spoj: Spojeni, kdo: Kontext, dil: NovyDil) -> int:
    """Založí díl v transakci volajícího (migrace) a zapíše audit. Vrací DilID.

    Chyby: ALREADY_EXISTS, NOT_FOUND (neznámý kód číselníku), VALIDATION_ERROR.
    """
    raise NotImplementedError("Ostrov D – fáze 1")
