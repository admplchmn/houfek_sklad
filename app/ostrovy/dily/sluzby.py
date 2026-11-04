"""Služby ostrova D – Díly a číselníky. Jedna operace = @transakce, čtení = @cteni.

Fáze 1: SQL je v `repozitar.py`. Zásah do kmenových dat vždy zapíše AuditZmen
(`app.platforma.audit.zapis`): jeden řádek na jedno pole, `Pole` = název sloupce,
důvod z vstupu jde do `Poznamka`. Založení dílu je jeden řádek „sloupec vznikl“
(IdentifikacniCislo z NULL na číslo), u kterého důvod klient neposílá.
"""
from __future__ import annotations

from typing import Any

from app.platforma.audit import zapis
from app.platforma.chyby import AppError
from app.platforma.db import Spojeni, cteni
from app.platforma.kontrakty import CiselnikRadek, DuvodVstup, Seznam, Strana
from app.platforma.transakce import transakce
from app.platforma.typy import Kontext

from . import domena, repozitar
from .kontrakty import (
    TYPY_CISELNIKU,
    DilRadek,
    DilyFiltr,
    NovyCiselnikVstup,
    NovyDilVstup,
    ZmenaCiselnikuVstup,
    ZmenaDiluVstup,
    ZmenaVelikostiVstup,
)
from .rozhrani import normalizuj_identifikacni_cislo

# Pole kontraktu → sloupec tabulky Dil (název sloupce se píše do AuditZmen.Pole).
_DIL_SLOUPCE = {"nazev": "NazevDilu", "material_id": "MaterialID", "tloustka_id": "TloustkaID",
                "prvni_operace_id": "PrvniOperaceID", "standardni_davka_ks": "StandardniDavkaKs",
                "vault_url": "VaultVykresURL", "poznamka": "Poznamka"}
# Pole s ID položky → typ číselníku; cizí klíč ověřuje aplikace, aby přišel NOT_FOUND, ne chyba SQL.
_DIL_CISELNIK = {"material_id": "materialy", "tloustka_id": "tloustky", "prvni_operace_id": "operace"}
# Položky číselníků se auditují pod TypObjektu podle názvu vlastní tabulky (jako DIL, BOX …).
_TYP_OBJEKTU_CISELNIKU = {"materialy": "MATERIAL", "tloustky": "TLOUSTKA_MATERIALU",
                          "operace": "PRVNI_VYROBNI_OPERACE"}

# --- čtení ------------------------------------------------------------------------------------


@cteni
def seznam_dilu(spoj: Spojeni, filtr: DilyFiltr) -> Strana[DilRadek]:
    """Díly podle filtru; hledat se:normalizuje stejným způsobem jako se čísla ukládají."""
    filtr = filtr.model_copy(update={"hledat": normalizuj_identifikacni_cislo(filtr.hledat or "")})
    radky, celkem = repozitar.seznam_dilu(spoj, filtr)
    return Strana[DilRadek](polozky=[_radek(r) for r in radky], strana=filtr.strana,
                            velikost=filtr.velikost, celkem=celkem)


@cteni
def detail_dilu(spoj: Spojeni, dil_id: int) -> DilRadek:
    return _nacti_dil(spoj, dil_id)


@cteni
def ciselnik(spoj: Spojeni, typ: str) -> Seznam[CiselnikRadek]:
    """Číselník včetně vyřazených položek – ty u existujících díů zůstávají, nové je nedostanou."""
    _over_typ(typ)
    return Seznam[CiselnikRadek](polozky=[_polozka(r) for r in repozitar.polozky_ciselniku(spoj, typ)])


# --- díl (KMEN_EDIT) ------------------------------------------------------------------------------


@transakce("DIL_ZALOZENI")
def zaloz_dil(spoj: Spojeni, vstup: NovyDilVstup, kdo: Kontext) -> DilRadek:
    """Chyby: ALREADY_EXISTS (číslo po normalizaci), NOT_FOUND (číselník), VALIDATION_ERROR (rozměr V6)."""
    cislo = normalizuj_identifikacni_cislo(vstup.identifikacni_cislo)
    if repozitar.existuje_dil(spoj, cislo):
        raise AppError("ALREADY_EXISTS", f"Díl {cislo} už existuje.")
    _over_ciselniky(spoj, {pole: getattr(vstup, pole) for pole in _DIL_CISELNIK})
    velikost = _kod_velikosti(spoj, vstup.velikost_pozice_id)
    domena.potreba_mista(velikost, vstup.potrebna_delka_mm, vstup.potrebna_hloubka_mm)
    dil_id = repozitar.vloz_dil(spoj, identifikacni_cislo=cislo, nazev=vstup.nazev,
                                material_id=vstup.material_id, tloustka_id=vstup.tloustka_id,
                                prvni_operace_id=vstup.prvni_operace_id,
                                standardni_davka_ks=vstup.standardni_davka_ks,
                                velikost_pozice_id=vstup.velikost_pozice_id,
                                potrebna_delka_mm=vstup.potrebna_delka_mm,
                                potrebna_hloubka_mm=vstup.potrebna_hloubka_mm,
                                vault_url=vstup.vault_url, poznamka=vstup.poznamka)
    zapis(spoj, kdo, "DIL", dil_id, "IdentifikacniCislo", None, cislo)
    return _nacti_dil(spoj, dil_id)


@transakce("DIL_ZMENA")
def zmen_dil(spoj: Spojeni, dil_id: int, vstup: ZmenaDiluVstup, kdo: Kontext) -> DilRadek:
    """Mění jen poslaná pole; o každé skutečně změněné se sepíše řádek AuditZmen s důvodem."""
    puvodni = _nacti_radek(spoj, dil_id)
    zmeny = vstup.zmenena_pole()
    _over_ciselniky(spoj, {pole: hodnota for pole, hodnota in zmeny.items() if pole in _DIL_CISELNIK})
    nove = {}
    for pole, hodnota in zmeny.items():
        sloupec = _DIL_SLOUPCE[pole]
        if puvodni[sloupec] != hodnota:               # stejná hodnota se do auditu nepíše
            zapis(spoj, kdo, "DIL", dil_id, sloupec, puvodni[sloupec], hodnota, vstup.duvod)
            nove[sloupec] = hodnota
    if nove:
        repozitar.nastav_pole_dilu(spoj, dil_id, nove)
    return _nacti_dil(spoj, dil_id)


@transakce("DIL_DEAKTIVACE")
def deaktivuj_dil(spoj: Spojeni, dil_id: int, vstup: DuvodVstup, kdo: Kontext) -> DilRadek:
    """Chyby: NOT_EMPTY (díl má obsah na pozici – v_ObsahPozice), NOT_FOUND."""
    _nacti_radek(spoj, dil_id)
    if repozitar.ma_obsah(spoj, dil_id):
        raise AppError("NOT_EMPTY", "Díl má na pozici obsah, nejde vyřadit.")
    repozitar.nastav_pole_dilu(spoj, dil_id, {"Aktivni": False})
    zapis(spoj, kdo, "DIL", dil_id, "Aktivni", 1, 0, vstup.duvod)      # BIT
    return _nacti_dil(spoj, dil_id)


@transakce("DIL_VELIKOST")
def zmen_velikost(spoj: Spojeni, dil_id: int, vstup: ZmenaVelikostiVstup, kdo: Kontext) -> DilRadek:
    """Chyby: NOT_EMPTY (díl má obsah v DYN, Q-28), VALIDATION_ERROR (rozměr V6), NOT_FOUND.

    Q-28 je zatím otevřená; kontrakt popisuje navržené řešení – dokud má díl obsah v DYN,
    velikost se měnit nesmí, jinak se změní a zapíše do auditu.
    """
    puvodni = _nacti_radek(spoj, dil_id)
    velikost = _kod_velikosti(spoj, vstup.velikost_pozice_id)
    domena.potreba_mista(velikost, vstup.potrebna_delka_mm, vstup.potrebna_hloubka_mm)
    if repozitar.ma_obsah_v_dyn(spoj, dil_id):
        raise AppError("NOT_EMPTY", "Díl má obsah v dynamickém boxu, velikost nejde změnit (Q-28).")
    # Vstup je celý stav, tedy audit jen pro pole, které se skutečně změnila
    nove = {sloupec: hodnota for sloupec, hodnota in
            (("VelikostPoziceID", vstup.velikost_pozice_id), ("PotrebnaDelkaMM", vstup.potrebna_delka_mm),
             ("PotrebnaHloubkaMM", vstup.potrebna_hloubka_mm)) if puvodni[sloupec] != hodnota}
    for sloupec, hodnota in nove.items():
        zapis(spoj, kdo, "DIL", dil_id, sloupec, puvodni[sloupec], hodnota, vstup.duvod)
    if nove:
        repozitar.nastav_pole_dilu(spoj, dil_id, nove)
    return _nacti_dil(spoj, dil_id)


# --- číselníky (KMEN_EDIT) ------------------------------------------------------------------------


@transakce("CISELNIK_ZALOZENI")
def zaloz_polozku_ciselniku(spoj: Spojeni, typ: str, vstup: NovyCiselnikVstup, kdo: Kontext) -> CiselnikRadek:
    """Chyby: NOT_FOUND (typ), VALIDATION_ERROR (kód, název), ALREADY_EXISTS (kód po normalizaci)."""
    _over_typ(typ)
    kod = domena.normalizuj_kod_ciselniku(typ, vstup.kod)
    domena.over_nazev_ciselniku(typ, vstup.nazev, zakladani=True)
    if repozitar.polozka_ciselniku_podle_kodu(spoj, typ, kod) is not None:
        raise AppError("ALREADY_EXISTS", f"Kód {kod} už v číselníku je.")
    polozka_id = repozitar.vloz_polozku_ciselniku(spoj, typ, kod, vstup.nazev)
    return CiselnikRadek(id=polozka_id, kod=kod, nazev=vstup.nazev, aktivni=True)


@transakce("CISELNIK_ZMENA")
def zmen_polozku_ciselniku(spoj: Spojeni, typ: str, polozka_id: int, vstup: ZmenaCiselnikuVstup,
                           kdo: Kontext) -> CiselnikRadek:
    """Chyby: NOT_FOUND (typ, položka), VALIDATION_ERROR (kód, název), ALREADY_EXISTS (kód po normalizaci)."""
    _over_typ(typ)
    polozka = _polozka_radek(spoj, typ, polozka_id)
    sloupce = repozitar.sloupce_ciselniku(typ)
    zmeny = vstup.zmenena_pole()
    if "kod" in zmeny:
        zmeny["kod"] = domena.normalizuj_kod_ciselniku(typ, zmeny["kod"])
        jina = repozitar.polozka_ciselniku_podle_kodu(spoj, typ, zmeny["kod"])
        if jina is not None and jina["id"] != polozka_id:
            raise AppError("ALREADY_EXISTS", f"Kód {zmeny['kod']} už v číselníku je.")
    if "nazev" in zmeny:
        domena.over_nazev_ciselniku(typ, zmeny["nazev"], zakladani=False)
    nove = {}
    for pole, hodnota in zmeny.items():
        if polozka[pole] != hodnota:                   # stejná hodnota se do auditu nepíše
            zapis(spoj, kdo, _TYP_OBJEKTU_CISELNIKU[typ], polozka_id, sloupce[pole], polozka[pole], hodnota,
                  vstup.duvod)
            nove[sloupce[pole]] = hodnota
    if nove:
        repozitar.nastav_pole_polozky(spoj, typ, polozka_id, nove)
    return _polozka(_polozka_radek(spoj, typ, polozka_id))


@transakce("CISELNIK_DEAKTIVACE")
def deaktivuj_polozku_ciselniku(spoj: Spojeni, typ: str, polozka_id: int, vstup: DuvodVstup,
                                kdo: Kontext) -> CiselnikRadek:
    """Vyřazená položka zůstává u existujících dílů, nové díly ji nedostanou."""
    _over_typ(typ)
    _polozka_radek(spoj, typ, polozka_id)
    repozitar.nastav_pole_polozky(spoj, typ, polozka_id, {"Aktivni": False})
    zapis(spoj, kdo, _TYP_OBJEKTU_CISELNIKU[typ], polozka_id, "Aktivni", 1, 0, vstup.duvod)   # BIT
    return _polozka(_polozka_radek(spoj, typ, polozka_id))


# --- pomocné -------------------------------------------------------------------------------------


def _nacti_radek(spoj: Spojeni, dil_id: int) -> dict[str, Any]:
    """Řádek dílu z DB; jeho absence je NOT_FOUND (ID posílá klient a to mu nedůvěřujeme)."""
    radek = repozitar.nacti_dil(spoj, dil_id)
    if radek is None:
        raise AppError("NOT_FOUND", f"Díl {dil_id} neexistuje.")
    return radek


def _nacti_dil(spoj: Spojeni, dil_id: int) -> DilRadek:
    return _radek(_nacti_radek(spoj, dil_id))


def _over_ciselniky(spoj: Spojeni, pole: dict[str, Any]) -> None:
    """Každé poslané ID položky musí v číselníku existovat (i vyřazená – tu díl mít může)."""
    for jmeno, typ in _DIL_CISELNIK.items():
        if pole.get(jmeno) is not None and repozitar.polozka_ciselniku(spoj, typ, pole[jmeno]) is None:
            raise AppError("NOT_FOUND", f"Položka {pole[jmeno]} číselníku {typ} neexistuje.")


def _kod_velikosti(spoj: Spojeni, velikost_pozice_id: int | None) -> str | None:
    """ID velikosti → kód V1–V6; ostrov D ji čte z pohledu v_VelikostPozice ostrova C (P2)."""
    if velikost_pozice_id is None:
        return None
    kod = repozitar.kod_velikosti(spoj, velikost_pozice_id)
    if kod is None:
        raise AppError("NOT_FOUND", f"Velikost pozice {velikost_pozice_id} neexistuje.")
    return kod


def _over_typ(typ: str) -> None:
    if typ not in TYPY_CISELNIKU:
        raise AppError("NOT_FOUND", f"Číselník {typ!r} neexistuje. Povolené: {', '.join(TYPY_CISELNIKU)}.")


def _polozka_radek(spoj: Spojeni, typ: str, polozka_id: int) -> dict[str, Any]:
    radek = repozitar.polozka_ciselniku(spoj, typ, polozka_id)
    if radek is None:
        raise AppError("NOT_FOUND", f"Položka {polozka_id} číselníku {typ} neexistuje.")
    return radek


def _radek(radek: dict[str, Any]) -> DilRadek:
    return DilRadek(
        dil_id=radek["DilID"], identifikacni_cislo=radek["IdentifikacniCislo"], nazev=radek["NazevDilu"],
        material_id=radek["MaterialID"], material=radek["KodMaterialu"],
        tloustka_id=radek["TloustkaID"], tloustka_mm=radek["TloustkaMM"],
        prvni_operace_id=radek["PrvniOperaceID"], prvni_operace=radek["KodOperace"],
        standardni_davka_ks=radek["StandardniDavkaKs"],
        velikost_pozice_id=radek["VelikostPoziceID"], velikost=radek["Velikost"],
        potrebna_delka_mm=radek["PotrebnaDelkaMM"], potrebna_hloubka_mm=radek["PotrebnaHloubkaMM"],
        vault_url=radek["VaultVykresURL"], aktivni=radek["Aktivni"], poznamka=radek["Poznamka"])


def _polozka(radek: dict[str, Any]) -> CiselnikRadek:
    return CiselnikRadek(id=radek["id"], kod=radek["kod"], nazev=radek["nazev"], aktivni=radek["aktivni"])
