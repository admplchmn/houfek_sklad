"""HTTP kontrakty ostrova G – Přehledy a navigace (sekce 7.7 dokumentu Ostrovy, zadání kap. 13.1, 14–17, 21.1.2).

Kontrakt je hotový (fáze 0); služby skládají vzorová data ostrovů B–E přes jejich rozhraní (KOSTRA).
Po zmrazení na bráně K1 se tu jen přidává (P10). Ostrov jen čte – žádný endpoint nic nezapisuje.

- Každý výsledek, který má místo ve skladu, nese `zvyrazneni` (regál → úroveň → box → pozice),
  aby UI hned přepnulo SVG na správnou úroveň a zvýraznilo místo (kap. 16).
- Barva boxu je technický kód (CERVENA, ZELENA, MODRA, SEDA); CSS ho převede (zadání 7.2, 17.1).
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from pydantic import Field

from app.platforma.kontrakty import Cas, CiselnikRadek, Kod, Mm, Parametry, Strankovani, Vystup

StavZasoby = Literal["OK", "NA_MINIMU", "POD_MINIMEM", "VYCERPANO"]

# --- sken a hledání (kap. 16, 21.1.2) --------------------------------------------------------------


class Zvyrazneni(Vystup):
    """Kam přepnout SVG a co zvýraznit: úroveň → box → konkrétní přihrádka."""

    regal_id: int
    uroven_id: int | None
    box_id: int | None
    vnitrni_pozice_id: int | None


class ObsahNaPozici(Vystup):
    """Díl a stav na naskenované pozici – obsluha je vidí před zadáním množství (12.2)."""

    dil_id: int
    identifikacni_cislo: str
    pocet_ks: int


class VysledekHledani(Vystup):
    typ: Literal["DIL", "REGAL", "BOX", "POZICE"]
    id: int                           # DilID | RegalID | BoxID | VnitrniPoziceID podle typu
    kod: str                          # identifikační číslo dílu nebo kód ze štítku
    popis: str | None                 # název dílu nebo typ a členění boxu
    adresa: str | None                # fyzická adresa místa (u dílu jeho první umístění)
    zvyrazneni: Zvyrazneni | None     # None = díl nikde neleží
    obsah: ObsahNaPozici | None       # jen typ POZICE s obsahem (12.2); prázdná pozice a ostatní typy None


class Vysledky(Vystup):
    polozky: list[VysledekHledani]
    presny: bool                      # True = kód skladu nebo přesné číslo dílu → UI otevře rovnou detail


class HledaniFiltr(Parametry):
    q: str = Field(..., min_length=1, max_length=150, description="Kód ze štítku, číslo nebo název dílu")
    pracoviste_id: int | None = None
    material_id: int | None = None
    tloustka_id: int | None = None
    prvni_operace_id: int | None = None
    typ_boxu: Literal["DYN", "STAT"] | None = None
    stav_zasoby: StavZasoby | None = None


# --- SVG úrovně (kap. 17) ---------------------------------------------------------------------------


class PoziceSvg(Vystup):
    vnitrni_pozice_id: int
    kod_pozice: str
    kod: str                          # "BPLE037-A"
    velikost: str
    blokovana: bool
    rel_x: float                      # poloha přihrádky v boxu (0–1, šablona členění)
    rel_y: float
    rel_sirka: float
    rel_hloubka: float
    dil_id: int | None
    identifikacni_cislo: str | None
    pocet_ks: int
    vault_url: str | None             # odkaz na výkres v popupu pozice (kap. 17); None = nepřiřazen


class BoxSvg(Vystup):
    box_id: int
    kod_boxu: str
    typ_boxu: str
    kod_cleneni: str
    stav_boxu: str                    # VOLNY | OBSAZENY | BLOKOVANY
    barva: str                        # CERVENA | ZELENA | MODRA | SEDA (zadání 7.2, 17.1)
    x_mm: float
    y_mm: float
    delka_mm: float
    hloubka_mm: float
    pozice: list[PoziceSvg]
    kod_pozice_urovne: str            # "P01" – Pozice boxu na úrovni, pořadí zleva doprava (17.2)


class RozlozeniVystup(Vystup):
    uroven_id: int
    kod_urovne: str
    regal_id: int
    kod_regalu: str
    pracoviste: str
    delka_plochy_mm: float            # informační text, neurčuje velikost SVG (17.1)
    hloubka_plochy_mm: float
    sirka_svg_mm: float               # viewBox = 0 0 sirka vyska
    vyska_svg_mm: float
    boxy: list[BoxSvg]


# --- karta dílu (kap. 15) ---------------------------------------------------------------------------


class UmisteniDilu(Vystup):
    vnitrni_pozice_id: int
    kod: str
    adresa: str
    typ_boxu: str
    pocet_ks: int
    zvyrazneni: Zvyrazneni


class StatZasoba(Vystup):
    stat_umisteni_id: int
    kod: str
    minimalni_ks: int
    optimalni_ks: int | None
    maximalni_ks: int | None
    stav_ks: int
    stav_zasoby: StavZasoby
    kod_boxu: str                     # "BSTAT037" – karta dílu ukazuje STAT místo kódem boxu (kap. 15)
    chybi_do_maxima_ks: int | None    # max(0, Maximum − stav) jako v kap. 14; None = bez maxima


class PohybHistorie(Vystup):
    pohyb_id: int
    datum_cas: Cas
    typ_pohybu: str
    dil_id: int
    identifikacni_cislo: str | None
    vnitrni_pozice_id: int
    kod: str | None                   # kód pozice (u vyřazené pozice None)
    mnozstvi: int
    stav_pred_ks: int
    stav_po_ks: int
    uzivatel_id: int
    cele_jmeno: str | None
    terminal_id: int | None
    skladova_transakce_id: uuid.UUID | None   # společné pro PRESUN-OUT + PRESUN-IN; detail /transakce/{id}
    poznamka: str | None


class KartaDilu(Vystup):
    dil_id: int
    identifikacni_cislo: str
    nazev: str | None
    material: str | None
    tloustka_mm: Mm | None
    prvni_operace: str | None
    standardni_davka_ks: int | None
    velikost: str | None
    vault_url: str | None             # null → UI zobrazí „Výkres ve Vaultu není přiřazen“ (kap. 15)
    stat: StatZasoba | None
    dyn_ks: int                       # rozpracovaná zásoba v DYN
    celkem_ks: int
    umisteni: list[UmisteniDilu]      # STAT první, pak DYN podle čísla boxu
    posledni_pohyby: list[PohybHistorie]


# --- monitoring a laser (kap. 13.1, 14) --------------------------------------------------------------


class SouhrnZasob(Vystup):
    sledovane: int
    ok: int
    na_minimu: int
    pod_minimem: int
    vycerpano: int


class ZasobaRadek(Vystup):
    dil_id: int
    identifikacni_cislo: str
    nazev: str | None
    material: str | None
    tloustka_mm: Mm | None
    prvni_operace: str | None
    stat_ks: int
    dyn_ks: int
    celkem_ks: int
    minimalni_ks: int | None          # None = díl bez aktivního STAT místa (jen při jenSeStat=false)
    maximalni_ks: int | None
    stav_zasoby: StavZasoby | None    # podle STAT (kap. 13); None = díl bez STAT místa
    umisteni: str                     # "STAT + 2× DYN"
    zvyrazneni: Zvyrazneni            # STAT místo dílu, bez STAT jeho první místo
    mista: list[UmisteniDilu]         # každé umístění zvlášť – klik vykreslí jeho úroveň a zvýrazní ho (13.1)


class ZasobyVystup(Vystup):
    souhrn: SouhrnZasob               # vždy za všechny sledované díly podle filtru, bez stránkování
    polozky: list[ZasobaRadek]
    strana: int
    velikost: int
    celkem: int


class ZasobyFiltr(Strankovani):
    pracoviste_id: int | None = None
    prvni_operace_id: int | None = None
    material_id: int | None = None
    tloustka_id: int | None = None
    stav_zasoby: StavZasoby | None = None
    jen_problemove: bool = False      # jedním kliknutím jen NA_MINIMU, POD_MINIMEM, VYCERPANO (13.1)
    jen_se_stat: bool = True          # jen díly s aktivním STAT místem (13.1); false = i díly jen v DYN


class LaserRadek(Vystup):
    dil_id: int
    identifikacni_cislo: str
    material: str | None
    tloustka_mm: Mm | None
    prvni_operace: str | None
    stat_ks: int
    dyn_ks: int
    maximalni_ks: int
    chybi_ve_stat_ks: int             # max(0, Maximum − STAT) – kap. 14
    doporuceno_ks: int                # Q-22: zaokrouhleno nahoru na standardní dávku
    standardni_davka_ks: int | None


class LaserFiltr(Strankovani):
    prvni_operace_id: int | None = Field(None, description="Prázdné = operace s kódem LASER")
    material_id: int | None = None
    tloustka_id: int | None = None
    jen_pod_maximem: bool = True
    odecitat_dyn: bool = True         # Q-22 rozhodnuto 9. 11.


# --- historie (kap. 9, 17 obrazovka 17) -----------------------------------------------------------------


class PohybyFiltr(Strankovani):
    dil_id: int | None = None
    vnitrni_pozice_id: int | None = None
    kod: Kod | None = None            # naskenovaný kód pozice místo ID
    typ_pohybu: str | None = Field(None, max_length=30)
    uzivatel_id: int | None = None
    od: date | None = None
    do: date | None = None


class TransakceDetail(Vystup):
    """Hlavička skladové transakce a její pohyby. (`transakceId` v obálce GET je vždy null – nic se nezapsalo.)"""

    skladova_transakce_id: uuid.UUID
    typ_operace: str                  # PRIJEM_DYN | PRIJEM_STAT | VYDEJ | PRESUN | BLOKACE | INVENTURA_DOKONCENI
    datum_cas: Cas
    uzivatel_id: int
    cele_jmeno: str | None
    terminal_id: int | None
    pohyby: list[PohybHistorie]


# --- číselníky pro filtry ---------------------------------------------------------------------------


class CiselnikyVystup(Vystup):
    pracoviste: list[CiselnikRadek]
    velikosti: list[CiselnikRadek]
    materialy: list[CiselnikRadek]
    tloustky: list[CiselnikRadek]
    operace: list[CiselnikRadek]
    typy_pohybu: list[CiselnikRadek]
    typy_boxu: list[str]
    stavy_zasoby: list[str]


CHYBY: list = []   # jen kódy Platformy a ostrovů, ze kterých čte (NOT_FOUND, INVALID_BARCODE …)

OPRAVNENI = ["DIL_CIST"]

# fáze 3: Sken a hledání (3), Úroveň SVG (4), Karta dílu (5), Monitoring (14), Laser (15), Historie (17)
MENU: list = []
