"""HTTP kontrakty ostrova F – Inventura (sekce 7.6 dokumentu Ostrovy, zadání kap. 18 a 21.1.7, analýza 5.11).

Kontrakt je hotový (fáze 0); služby zatím vracejí vzorová data (KOSTRA). Po zmrazení na
bráně K1 se tu jen přidává (P10).

- Slepá inventura: u nezapsané položky se očekávaný díl a počet nevracejí (null), ukážou se až po zápisu.
- Dokončení je skladový příkaz (requestId, oprávnění KOREKCE): všechny rozdíly zaúčtuje v jedné
  transakci pohyby INVENTURA; nikdy tichým přepisem.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from app.platforma.chyby import Chyba
from app.platforma.kontrakty import Cas, Kod, Ks, SkladovyVstup, Strankovani, Vstup, Vystup

TypRozsahu = Literal["FULL", "PRAC", "REGAL", "UROVEN", "BOX", "POZICE"]
StavInventury = Literal["ROZPRACOVANA", "DOKONCENA", "ZRUSENA"]
Poznamka = Annotated[str | None, Field(max_length=500)]

# --- výstupy ------------------------------------------------------------------------------------


class InventuraRadek(Vystup):
    inventura_id: int
    typ_rozsahu: TypRozsahu
    cil_id: int | None                 # ID pracoviště / regálu / úrovně / boxu / pozice podle rozsahu; FULL = null
    stav_inventury: StavInventury
    slepa: bool
    datum_zahajeni: Cas
    datum_dokonceni: Cas | None
    zalozil_uzivatel_id: int
    pocet_polozek: int
    pocet_zapsanych: int
    pocet_k_prepoctu: int
    poznamka: str | None


class PolozkaInventury(Vystup):
    vnitrni_pozice_id: int
    kod: str                           # štítek pozice, který obsluha skenuje
    typ_boxu: str
    stav_polozky: Literal["CEKA", "ZAPSANO", "PREPOCITAT"]
    ocekavany_dil_id: int | None       # slepá inventura: null, dokud není zapsáno
    ocekavany_pocet_ks: int | None
    skutecny_dil_id: int | None        # null = zapsáno „prázdné“ (nebo ještě nezapsáno)
    skutecny_pocet_ks: int | None
    rozdil_ks: int | None              # skutečný − očekávaný počet
    vyhodnoceni: Literal["SHODA", "ROZDIL", "JINY_DIL"] | None
    datum_kontroly: Cas | None


class InventuraDetail(InventuraRadek):
    polozky: list[PolozkaInventury]


class DokonceniVysledek(Vystup):
    inventura_id: int
    pocet_shod: int
    pocet_rozdilu: int
    pocet_jinych_dilu: int
    pohyby: list[int]                  # PohybID korekčních pohybů INVENTURA (21.1.7 „Výstup“)


# --- vstupy ------------------------------------------------------------------------------------


class InventuryFiltr(Strankovani):
    stav: StavInventury | None = Field("ROZPRACOVANA", description="Prázdná hodnota = všechny")


class NovaInventuraVstup(Vstup):
    """Založí položky pro všechny aktivní pozice v rozsahu, i prázdné, se snímkem očekávaného stavu."""

    typ_rozsahu: TypRozsahu
    cil_id: int | None = None
    slepa: bool = True
    poznamka: Poznamka = None


class ZapisPolozkyVstup(Vstup):
    """Co obsluha našla: díl a počet, nebo „prázdné“ (bez dílu, 0 ks). Zápis jde opakovat (přepočet)."""

    skutecny_dil_id: int | None = None
    skutecny_pocet_ks: Ks


class DokonceniVstup(SkladovyVstup):
    """`cileJinyDil`: kam zaúčtovat jiný díl nalezený na STAT pozici – {"501": "BPLE039-A"} (Q-17)."""

    cile_jiny_dil: dict[int, Kod] = Field(default_factory=dict, max_length=1000)
    poznamka: Poznamka = None


CHYBY = [
    Chyba("INVENTORY_RECOUNT", 409, "Pozici je nutné přepočítat, od zápisu se změnil stav."),
]

OPRAVNENI = ["INVENTURA", "KOREKCE"]

MENU: list = []   # fáze 3: Inventura – seznam, počítání, dokončení (11–13)
