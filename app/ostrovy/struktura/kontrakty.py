"""HTTP kontrakty ostrova C – Struktura skladu a kódy (sekce 7.3 dokumentu Ostrovy, analýza 9.4 a 9.7).

Kontrakt je hotový (fáze 0); služby zatím vracejí vzorová data (KOSTRA). Po zmrazení na
bráně K1 se tu jen přidává (P10).

- Odkazy na objekty jsou ID (`urovenId`, `cleneniId`); typ boxu je technický kód DYN | STAT (4.2).
- Kódy pracoviště, regálu a úrovně jsou součástí barcode (DYN kód boxu, FullBoxKlic), proto se po
  založení nemění – PATCH mění jen popisné údaje. Změna kódu by znamenala přetisk všech štítků
  a přepočet adres; ve fázi 0 se nepodporuje (otevřený bod pro vlastníka procesu).
- Box se mění jen řízenými operacemi POST /boxy/{id}/{akce} (analýza 9.7), nikdy obecným PATCH.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.platforma.chyby import Chyba
from app.platforma.kontrakty import Duvod, FiltrAktivni, Kod, Mm, Parametry, SkladovyVstup, Vstup, Vystup, Zmena

TypBoxu = Literal["DYN", "STAT"]

# --- výstupy ------------------------------------------------------------------------------------


class PracovisteRadek(Vystup):
    pracoviste_id: int
    kod_pracoviste: str              # "PLE" – část DYN kódu boxu (BPLE037)
    nazev: str | None
    aktivni: bool


class RegalRadek(Vystup):
    regal_id: int
    pracoviste_id: int
    kod_pracoviste: str
    kod_regalu: str                  # "R01"
    kod: str                         # barcode regálu "HOUFEK-PLE-R01" (hledání kandidátů, kap. 11)
    nazev: str | None
    aktivni: bool


class UrovenRadek(Vystup):
    uroven_id: int
    regal_id: int
    kod_urovne: str                  # "U03"
    poradi: int                      # svislé pořadí
    delka_plochy_mm: Mm              # jen informace; SVG se počítá z boxů (17.1)
    hloubka_plochy_mm: Mm
    pocet_boxu: int                  # aktivní boxy na úrovni
    aktivni: bool


class BoxNaUrovni(Vystup):
    """Box v pořadí zleva doprava (Pozice P01…Pn, kap. 6)."""

    box_id: int
    kod_boxu: str
    typ_boxu: TypBoxu
    kod_cleneni: str
    poradi: int
    kod_pozice_urovne: str           # "P01"
    blokovany: bool


class VnitrniPoziceRadek(Vystup):
    vnitrni_pozice_id: int
    kod_pozice: str                  # DYN "A" … "R" včetně "CH", STAT "1" … "n"
    kod: str                         # barcode pozice "BPLE037-A" (Q-02)
    velikost: str                    # "V1" … "V6"
    poradi_v_boxu: int               # pořadí kandidátů podle šablony (česká abeceda DYN kódu)
    rozmer_c7_delka_mm: Mm | None    # aktuální rozměr C7, jen u V6 (Q-01)
    rozmer_c7_hloubka_mm: Mm | None
    blokovana: bool                  # vlastní blokace pozice; blokaci celého boxu nese box


class BoxDetail(Vystup):
    """Struktura boxu bez obsahu. Obsah a barvu vrací ostrov Přehledy (/api/prehledy)."""

    box_id: int
    kod_boxu: str                    # "BPLE037" / "BSTAT037" – trvalá identita na štítku
    typ_boxu: TypBoxu
    cleneni_id: int
    kod_cleneni: str                 # "C1" … "C7"
    delka_mm: Mm
    hloubka_mm: Mm
    full_box_klic: str               # "HOUFEK-PLE-R01-U03-BPLE037" – uložená adresa (Q-03)
    blokovany: bool
    aktivni: bool
    poradi: int                      # pořadí na úrovni zleva
    kod_pozice_urovne: str           # "P01"
    uroven_id: int
    kod_urovne: str
    regal_id: int
    kod_regalu: str
    pracoviste_id: int
    kod_pracoviste: str
    pozice: list[VnitrniPoziceRadek]


class VnitrniPoziceDetail(VnitrniPoziceRadek):
    blokovano: bool                  # skutečný stav pro sklad: blokovaný box NEBO pozice
    adresa: str                      # "HOUFEK-PLE-R01-U03-BPLE037-A"
    box_id: int
    kod_boxu: str
    typ_boxu: TypBoxu
    kod_cleneni: str
    box_blokovany: bool
    uroven_id: int
    regal_id: int
    pracoviste_id: int
    kod_pracoviste: str


class SablonaPozice(Vystup):
    """Přihrádka šablony členění (SablonaCleneni, Q-06); geometrie jako podíl rozměru boxu (0–1)."""

    dyn_kod: str
    stat_kod: str
    poradi: int
    rada: int                        # 1 = zadní řada (nejdál od hlavního štítku boxu)
    sloupec: int                     # 1 = vlevo
    velikost: str
    rel_x: float
    rel_y: float
    rel_sirka: float
    rel_hloubka: float


class CleneniRadek(Vystup):
    cleneni_id: int
    kod_cleneni: str
    pocet_pozic: int
    pozice: list[SablonaPozice]


class BlokaceVysledek(Vystup):
    typ: Literal["BOX", "POZICE"]
    kod: str                         # krátký kód objektu: "BPLE037" nebo "BPLE037-A"
    box_id: int
    vnitrni_pozice_id: int | None    # None u blokace celého boxu
    blokovano: bool                  # nový stav objektu
    zmeneno: bool                    # False = objekt už byl v požadovaném stavu (varování BEZ_ZMENY)


# --- čtení (DIL_CIST) ---------------------------------------------------------------------------

class PracovisteFiltr(Parametry):
    aktivni: FiltrAktivni = True


class RegalyFiltr(Parametry):
    pracoviste_id: int | None = None
    aktivni: FiltrAktivni = True


class UrovneFiltr(Parametry):
    regal_id: int                    # povinný – úrovně se procházejí po regálech
    aktivni: FiltrAktivni = True


# --- blokace (BLOKACE, skladový příkaz s requestId) ------------------------------------------------


class BlokaceVstup(SkladovyVstup):
    """Blokace nebo odblokování celého boxu (BPLE037) či jedné pozice (BPLE037-A), i dlouhým kódem."""

    kod: Kod
    blokovat: bool
    duvod: Duvod                     # do AuditZmen; tabulky údaje o blokaci zatím nemají (brána G2)


# --- správa pracovišť, regálů a úrovní (BOX_EDIT) ---------------------------------------------------


class NovePracovisteVstup(Vstup):
    kod_pracoviste: str = Field(..., min_length=1, max_length=20)   # normalizuje se na 3 znaky (domena)
    nazev: str | None = Field(None, max_length=100)


class ZmenaPracovisteVstup(Zmena):
    nazev: str | None = Field(None, max_length=100)


class NovyRegalVstup(Vstup):
    pracoviste_id: int
    kod_regalu: str = Field(..., min_length=1, max_length=20)       # "r1" → "R01"
    nazev: str | None = Field(None, max_length=100)


class ZmenaRegaluVstup(Zmena):
    nazev: str | None = Field(None, max_length=100)


class NovaUrovenVstup(Vstup):
    regal_id: int
    kod_urovne: str = Field(..., min_length=1, max_length=20)       # "u3" → "U03"
    poradi: int | None = Field(None, ge=0, le=999)                 # None = číslo z kódu (U03 → 3)
    delka_plochy_mm: Mm = Field(..., gt=0)
    hloubka_plochy_mm: Mm = Field(..., gt=0)


class ZmenaUrovneVstup(Zmena):
    NELZE_VYMAZAT = ("poradi", "delka_plochy_mm", "hloubka_plochy_mm")

    poradi: int | None = Field(None, ge=0, le=999)
    delka_plochy_mm: Mm | None = Field(None, gt=0)
    hloubka_plochy_mm: Mm | None = Field(None, gt=0)


# --- operace s boxem (BOX_EDIT, analýza 9.7) ----------------------------------------------------------


class NovyBoxVstup(Vstup):
    """Přidá box na úroveň: Pozice + Box + vnitřní pozice ze šablony v jedné transakci."""

    poradi: int | None = Field(None, ge=1)                          # None = na konec úrovně
    typ_boxu: TypBoxu
    cleneni_id: int
    delka_mm: Mm = Field(..., gt=0)
    hloubka_mm: Mm = Field(..., gt=0)
    cislo_boxu: int | None = Field(None, ge=1, le=999)             # None = další číslo řady (11.2.1)


class VymenaBoxuVstup(Vstup):
    """Nový box na stejné Pozici (stejné PoziceID); starý musí být prázdný a vyřadí se."""

    typ_boxu: TypBoxu
    cleneni_id: int
    delka_mm: Mm = Field(..., gt=0)
    hloubka_mm: Mm = Field(..., gt=0)
    cislo_boxu: int | None = Field(None, ge=1, le=999)
    duvod: Duvod


class PresunBoxuVstup(Vstup):
    """Box i s obsahem na jinou úroveň (bez skladového pohybu); DYN jen v rámci pracoviště (Q-30)."""

    cil_uroven_id: int
    poradi: int | None = Field(None, ge=1)                          # None = na konec cílové úrovně
    duvod: Duvod


class PoradiBoxuVstup(Vstup):
    nove_poradi: int = Field(..., ge=1)
    duvod: Duvod


class RekonfiguraceVstup(Vstup):
    """Nové členění prázdného boxu bez STAT přiřazení (Q-27, otevřený bod A-14)."""

    cleneni_id: int
    duvod: Duvod


class RozmerC7Vstup(Vstup):
    delka_mm: Mm = Field(..., gt=0)
    hloubka_mm: Mm = Field(..., gt=0)
    duvod: Duvod


CHYBY = [
    Chyba("INVALID_BARCODE", 400, "Kód neodpovídá žádnému kódu skladu."),
    Chyba("WRONG_SCAN_LEVEL", 400, "Naskenujte štítek pozice, ne celý box."),
    Chyba("BOX_SERIES_FULL", 409, "Řada čísel boxů je vyčerpaná."),
]

# Kódy varování v obálce (`varovani[].code`); operaci nezastaví.
VAROVANI_BEZ_ZMENY = "BEZ_ZMENY"     # blokace: objekt už byl v požadovaném stavu

OPRAVNENI = ["DIL_CIST", "BLOKACE", "BOX_EDIT"]

MENU: list = []   # fáze 3: Detail boxu a pozice (6), Struktura (19), Štítky (23)
