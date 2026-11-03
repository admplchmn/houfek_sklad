"""Služby ostrova D – Díly a číselníky. Jedna operace = @transakce, čtení = @cteni.

Fáze 0: kontrakt a čistá pravidla (domena) jsou hotové, data jsou vzorová (KOSTRA).
Ve fázi 1 vlastník nahradí řádky `from . import ukazky` voláním repozitar.* a doplní audit
(app.platforma.audit.zapis) – podpisy funkcí se nemění.
"""
from __future__ import annotations

from app.platforma.chyby import AppError
from app.platforma.db import Spojeni, cteni
from app.platforma.kontrakty import CiselnikRadek, DuvodVstup, Seznam, Strana
from app.platforma.transakce import transakce
from app.platforma.typy import Kontext

from . import domena
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

# --- čtení ------------------------------------------------------------------------------------


@cteni
def seznam_dilu(spoj: Spojeni, filtr: DilyFiltr) -> Strana[DilRadek]:
    from . import ukazky  # KOSTRA (fáze 0)

    hledat = normalizuj_identifikacni_cislo(filtr.hledat or "")
    radky = [d for d in ukazky.DIL_RADKY.values()
             if hledat in d.identifikacni_cislo and (filtr.aktivni is None or d.aktivni == filtr.aktivni)]
    return Strana[DilRadek](polozky=radky, strana=filtr.strana, velikost=filtr.velikost, celkem=len(radky))


@cteni
def detail_dilu(spoj: Spojeni, dil_id: int) -> DilRadek:
    return _nacti_dil(spoj, dil_id)


@cteni
def ciselnik(spoj: Spojeni, typ: str) -> Seznam[CiselnikRadek]:
    _over_typ(typ)
    from . import ukazky  # KOSTRA (fáze 0)

    return Seznam[CiselnikRadek](polozky=ukazky.CISELNIKY[typ])


# --- díl (KMEN_EDIT) ------------------------------------------------------------------------------


@transakce("DIL_ZALOZENI")
def zaloz_dil(spoj: Spojeni, vstup: NovyDilVstup, kdo: Kontext) -> DilRadek:
    """Chyby: ALREADY_EXISTS (číslo po normalizaci), NOT_FOUND (číselník), VALIDATION_ERROR (rozměr V6)."""
    from . import ukazky  # KOSTRA (fáze 0)

    cislo = normalizuj_identifikacni_cislo(vstup.identifikacni_cislo)
    if any(d.identifikacni_cislo == cislo for d in ukazky.DIL_RADKY.values()):
        raise AppError("ALREADY_EXISTS", f"Díl {cislo} už existuje.")
    velikost = _kod_velikosti(vstup.velikost_pozice_id)
    domena.potreba_mista(velikost, vstup.potrebna_delka_mm, vstup.potrebna_hloubka_mm)
    return DilRadek(
        dil_id=9001, identifikacni_cislo=cislo, nazev=vstup.nazev,
        material_id=vstup.material_id, material=None, tloustka_id=vstup.tloustka_id, tloustka_mm=None,
        prvni_operace_id=vstup.prvni_operace_id, prvni_operace=None, standardni_davka_ks=vstup.standardni_davka_ks,
        velikost_pozice_id=vstup.velikost_pozice_id, velikost=velikost,
        potrebna_delka_mm=vstup.potrebna_delka_mm, potrebna_hloubka_mm=vstup.potrebna_hloubka_mm,
        vault_url=vstup.vault_url, aktivni=True, poznamka=vstup.poznamka,
    )


@transakce("DIL_ZMENA")
def zmen_dil(spoj: Spojeni, dil_id: int, vstup: ZmenaDiluVstup, kdo: Kontext) -> DilRadek:
    """Mění jen poslaná pole; každé pole = jeden řádek AuditZmen s důvodem."""
    return _nacti_dil(spoj, dil_id).model_copy(update=vstup.zmenena_pole())


@transakce("DIL_DEAKTIVACE")
def deaktivuj_dil(spoj: Spojeni, dil_id: int, vstup: DuvodVstup, kdo: Kontext) -> DilRadek:
    """Chyby: NOT_EMPTY (díl má obsah na pozici – v_ObsahPozice), NOT_FOUND."""
    return _nacti_dil(spoj, dil_id).model_copy(update={"aktivni": False})


@transakce("DIL_VELIKOST")
def zmen_velikost(spoj: Spojeni, dil_id: int, vstup: ZmenaVelikostiVstup, kdo: Kontext) -> DilRadek:
    """Chyby: NOT_EMPTY (díl má obsah v DYN, Q-28), VALIDATION_ERROR (rozměr V6), NOT_FOUND."""
    dil = _nacti_dil(spoj, dil_id)
    velikost = _kod_velikosti(vstup.velikost_pozice_id)
    domena.potreba_mista(velikost, vstup.potrebna_delka_mm, vstup.potrebna_hloubka_mm)
    return dil.model_copy(update={"velikost_pozice_id": vstup.velikost_pozice_id, "velikost": velikost,
                                  "potrebna_delka_mm": vstup.potrebna_delka_mm,
                                  "potrebna_hloubka_mm": vstup.potrebna_hloubka_mm})


# --- číselníky (KMEN_EDIT) ------------------------------------------------------------------------


@transakce("CISELNIK_ZALOZENI")
def zaloz_polozku_ciselniku(spoj: Spojeni, typ: str, vstup: NovyCiselnikVstup, kdo: Kontext) -> CiselnikRadek:
    """Chyby: NOT_FOUND (typ), VALIDATION_ERROR (kód, název), ALREADY_EXISTS (kód po normalizaci)."""
    _over_typ(typ)
    kod = domena.normalizuj_kod_ciselniku(typ, vstup.kod)
    domena.over_nazev_ciselniku(typ, vstup.nazev, zakladani=True)
    from . import ukazky  # KOSTRA (fáze 0)

    if any(p.kod == kod for p in ukazky.CISELNIKY[typ]):
        raise AppError("ALREADY_EXISTS", f"Kód {kod} už v číselníku je.")
    return CiselnikRadek(id=9001, kod=kod, nazev=vstup.nazev, aktivni=True)


@transakce("CISELNIK_ZMENA")
def zmen_polozku_ciselniku(spoj: Spojeni, typ: str, polozka_id: int, vstup: ZmenaCiselnikuVstup,
                           kdo: Kontext) -> CiselnikRadek:
    _over_typ(typ)
    zmena = vstup.zmenena_pole()
    if "kod" in zmena:
        zmena["kod"] = domena.normalizuj_kod_ciselniku(typ, zmena["kod"])
    if "nazev" in zmena:
        domena.over_nazev_ciselniku(typ, zmena["nazev"], zakladani=False)
    return _polozka(typ, polozka_id).model_copy(update=zmena)


@transakce("CISELNIK_DEAKTIVACE")
def deaktivuj_polozku_ciselniku(spoj: Spojeni, typ: str, polozka_id: int, vstup: DuvodVstup,
                                kdo: Kontext) -> CiselnikRadek:
    """Vyřazená položka zůstává u existujících dílů, nové díly ji nedostanou."""
    _over_typ(typ)
    return _polozka(typ, polozka_id).model_copy(update={"aktivni": False})


# --- pomocné -------------------------------------------------------------------------------------


def _nacti_dil(spoj: Spojeni, dil_id: int) -> DilRadek:
    """Fáze 1: repozitar.nacti_dil(spoj, dil_id) nad v_Dil."""
    from . import ukazky  # KOSTRA (fáze 0)

    dil = ukazky.DIL_RADKY.get(dil_id)
    if dil is None:
        raise AppError("NOT_FOUND", f"Díl {dil_id} neexistuje.")
    return dil


def _over_typ(typ: str) -> None:
    if typ not in TYPY_CISELNIKU:
        raise AppError("NOT_FOUND", f"Číselník {typ!r} neexistuje. Povolené: {', '.join(TYPY_CISELNIKU)}.")


def _kod_velikosti(velikost_pozice_id: int | None) -> str | None:
    """ID velikosti → kód V1–V6 (fáze 1: pohled v_VelikostPozice ostrova C)."""
    if velikost_pozice_id is None:
        return None
    from . import ukazky  # KOSTRA (fáze 0)

    kod = ukazky.VELIKOSTI.get(velikost_pozice_id)
    if kod is None:
        raise AppError("NOT_FOUND", f"Velikost pozice {velikost_pozice_id} neexistuje.")
    return kod


def _polozka(typ: str, polozka_id: int) -> CiselnikRadek:
    from . import ukazky  # KOSTRA (fáze 0)

    for polozka in ukazky.CISELNIKY[typ]:
        if polozka.id == polozka_id:
            return polozka
    raise AppError("NOT_FOUND", f"Položka {polozka_id} číselníku {typ} neexistuje.")
