"""HTTP kontrakty ostrova D – Díly a číselníky (sekce 7.4 dokumentu Ostrovy, analýza 9.3 a 9.7).

Kontrakt je hotový (fáze 0); služby zatím vracejí vzorová data (KOSTRA). Po zmrazení na
bráně K1 se tu jen přidává (P10). Odkazy na číselníky jsou ID (`materialId` …), ne kódy.
"""
from __future__ import annotations

from pydantic import Field

from app.platforma.chyby import Chyba
from app.platforma.kontrakty import Duvod, FiltrAktivni, Ks, Mm, Strankovani, Vstup, Vystup, Zmena

# --- výstupy ------------------------------------------------------------------------------------


class DilRadek(Vystup):
    """Díl s kódy číselníků. Velikost None = díl nejde do DYN (Q-26)."""

    dil_id: int
    identifikacni_cislo: str                 # "CE21RA 10 100194" – není barcode (kap. 11)
    nazev: str | None
    material_id: int | None
    material: str | None                     # kód, např. "S235"
    tloustka_id: int | None
    tloustka_mm: Mm | None
    prvni_operace_id: int | None
    prvni_operace: str | None                # kód, např. "LASER"
    standardni_davka_ks: int | None
    velikost_pozice_id: int | None
    velikost: str | None                     # "V1" … "V6"
    potrebna_delka_mm: Mm | None             # jen V6 (Q-01)
    potrebna_hloubka_mm: Mm | None
    vault_url: str | None                    # Vault zatím jen připraveno
    aktivni: bool
    poznamka: str | None = None              # pokyn pro obsluhu, např. ze sloupce JINÉ INFORMACE v XLSM


# --- čtení --------------------------------------------------------------------------------------


class DilyFiltr(Strankovani):
    hledat: str | None = Field(None, max_length=80, description="Část identifikačního čísla nebo názvu")
    material_id: int | None = None
    tloustka_id: int | None = None
    prvni_operace_id: int | None = None
    velikost_pozice_id: int | None = None
    aktivni: FiltrAktivni = True


TYPY_CISELNIKU: tuple[str, ...] = ("materialy", "tloustky", "operace")   # {typ} v /ciselniky/{typ}

# --- zápis (KMEN_EDIT) ------------------------------------------------------------------------


class NovyDilVstup(Vstup):
    identifikacni_cislo: str = Field(..., min_length=1, max_length=80)   # normalizuje se (rozhrani)
    nazev: str | None = Field(None, max_length=200)
    material_id: int | None = None
    tloustka_id: int | None = None
    prvni_operace_id: int | None = None
    standardni_davka_ks: Ks | None = Field(None, gt=0)
    velikost_pozice_id: int | None = None
    potrebna_delka_mm: Mm | None = Field(None, gt=0)    # povinné jen u V6, jinak se neposílá
    potrebna_hloubka_mm: Mm | None = Field(None, gt=0)
    vault_url: str | None = Field(None, max_length=1000)
    poznamka: str | None = Field(None, max_length=500)


class ZmenaDiluVstup(Zmena):
    """Změna kmenových údajů. Identifikační číslo se nemění (jiné číslo = nový díl),
    velikost se mění zvlášť přes PATCH /{id}/velikost (Q-28)."""

    nazev: str | None = Field(None, max_length=200)
    material_id: int | None = None
    tloustka_id: int | None = None
    prvni_operace_id: int | None = None
    standardni_davka_ks: Ks | None = Field(None, gt=0)
    vault_url: str | None = Field(None, max_length=1000)
    poznamka: str | None = Field(None, max_length=500)


class ZmenaVelikostiVstup(Vstup):
    """Nová velikost pozice dílu (celý stav, ne jen změna). Zakázáno, dokud má díl obsah v DYN (Q-28)."""

    velikost_pozice_id: int | None
    potrebna_delka_mm: Mm | None = Field(None, gt=0)
    potrebna_hloubka_mm: Mm | None = Field(None, gt=0)
    duvod: Duvod


class NovyCiselnikVstup(Vstup):
    """materialy: kód (např. S235) · tloustky: kód = tloušťka v mm (např. 3.00) · operace: kód + název."""

    kod: str = Field(..., min_length=1, max_length=30)
    nazev: str | None = Field(None, max_length=100)


class ZmenaCiselnikuVstup(Zmena):
    NELZE_VYMAZAT = ("kod",)

    kod: str | None = Field(None, min_length=1, max_length=30)
    nazev: str | None = Field(None, max_length=100)


CHYBY: list[Chyba] = []   # ostrov používá jen kódy Platformy (ALREADY_EXISTS, NOT_EMPTY, NOT_FOUND …)

OPRAVNENI = ["DIL_CIST", "KMEN_EDIT"]

MENU: list = []   # fáze 3: Kmenová data (obrazovka 18)
