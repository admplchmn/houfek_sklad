"""Vzorová data ostrova D pro kostru rozhraní, kostru služeb a testy spotřebitelů."""
from __future__ import annotations

from decimal import Decimal

from app.platforma.kontrakty import CiselnikRadek
from app.platforma.kostra import jen_ve_vyvoji
from app.platforma.typy import PotrebaMista

from .kontrakty import DilRadek
from .rozhrani import DilInfo

jen_ve_vyvoji(__name__)  # v provozu vzorová data nikdy (app/platforma/kostra.py)

DIL_AAR10044 = DilInfo(
    dil_id=12, identifikacni_cislo="AAR10044", nazev="Plech boční", material="S235",
    tloustka_mm=Decimal("3.00"), prvni_operace="LASER", standardni_davka_ks=30,
    potreba=PotrebaMista("V1"), vault_url=None, aktivni=True,
)

DIL_BEZ_VELIKOSTI = DilInfo(
    dil_id=13, identifikacni_cislo="CE21RA 10 100194", nazev=None, material="S355",
    tloustka_mm=Decimal("10.00"), prvni_operace="LASER", standardni_davka_ks=None,
    potreba=None, vault_url=None, aktivni=True,
)

VAULT_BX500 = "https://vault.example/BX500-21.pdf"   # vzorový odkaz; skutečný Vault zatím není (příprava)

DIL_BX500 = DilInfo(
    dil_id=14, identifikacni_cislo="BX500-21", nazev="Držák motoru", material="S355",
    tloustka_mm=Decimal("5.00"), prvni_operace="LASER", standardni_davka_ks=20,
    potreba=PotrebaMista("V3"), vault_url=VAULT_BX500, aktivni=True,
)

DIL_INFO = {d.dil_id: d for d in (DIL_AAR10044, DIL_BEZ_VELIKOSTI, DIL_BX500)}

# --- výstupy HTTP (kostra služeb) ----------------------------------------------------------------

# Pořadí ID odpovídá výchozím datům migrace 001 (příloha A).
MATERIALY = [CiselnikRadek(id=i, kod=k, nazev=None, aktivni=True)
             for i, k in enumerate(["S235", "S355", "JRG2C", "POZINK", "1.4301", "ALMG3"], start=1)]
TLOUSTKY = [CiselnikRadek(id=i, kod=k, nazev=None, aktivni=True)
            for i, k in enumerate(["1.00", "1.50", "2.00", "2.50", "3.00", "4.00", "5.00", "6.00", "8.00", "10.00"],
                                  start=1)]
OPERACE = [CiselnikRadek(id=1, kod="LASER", nazev="Laser", aktivni=True),
           CiselnikRadek(id=2, kod="AUTOGEN", nazev="Autogen", aktivni=True),
           CiselnikRadek(id=3, kod="PILA", nazev="Pila", aktivni=True),
           CiselnikRadek(id=4, kod="NAKUP", nazev="Nákup", aktivni=True)]
CISELNIKY = {"materialy": MATERIALY, "tloustky": TLOUSTKY, "operace": OPERACE}

# VelikostPozice patří ostrovu C; ostrov D ji čte z pohledu v_VelikostPozice (ID → kód).
VELIKOSTI = {1: "V1", 2: "V2", 3: "V3", 4: "V4", 5: "V5", 6: "V6"}

DIL_RADEK_AAR10044 = DilRadek(
    dil_id=12, identifikacni_cislo="AAR10044", nazev="Plech boční",
    material_id=1, material="S235", tloustka_id=5, tloustka_mm=Decimal("3.00"),
    prvni_operace_id=1, prvni_operace="LASER", standardni_davka_ks=30,
    velikost_pozice_id=1, velikost="V1", potrebna_delka_mm=None, potrebna_hloubka_mm=None,
    vault_url=None, aktivni=True,
)

DIL_RADEK_CE21RA = DilRadek(
    dil_id=13, identifikacni_cislo="CE21RA 10 100194", nazev=None,
    material_id=2, material="S355", tloustka_id=10, tloustka_mm=Decimal("10.00"),
    prvni_operace_id=1, prvni_operace="LASER", standardni_davka_ks=None,
    velikost_pozice_id=None, velikost=None, potrebna_delka_mm=None, potrebna_hloubka_mm=None,
    vault_url=None, aktivni=True,
)

DIL_RADEK_BX500 = DilRadek(
    dil_id=14, identifikacni_cislo="BX500-21", nazev="Držák motoru",
    material_id=2, material="S355", tloustka_id=7, tloustka_mm=Decimal("5.00"),
    prvni_operace_id=1, prvni_operace="LASER", standardni_davka_ks=20,
    velikost_pozice_id=3, velikost="V3", potrebna_delka_mm=None, potrebna_hloubka_mm=None,
    vault_url=VAULT_BX500, aktivni=True,
)

DIL_RADKY = {d.dil_id: d for d in (DIL_RADEK_AAR10044, DIL_RADEK_CE21RA, DIL_RADEK_BX500)}
