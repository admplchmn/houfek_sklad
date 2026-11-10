"""Čistá pravidla migrace: normalizace a validace hodnot z XLSM (docs/migrace-xlsm.md, sekce 2 a 3).

Mapování sloupců listu `Databáze` je tu jako konstanta, protože report i import (krok 2) čtou týž
list. Převody, které znají jen vlastníci databáze (formát kódu boxu, délka čísla dílu), zde nejsou –
ty ověřuje rozhraní ostrova C a D až při zakládání.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from app.ostrovy.dily import rozhrani as dily

LIST_DABAZE = "Databáze"        # list s tabulkou DatabazeTabulka (sekce 1)

# klíč reportu → název sloupce ve XLSM (sekce 2); FULL_BOX_KLÍČ se počítá z kódu, nečte se
SLOUPCE = {
    "pracoviste": "PRACOVIŠTĚ",
    "regal": "REGÁL",
    "uroven": "ÚROVEŇ",
    "pozice": "POZICE",
    "box_id": "BOX_ID",
    "stav_boxu": "STAV_BOXU",
    "cislo_dilu": "IDENTIFIKAČNÍ_ČÍSLO",
    "minimum": "MINIMÁLNÍ POČET KUSŮ V BOXU",
    "jine_informace": "JINÉ INFORMACE",
    "vault": "VAULT PDF",
    "delka_mm": "DÉLKA_BOXU_(mm)",
    "hloubka_mm": "HLOUBKA_BOXU_(mm)",
}

# Řádek hlavičky obsahuje oba tyto názvy (sekce 2); report podle nich hlavičku najde.
HLAVICKA = ("box_id", "cislo_dilu")

VOLNY_BOX = "Volný box."        # box bez dílu (sekce 2)
VOLNY_SLOT = "Volný slot."      # prázdná přihrádka v boxu s více přihrádkami

# STAV_BOXU (list Nápověda, sekce 1). D-06: BLOK a MULTI se při importu něčeho týkají, 0 a kódy
# dílů se nepřevádějí – barvu počítá systém z typu, obsahu a blokace (kap. 7.2).
STAVY_BEZ_PREVODU = ("0", "OPER", "MEOP", "POL")
STAV_BLOK = "BLOK"
STAV_MULTI = "MULTI"


def text_bunky(hodnota: Any) -> str:
    """Text buňky pro stg.Bunka: Excel uloží i celá čísla jako 300.0, do stagingu patří „300“."""
    if isinstance(hodnota, float) and hodnota.is_integer():
        return str(int(hodnota))
    return str(hodnota)


def kod_na_tri_cislice(kod: str) -> str:
    """Kód boxu na tři číslice: BPLE01 → BPLE001 (D-02). Jiný tvar vrátí beze změny, ozve se report."""
    text = dily.normalizuj_identifikacni_cislo(kod)
    nalez = re.fullmatch(r"(\D+)(\d{1,2})", text)
    return f"{nalez[1]}{int(nalez[2]):03d}" if nalez else text


def neni_dil(identifikacni_cislo: str) -> bool:
    """„Volný box.“ je box bez dílu a „Volný slot.“ prázdná přihrádka; ani jedno není díl (sekce 2)."""
    return dily.normalizuj_identifikacni_cislo(identifikacni_cislo) in {
        dily.normalizuj_identifikacni_cislo(VOLNY_BOX), dily.normalizuj_identifikacni_cislo(VOLNY_SLOT)}


def je_rozmer(text: str) -> bool:
    """Rozměr v mm zadaný jako číslo (celé, nebo s tečkou či čárkou)."""
    return bool(re.fullmatch(r"\d+([.,]\d+)?", text.strip()))


def minimum_a_poznamka(minimum: str | None, jine_informace: str | None) -> tuple[int | None, str | None]:
    """Minimum je první číslo textu („50 kusů (1 kus na stroj)“ → 50) a poznámka text v závorce
    plus JINÉ INFORMACE (sekce 2); chybějící údaj je None."""
    text = (minimum or "").strip()
    cislo = re.search(r"\d+", text)
    zavorka = re.search(r"\(([^)]*)\)", text)
    dilove = [hodnota for hodnota in (zavorka[1].strip() if zavorka else "", (jine_informace or "").strip())
              if hodnota]
    return (int(cislo[0]) if cislo else None), ("; ".join(dilove) or None)


def vyznam_stavu(stav_boxu: str) -> str | None:
    """Význam STAV_BOXU, který se při importu něčeho týká (D-06): BLOK blokuje box, MULTI je box
    s více přihrádkami, jejichž členění nastaví sklad. Ostatní – 0, OPER, MEOP, POL, neznámá i
    prázdná hodnota – vracejí None."""
    kod = dily.normalizuj_identifikacni_cislo(stav_boxu)
    if kod == STAV_BLOK:
        return "STAV_BOXU BLOK – box bude blokovaný"
    if kod == STAV_MULTI:
        return "STAV_BOXU MULTI – box s více přihrádkami, členění nastaví sklad"
    return None


def navrh_cleneni(pocet_dilu: int) -> str | None:
    """Návrh členění pro box s více díly (sekce 3.2); C5 jen u dlouhého boxu, to posoudí sklad.
    Počty bez vodítka vracejí None a členění volí sklad."""
    return {2: "C2 nebo C5", 3: "C3", 4: "C4", 6: "C6"}.get(pocet_dilu)


def vault_server(odkaz: str) -> str:
    """Server z odkazu do Vaultu – krátký název i plný (sekce 3.5); prázdný odkaz vrací prázdný řetězec."""
    text = odkaz.strip()
    if not text:
        return ""
    return (urlsplit(text if "//" in text else f"//{text}").hostname or "").lower()
