"""HTTP kontrakty ostrova E – Sklad: pohyby a zásoby (sekce 7.5 dokumentu Ostrovy, zadání 21.1.3–21.1.6).

Kontrakt je hotový (fáze 0); služby zatím vracejí vzorová data (KOSTRA). Po zmrazení na
bráně K1 se tu jen přidává (P10).

- Skladové příkazy dědí ze SkladovyVstup (requestId povinný); služby mají @transakce(…, skladova=True).
  Stejný requestId se stejným obsahem vrátí uložený výsledek a nic nezapíše (docs/adr/0004).
- Místa se zadávají kódem ze štítku (`cilKod`, `zdrojKod`: BPLE037-A, BSTAT037-1, i dlouhý tvar);
  rozkládá je ostrov Struktura. `zpusobPotvrzeni` říká, zda byl cíl naskenován (Q-15).
- Výsledek operace nese pohyby, stav zdroje a cíle po operaci, zásobový stav a změnu upozornění.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from app.platforma.chyby import AppError, Chyba
from app.platforma.kontrakty import (
    Cas,
    Duvod,
    FiltrAktivni,
    Kod,
    Ks,
    Parametry,
    SkladovyVstup,
    Strankovani,
    Vstup,
    Vystup,
    Zmena,
)

ZpusobPotvrzeni = Literal["SKEN", "RUCNE"]
StavZasoby = Literal["VYCERPANO", "POD_MINIMEM", "NA_MINIMU", "OK"]
Poznamka = Annotated[str | None, Field(max_length=500)]   # do SkladovyPohyb.Poznamka (NVARCHAR(500))

# --- výstupy ------------------------------------------------------------------------------------


class KandidatRadek(Vystup):
    vnitrni_pozice_id: int
    kod: str                          # barcode cíle "BPLE039-A"
    adresa: str                       # "HOUFEK-PLE-R01-U03-BPLE039-A"
    box_id: int
    kod_boxu: str
    kod_pozice: str
    velikost: str
    uroven_id: int
    regal_id: int
    jiny_regal: bool                  # z jiného regálu pracoviště (vcetneOstatnichRegalu, Q-10)


class PohybRadek(Vystup):
    pohyb_id: int
    typ_pohybu: str                   # PRIJEM | VYDEJ | PRESUN-OUT | PRESUN-IN
    vnitrni_pozice_id: int
    kod: str
    mnozstvi: int                     # podepsaná změna (+ příjem, − výdej)
    stav_pred_ks: int
    stav_po_ks: int


class StavMista(Vystup):
    """Pozice po operaci; barvu boxu z `stavBoxu` a typu boxu určí ostrov Přehledy (kap. 7.2)."""

    vnitrni_pozice_id: int
    kod: str
    adresa: str
    typ_boxu: str
    dil_id: int | None                # None = pozice je po operaci prázdná
    stav_ks: int
    stav_boxu: str                    # VOLNY | OBSAZENY | BLOKOVANY


class SkladovyVysledek(Vystup):
    dil_id: int
    identifikacni_cislo: str
    pocet_ks: int                     # množství operace (kladné)
    pohyby: list[PohybRadek]          # přesun: PRESUN-OUT + PRESUN-IN se stejným transakceId
    zdroj: StavMista | None
    cil: StavMista | None
    stav_zasoby: StavZasoby | None    # STAT místo dílu po operaci (kap. 13); None = díl STAT místo nemá
    upozorneni: Literal["ZALOZENO", "AKTUALIZOVANO", "UZAVRENO"] | None   # změna upozornění (5.8)


class StatMistoRadek(Vystup):
    stat_umisteni_id: int
    dil_id: int
    identifikacni_cislo: str
    vnitrni_pozice_id: int
    kod: str                          # "BSTAT037-1"
    velikost: str
    minimalni_ks: int
    optimalni_ks: int | None
    maximalni_ks: int | None
    stav_ks: int
    stav_zasoby: StavZasoby
    aktivni: bool


class UpozorneniRadek(Vystup):
    upozorneni_id: int
    stat_umisteni_id: int
    dil_id: int
    identifikacni_cislo: str
    kod: str
    typ_stavu: str                    # NA_MINIMU | POD_MINIMEM | VYCERPANO
    stav_upozorneni: str              # OTEVRENE | UZAVRENE
    aktualni_pocet_ks: int            # snímek při vzniku nebo poslední změně typu
    minimalni_pocet_ks: int
    datum_vzniku: Cas
    datum_uzavreni: Cas | None
    poznamka: str | None


# --- čtení ----------------------------------------------------------------------------------------


class KandidatiFiltr(Parametry):
    """Regál zadaný ID nebo naskenovaným kódem (HOUFEK-PLE-R01) – právě jedno z nich."""

    dil_id: int
    regal_id: int | None = None
    kod_regalu: Kod | None = None
    vcetne_ostatnich_regalu: bool = False


class StatMistaFiltr(Strankovani):
    dil_id: int | None = None
    vnitrni_pozice_id: int | None = None
    stav_zasoby: StavZasoby | None = None
    aktivni: FiltrAktivni = True


class UpozorneniFiltr(Strankovani):
    stav: Literal["OTEVRENE", "UZAVRENE"] | None = Field("OTEVRENE", description="Prázdná hodnota = obě")
    dil_id: int | None = None
    typ_stavu: Literal["NA_MINIMU", "POD_MINIMEM", "VYCERPANO"] | None = None


# --- skladové příkazy (requestId) -------------------------------------------------------------------


class PrijemDynVstup(SkladovyVstup):
    dil_id: int
    cil_kod: Kod
    pocet_ks: Ks = Field(..., gt=0)
    zpusob_potvrzeni: ZpusobPotvrzeni = "SKEN"
    poznamka: Poznamka = None


class PrijemStatVstup(SkladovyVstup):
    """Uskladnění do STAT místa dílu (12.5, Q-08): z výroby (bez zdroje) nebo z DYN pozice (celá či část)."""

    dil_id: int
    cil_kod: Kod
    pocet_ks: Ks = Field(..., gt=0)
    zdroj_kod: Kod | None = None
    zpusob_potvrzeni: ZpusobPotvrzeni = "SKEN"
    poznamka: Poznamka = None


class VydejVstup(SkladovyVstup):
    zdroj_kod: Kod
    pocet_ks: Ks = Field(..., gt=0)
    ocekavany_stav_ks: Ks | None = None   # stav, který obsluha viděla; jiný = CONCURRENT_CHANGE
    poznamka: Poznamka = None


class PresunVstup(SkladovyVstup):
    """Přesouvá se vždy celá dávka (18.7): množství se neposílá, poslané pocetKs = WHOLE_BATCH_ONLY."""

    zdroj_kod: Kod
    cil_kod: Kod
    zpusob_potvrzeni: ZpusobPotvrzeni = "SKEN"
    poznamka: Poznamka = None

    @model_validator(mode="before")
    @classmethod
    def _bez_mnozstvi(cls, data: Any) -> Any:
        if isinstance(data, dict) and ("pocetKs" in data or "pocet_ks" in data):
            raise AppError("WHOLE_BATCH_ONLY")   # projde validací beze změny (viz Zmena.NELZE_VYMAZAT)
        return data


# --- STAT místa a upozornění (STAT_EDIT, UPOZORNENI_UZAVRIT) ---------------------------------------------


class NoveStatMistoVstup(Vstup):
    dil_id: int
    vnitrni_pozice_id: int
    minimalni_ks: Ks
    optimalni_ks: Ks | None = None
    maximalni_ks: Ks | None = None
    prepsat_velikost: bool = False    # vědomé přiřazení jiné velikosti (jen TECH/ADMIN s důvodem, Q-05)
    duvod: Duvod | None = None


class ZmenaStatMistaVstup(Zmena):
    """Nové min/opt/max; upozornění se přehodnotí stejnými pravidly (5.8)."""

    NELZE_VYMAZAT = ("minimalni_ks",)

    minimalni_ks: Ks | None = None
    optimalni_ks: Ks | None = None
    maximalni_ks: Ks | None = None


class UzavreniUpozorneniVstup(Vstup):
    poznamka: Duvod                   # ruční uzavření jen s poznámkou (Q-13)


CHYBY = [
    Chyba("POSITION_OCCUPIED", 409, "Cílová DYN pozice už není volná."),
    Chyba("SIZE_MISMATCH", 409, "Velikost pozice neodpovídá dílu."),
    Chyba("WRONG_PART", 409, "Do této statické pozice patří jiný díl."),
    Chyba("INSUFFICIENT_STOCK", 409, "Na pozici není dost kusů."),
    Chyba("WHOLE_BATCH_ONLY", 400, "Přesouvá se vždy celá dávka, množství se neposílá."),
    Chyba("PART_HAS_NO_SIZE", 409, "Díl nemá určenou velikost pozice, do DYN ho nelze zaskladnit."),
]

# Kódy varování v obálce (`varovani[].code`); operaci nezastaví.
VAROVANI_UPOZORNENI = "UPOZORNENI"    # změna minima založila nebo uzavřela upozornění

OPRAVNENI = ["DIL_CIST", "SKLAD_PRIJEM", "SKLAD_VYDEJ", "SKLAD_PRESUN", "STAT_EDIT",
             "UPOZORNENI_UZAVRIT", "RUCNI_POTVRZENI"]

# fáze 3: Příjem DYN (7), Uskladnění STAT (8), Výdej (9), Přesun (10), Upozornění (16), STAT místa (20)
MENU: list = []
