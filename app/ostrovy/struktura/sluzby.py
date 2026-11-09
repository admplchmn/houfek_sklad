"""Služby ostrova C – Struktura skladu a kódy. Jedna operace = @transakce, čtení = @cteni.

Fáze 1: SQL je v `repozitar.py`, vzorová data (KOSTRA) nenahrazuje nic – služby čtou a mění skutečné
tabulky. Repozitář vrací surové řádky, DTO kontraktu staví až služba (potřebuje je i pro audit).

Postup každé strukturální operace s boxem ve fázi 1 (jedna transakce, sekce 5.3 a P8):
  1. rozhrani.zamkni_mista(spoj, všechny aktivní pozice dotčených boxů) – stejné zámky jako sklad,
     takže během operace nikdo nenaskladní ani nevydá,
  2. obsah z v_ObsahPozice a statická přiřazení z v_StatickeMisto (ostrov E) → NOT_EMPTY,
  3. zápis Pozice / Box / VnitrniPoziceBoxu; pořadí na úrovni ve dvou krocích (domena.zmeny_poradi, Δ2),
  4. přepočet FullBoxKlic dotčených boxů (Q-03) a AuditZmen s důvodem (app.platforma.audit),
  5. v testu po operaci v_KontrolaIntegrity bez nálezů pro dotčené boxy (7.3 „Hotovo, když“).

Audit (kap. 25): zapisují se změny a vyřazení kmenových dat, ne jejich vznik. `Pole` je název sloupce,
`TypObjektu` název vlastní tabulky velkým písmenem (DIL, BOX, …), důvod ze vstupu jde do `Poznamka`
a BIT se audituje jako bool.
"""
from __future__ import annotations

from typing import Any

from app.platforma.audit import zapis
from app.platforma.chyby import AppError, chyba_vstupu
from app.platforma.db import Spojeni, cteni
from app.platforma.kontrakty import DuvodVstup, Seznam, Varovani
from app.platforma.transakce import transakce
from app.platforma.typy import Kontext, Rozmer

from . import domena, repozitar
from .kontrakty import (
    VAROVANI_BEZ_ZMENY,
    BlokaceVstup,
    BlokaceVysledek,
    BoxDetail,
    BoxNaUrovni,
    CleneniRadek,
    NovaUrovenVstup,
    NovePracovisteVstup,
    NovyBoxVstup,
    NovyRegalVstup,
    PoradiBoxuVstup,
    PracovisteFiltr,
    PracovisteRadek,
    PresunBoxuVstup,
    RegalRadek,
    RegalyFiltr,
    RekonfiguraceVstup,
    RozmerC7Vstup,
    SablonaPozice,
    UrovenRadek,
    UrovneFiltr,
    VnitrniPoziceDetail,
    VnitrniPoziceRadek,
    VymenaBoxuVstup,
    ZmenaPracovisteVstup,
    ZmenaRegaluVstup,
    ZmenaUrovneVstup,
)
from .rozhrani import rozloz_kod, zamkni_mista

# Pole PATCH kontraktu → sloupec vlastní tabulky (název sloupce se píše do AuditZmen.Pole).
_SLOUPCE_PRACOVISTE = {"nazev": "NazevPracoviste"}
_SLOUPCE_REGALU = {"nazev": "NazevRegalu"}
_SLOUPCE_UROVNE = {"poradi": "Poradi", "delka_plochy_mm": "DelkaPlochyMM", "hloubka_plochy_mm": "HloubkaPlochyMM"}
_SLOUPCE_C7 = {"delka_mm": "DelkaMM", "hloubka_mm": "HloubkaMM"}

# --- čtení ------------------------------------------------------------------------------------


@cteni
def seznam_pracovist(spoj: Spojeni, filtr: PracovisteFiltr) -> Seznam[PracovisteRadek]:
    return Seznam[PracovisteRadek](
        polozky=[_pracoviste(r) for r in repozitar.seznam_pracovistu(spoj, filtr.aktivni)])


@cteni
def seznam_regalu(spoj: Spojeni, filtr: RegalyFiltr) -> Seznam[RegalRadek]:
    return Seznam[RegalRadek](
        polozky=[_regal(r) for r in repozitar.seznam_regalu(spoj, filtr.pracoviste_id, filtr.aktivni)])


@cteni
def seznam_urovni(spoj: Spojeni, filtr: UrovneFiltr) -> Seznam[UrovenRadek]:
    """Úrovně regálu shora dolů podle svislého pořadí."""
    return Seznam[UrovenRadek](
        polozky=[_uroven(r) for r in repozitar.seznam_urovni(spoj, filtr.regal_id, filtr.aktivni)])


@cteni
def boxy_urovne(spoj: Spojeni, uroven_id: int) -> Seznam[BoxNaUrovni]:
    """Aktivní boxy úrovně zleva doprava (Pozice.Poradi ASC). Chyby: NOT_FOUND."""
    _nacti(repozitar.uroven(spoj, uroven_id), f"Úroveň {uroven_id} neexistuje.")
    return Seznam[BoxNaUrovni](polozky=[_na_urovni(r) for r in repozitar.boxy_urovne(spoj, uroven_id)])


@cteni
def detail_boxu(spoj: Spojeni, box_id: int) -> BoxDetail:
    """Box i vyřazený (po výměně T22 se musí dohledat); obsah boxu nenáleží ostrovu C."""
    return _detail(spoj, _nacti_box(spoj, box_id))


@cteni
def detail_vnitrni_pozice(spoj: Spojeni, vnitrni_pozice_id: int) -> VnitrniPoziceDetail:
    return _detail_pozice(_nacti_pozici(spoj, vnitrni_pozice_id))


@cteni
def seznam_cleneni(spoj: Spojeni) -> Seznam[CleneniRadek]:
    """Konfigurace C1–C7 se šablonou přihrádek (Q-06) – pro formulář boxu a náhled SVG."""
    return Seznam[CleneniRadek](polozky=_seskup_cleneni(repozitar.polozky_cleneni(spoj)))


# --- blokace (BLOKACE, skladový příkaz) ----------------------------------------------------------------


@transakce("BLOKACE", skladova=True)
def blokuj(spoj: Spojeni, vstup: BlokaceVstup, kdo: Kontext) -> BlokaceVysledek:
    """Zablokuje nebo odblokuje celý box či jednu pozici. Stejný stav = nic se nezapíše, varování BEZ_ZMENY.

    Zámky jako sklad (P8), pak UPDATE Blokovany a řádek AuditZmen (Pole Blokovany, důvod v Poznámce).
    Chyby: INVALID_BARCODE, VALIDATION_ERROR (regál), NOT_FOUND.
    """
    rozlozeny = rozloz_kod(vstup.kod)
    typ = domena.cil_blokace(rozlozeny.typ)
    box = _nacti(repozitar.box_podle_kodu(spoj, rozlozeny.kod_boxu),
                 f"Box {rozlozeny.kod_boxu} neexistuje nebo není aktivní.")
    if rozlozeny.kod_urovne is not None:
        domena.over_adresu(rozlozeny.kod_pracoviste or "", rozlozeny.kod_regalu or "", rozlozeny.kod_urovne,
                           box["KodBoxu"], box["FullBoxKlic"])
    pozice = repozitar.pozice_boxu(spoj, box["BoxID"])
    if typ == "BOX":
        kod, objekt_id, puvodne = box["KodBoxu"], box["BoxID"], bool(box["BoxBlokovany"])
        tabulka, typ_objektu, nazev = "Box", "BOX", f"Box {kod}"
    else:
        radek = next((p for p in pozice if p["KodPozice"] == rozlozeny.kod_pozice), None)
        if radek is None:
            raise AppError("NOT_FOUND", f"Pozice {rozlozeny.kod_mista} neexistuje nebo není aktivní.")
        kod = f"{box['KodBoxu']}-{radek['KodPozice']}"
        objekt_id, puvodne = radek["VnitrniPoziceID"], bool(radek["Blokovany"])
        tabulka, typ_objektu, nazev = "VnitrniPoziceBoxu", "VNITRNI_POZICE_BOXU", f"Pozice {kod}"
    zamkni_mista(spoj, [p["VnitrniPoziceID"] for p in pozice])
    varovani = ()
    if puvodne == vstup.blokovat:
        stav = "blokovaná" if vstup.blokovat else "odblokovaná"
        varovani = (Varovani(VAROVANI_BEZ_ZMENY, f"{nazev} už je {stav}, nic se nezměnilo."),)
    else:
        repozitar.nastav_pole(spoj, tabulka, objekt_id, {"Blokovany": vstup.blokovat})
        zapis(spoj, kdo, typ_objektu, objekt_id, "Blokovany", puvodne, vstup.blokovat, vstup.duvod)
    return BlokaceVysledek(typ=typ, kod=kod, box_id=box["BoxID"],
                           vnitrni_pozice_id=None if typ == "BOX" else objekt_id,
                           blokovano=vstup.blokovat, zmeneno=puvodne != vstup.blokovat, varovani=varovani)


# --- pracoviště, regály, úrovně (BOX_EDIT) ---------------------------------------------------------------


@transakce("PRACOVISTE_ZALOZENI")
def zaloz_pracoviste(spoj: Spojeni, vstup: NovePracovisteVstup, kdo: Kontext) -> PracovisteRadek:
    """Vznik kmenového údaje se do auditu nepíše (kap. 25). Chyby: VALIDATION_ERROR, ALREADY_EXISTS."""
    return _pracoviste(_nacti_pracoviste(spoj, repozitar.zaloz_pracoviste(spoj, vstup.kod_pracoviste,
                                                                         vstup.nazev)))


@transakce("PRACOVISTE_ZMENA")
def zmen_pracoviste(spoj: Spojeni, pracoviste_id: int, vstup: ZmenaPracovisteVstup, kdo: Kontext) -> PracovisteRadek:
    """Kód pracoviště je součástí barcode, mění se jen název. Chyby: NOT_FOUND, VALIDATION_ERROR."""
    puvodni = _nacti_pracoviste(spoj, pracoviste_id)
    _prepsat(spoj, kdo, "Pracoviste", pracoviste_id, _SLOUPCE_PRACOVISTE, puvodni, vstup.zmenena_pole(), vstup.duvod)
    return _pracoviste(_nacti_pracoviste(spoj, pracoviste_id))


@transakce("PRACOVISTE_DEAKTIVACE")
def deaktivuj_pracoviste(spoj: Spojeni, pracoviste_id: int, vstup: DuvodVstup, kdo: Kontext) -> PracovisteRadek:
    """Chyby: NOT_EMPTY (pracoviště má aktivní regál), NOT_FOUND."""
    radek = _nacti_pracoviste(spoj, pracoviste_id)
    regaly = [r["KodRegalu"] for r in repozitar.seznam_regalu(spoj, pracoviste_id, True)]
    if regaly:
        raise AppError("NOT_EMPTY", f"Pracoviště {radek['KodPracoviste']} má aktivní regály {', '.join(regaly)}."
                                    " Nejdřív je vyřaďte.")
    repozitar.nastav_pole(spoj, "Pracoviste", pracoviste_id, {"Aktivni": False})
    zapis(spoj, kdo, "PRACOVISTE", pracoviste_id, "Aktivni", True, False, vstup.duvod)
    return _pracoviste(_nacti_pracoviste(spoj, pracoviste_id))


@transakce("REGAL_ZALOZENI")
def zaloz_regal(spoj: Spojeni, vstup: NovyRegalVstup, kdo: Kontext) -> RegalRadek:
    """Chyby: VALIDATION_ERROR (kód), NOT_FOUND (pracoviště), ALREADY_EXISTS (kód na pracovišti)."""
    return _regal(_nacti_regal(spoj, repozitar.zaloz_regal(spoj, vstup.pracoviste_id, vstup.kod_regalu,
                                                           vstup.nazev)))


@transakce("REGAL_ZMENA")
def zmen_regal(spoj: Spojeni, regal_id: int, vstup: ZmenaRegaluVstup, kdo: Kontext) -> RegalRadek:
    """Kód regálu je součástí barcode, mění se jen název. Chyby: NOT_FOUND, VALIDATION_ERROR."""
    puvodni = _nacti_regal(spoj, regal_id)
    _prepsat(spoj, kdo, "Regal", regal_id, _SLOUPCE_REGALU, puvodni, vstup.zmenena_pole(), vstup.duvod)
    return _regal(_nacti_regal(spoj, regal_id))


@transakce("REGAL_DEAKTIVACE")
def deaktivuj_regal(spoj: Spojeni, regal_id: int, vstup: DuvodVstup, kdo: Kontext) -> RegalRadek:
    """Chyby: NOT_EMPTY (regál má aktivní úroveň), NOT_FOUND."""
    radek = _nacti_regal(spoj, regal_id)
    urovne = [u["KodUrovne"] for u in repozitar.seznam_urovni(spoj, regal_id, True)]
    if urovne:
        kod = domena.kod_regalu_barcode(radek["KodPracoviste"], radek["KodRegalu"])
        raise AppError("NOT_EMPTY", f"Regál {kod} má aktivní úrovně {', '.join(urovne)}. Nejdřív je vyřaďte.")
    repozitar.nastav_pole(spoj, "Regal", regal_id, {"Aktivni": False})
    zapis(spoj, kdo, "REGAL", regal_id, "Aktivni", True, False, vstup.duvod)
    return _regal(_nacti_regal(spoj, regal_id))


@transakce("UROVEN_ZALOZENI")
def zaloz_uroven(spoj: Spojeni, vstup: NovaUrovenVstup, kdo: Kontext) -> UrovenRadek:
    """Chyby: VALIDATION_ERROR (kód), NOT_FOUND (regál), ALREADY_EXISTS (kód na regálu)."""
    kod = domena.normalizuj_kod_urovne(vstup.kod_urovne)
    poradi = vstup.poradi if vstup.poradi is not None else domena.poradi_z_kodu_urovne(kod)
    uroven_id = repozitar.zaloz_uroven(spoj, vstup.regal_id, kod, poradi, vstup.delka_plochy_mm,
                                       vstup.hloubka_plochy_mm)
    return _uroven(_nacti_uroven(spoj, uroven_id))


@transakce("UROVEN_ZMENA")
def zmen_uroven(spoj: Spojeni, uroven_id: int, vstup: ZmenaUrovneVstup, kdo: Kontext) -> UrovenRadek:
    """Rozměr plochy je jen informace (17.1): změna nepřepočítává SVG ani boxy. Chyby: NOT_FOUND."""
    puvodni = _nacti_uroven(spoj, uroven_id)
    _prepsat(spoj, kdo, "Uroven", uroven_id, _SLOUPCE_UROVNE, puvodni, vstup.zmenena_pole(), vstup.duvod)
    return _uroven(_nacti_uroven(spoj, uroven_id))


@transakce("UROVEN_DEAKTIVACE")
def deaktivuj_uroven(spoj: Spojeni, uroven_id: int, vstup: DuvodVstup, kdo: Kontext) -> UrovenRadek:
    """Chyby: NOT_EMPTY (na úrovni stojí aktivní box), NOT_FOUND."""
    radek = _nacti_uroven(spoj, uroven_id)
    boxy = [b["KodBoxu"] for b in repozitar.boxy_urovne(spoj, uroven_id)]
    if boxy:
        raise AppError("NOT_EMPTY", f"Na úrovni {radek['KodUrovne']} stojí boxy {', '.join(boxy)}. "
                                    "Nejdřív je přesuňte nebo vyřaďte.")
    repozitar.nastav_pole(spoj, "Uroven", uroven_id, {"Aktivni": False})
    zapis(spoj, kdo, "UROVEN", uroven_id, "Aktivni", True, False, vstup.duvod)
    return _uroven(_nacti_uroven(spoj, uroven_id))


# --- operace s boxem (BOX_EDIT) ----------------------------------------------------------------------


@transakce("BOX_ZALOZENI")
def zaloz_box(spoj: Spojeni, uroven_id: int, vstup: NovyBoxVstup, kdo: Kontext) -> BoxDetail:
    """Pozice (pořadí na úrovni) + Box + vnitřní pozice ze šablony. Boxy od zvoleného pořadí se posunou.

    Vznik boxu se neaudituje (kap. 25). Chyby: NOT_FOUND (úroveň, členění), VALIDATION_ERROR (pořadí,
    číslo), ALREADY_EXISTS (kód boxu), BOX_SERIES_FULL.
    """
    uroven = _nacti(repozitar.uroven(spoj, uroven_id), f"Úroveň {uroven_id} neexistuje.")
    kod_boxu = _kod_boxu(spoj, uroven["RegalID"], vstup.typ_boxu, vstup.cislo_boxu)
    box_id = repozitar.zaloz_box(spoj, uroven_id, vstup.poradi, vstup.typ_boxu,
                                 _kod_cleneni(spoj, vstup.cleneni_id), vstup.delka_mm, vstup.hloubka_mm, kod_boxu)
    return _detail(spoj, _nacti_box(spoj, box_id))


@transakce("BOX_VYMENA")
def vymen_box(spoj: Spojeni, box_id: int, vstup: VymenaBoxuVstup, kdo: Kontext) -> BoxDetail:
    """Nový box na stejné Pozici (PoziceID i pořadí zůstávají); starý prázdný box Aktivni = 0 (Q-04).

    Starý box zůstává dohledat se svým kódem (trvalá identita na štítku); do auditu jde jeho vyřazení,
    nové číslo boxu se zakládá, tedy neaudituje (kap. 25).
    Chyby: NOT_FOUND, NOT_EMPTY (obsah nebo STAT přiřazení), ALREADY_EXISTS, BOX_SERIES_FULL.
    """
    stary = _nacti_box(spoj, box_id)
    zamkni_mista(spoj, _ids_pozic(spoj, box_id))
    _over_prazdny(spoj, stary)
    kod_boxu = _kod_boxu(spoj, stary["RegalID"], vstup.typ_boxu, vstup.cislo_boxu)
    novy_id = repozitar.vymen_box(spoj, stary, vstup.typ_boxu, _kod_cleneni(spoj, vstup.cleneni_id),
                                  vstup.delka_mm, vstup.hloubka_mm, kod_boxu)
    zapis(spoj, kdo, "BOX", box_id, "Aktivni", True, False, vstup.duvod)
    return _detail(spoj, _nacti_box(spoj, novy_id))


@transakce("BOX_PRESUN")
def presun_box(spoj: Spojeni, box_id: int, vstup: PresunBoxuVstup, kdo: Kontext) -> BoxDetail:
    """Box i s obsahem na jinou úroveň, bez skladového pohybu; obsah zůstává na svých pozicích.

    Stará Pozice se vyřadí a zbytek její úrovně se přečísluje; na cílové úrovni se boxy od zvoleného
    pořadí posunou. FullBoxKlic se přepočítá (Q-03) a zapíše do auditu, barcode pozic (BPLE037-A) se
    nemění (Q-02). Chyby: NOT_FOUND, VALIDATION_ERROR (stejná úroveň, cizí pracoviště DYN boxu – Q-30,
    pořadí).
    """
    box = _nacti_box(spoj, box_id)
    cil = _nacti(repozitar.uroven(spoj, vstup.cil_uroven_id), f"Úroveň {vstup.cil_uroven_id} neexistuje.")
    if cil["UrovenID"] == box["UrovenID"]:
        raise chyba_vstupu("Box už na této úrovni stojí.",
                           {"cilUrovenId": "Pořadí na stejné úrovni se mění přes POST /boxy/{id}/poradi."})
    domena.over_presun_boxu(box["KodTypu"], box["KodBoxu"], _nacti_regal(spoj, cil["RegalID"])["KodPracoviste"])
    zamkni_mista(spoj, _ids_pozic(spoj, box_id))
    repozitar.presun_box(spoj, box, vstup.cil_uroven_id, vstup.poradi)
    novy = _nacti_box(spoj, box_id)          # FullBoxKlic přepočítal repozitář, audituje se jeho výsledek
    zapis(spoj, kdo, "BOX", box_id, "FullBoxKlic", box["FullBoxKlic"], novy["FullBoxKlic"], vstup.duvod)
    return _detail(spoj, novy)


@transakce("BOX_PORADI")
def zmen_poradi_boxu(spoj: Spojeni, box_id: int, vstup: PoradiBoxuVstup, kdo: Kontext) -> Seznam[BoxNaUrovni]:
    """Přesune box na nové pořadí v rámci jeho úrovně; vrací celou úroveň v novém pořadí (T23).

    Mění se jen sloupec Poradi tabulky Pozice (1:1 k boxu, PoziceID zůstávají), proto se audituje pod
    boxem. Chyby: NOT_FOUND, VALIDATION_ERROR (pořadí).
    """
    box = _nacti_box(spoj, box_id)
    zamkni_mista(spoj, _ids_pozic(spoj, box_id))
    repozitar.zmen_poradi_boxu(spoj, box, vstup.nove_poradi)
    zapis(spoj, kdo, "BOX", box_id, "Poradi", box["Poradi"], vstup.nove_poradi, vstup.duvod)
    return Seznam[BoxNaUrovni](polozky=[_na_urovni(r) for r in repozitar.boxy_urovne(spoj, box["UrovenID"])])


@transakce("BOX_REKONFIGURACE")
def rekonfiguruj_box(spoj: Spojeni, box_id: int, vstup: RekonfiguraceVstup, kdo: Kontext) -> BoxDetail:
    """Staré vnitřní pozice Aktivni = 0, nové ze šablony; štítky pozic se tisknou znovu (Q-27, A-14).

    Q-27 je otevřený bod: rekonfigurace se dělá jen u boxu bez zásoby a bez STAT přiřazení.
    Chyby: NOT_FOUND, VALIDATION_ERROR (stejné členění), NOT_EMPTY (obsah nebo STAT přiřazení).
    """
    box = _nacti_box(spoj, box_id)
    nova = _nacti_cleneni(spoj, vstup.cleneni_id)
    domena.over_rekonfiguraci(box["KodCleneni"], nova["KodCleneni"])
    zamkni_mista(spoj, _ids_pozic(spoj, box_id))
    _over_prazdny(spoj, box)
    repozitar.rekonfiguruj_box(spoj, box, nova["KodCleneni"])
    zapis(spoj, kdo, "BOX", box_id, "CleneniBoxuID", box["CleneniBoxuID"], nova["CleneniBoxuID"], vstup.duvod)
    return _detail(spoj, _nacti_box(spoj, box_id))


@transakce("BOX_DEAKTIVACE")
def deaktivuj_box(spoj: Spojeni, box_id: int, vstup: DuvodVstup, kdo: Kontext) -> BoxDetail:
    """Box i jeho Pozice Aktivni = 0, boxy vpravo se posunou doleva. Chyby: NOT_FOUND, NOT_EMPTY."""
    box = _nacti_box(spoj, box_id)
    zamkni_mista(spoj, _ids_pozic(spoj, box_id))
    _over_prazdny(spoj, box)
    repozitar.vyrad_box(spoj, box)
    zapis(spoj, kdo, "BOX", box_id, "Aktivni", True, False, vstup.duvod)
    return _detail(spoj, _nacti_box(spoj, box_id))


@transakce("C7_ROZMER")
def nastav_rozmer_c7(spoj: Spojeni, vnitrni_pozice_id: int, vstup: RozmerC7Vstup, kdo: Kontext
                     ) -> VnitrniPoziceDetail:
    """Nový rozměr variabilní pozice C7 (Q-01); jen u prázdné pozice. Chyby: NOT_FOUND, VALIDATION_ERROR, NOT_EMPTY."""
    misto = _nacti_pozici(spoj, vnitrni_pozice_id)
    domena.over_rozmer_c7(misto["KodVelikosti"], Rozmer(vstup.delka_mm, vstup.hloubka_mm),
                          Rozmer(misto["DelkaMM"], misto["HloubkaMM"]))
    zamkni_mista(spoj, [vnitrni_pozice_id])
    if repozitar.ma_obsah(spoj, vnitrni_pozice_id):
        raise AppError("NOT_EMPTY", f"Na pozici {misto['KodBoxu']}-{misto['KodPozice']} je zásoba."
                                    " Rozměr C7 se mění jen u prázdné pozice.")
    puvodni = {"DelkaMM": misto["RozmerC7DelkaMM"], "HloubkaMM": misto["RozmerC7HloubkaMM"]}
    _prepsat(spoj, kdo, "VnitrniPoziceBoxu", vnitrni_pozice_id, _SLOUPCE_C7, puvodni, vstup.zmenena_pole(),
             vstup.duvod, typ_objektu="VNITRNI_POZICE_BOXU")
    return _detail_pozice(_nacti_pozici(spoj, vnitrni_pozice_id))


# --- pomocné -------------------------------------------------------------------------------------


def _nacti(radek: dict[str, Any] | None, zprava: str) -> dict[str, Any]:
    """Řádek z DB; jeho absence je NOT_FOUND (ID posílá klient a to mu nedůvěřujeme)."""
    if radek is None:
        raise AppError("NOT_FOUND", zprava)
    return radek


def _nacti_pracoviste(spoj: Spojeni, pracoviste_id: int) -> dict[str, Any]:
    return _nacti(repozitar.pracoviste(spoj, pracoviste_id), f"Pracoviště {pracoviste_id} neexistuje.")


def _nacti_regal(spoj: Spojeni, regal_id: int) -> dict[str, Any]:
    return _nacti(repozitar.regal(spoj, regal_id), f"Regál {regal_id} neexistuje.")


def _nacti_uroven(spoj: Spojeni, uroven_id: int) -> dict[str, Any]:
    return _nacti(repozitar.uroven(spoj, uroven_id), f"Úroveň {uroven_id} neexistuje.")


def _nacti_box(spoj: Spojeni, box_id: int) -> dict[str, Any]:
    return _nacti(repozitar.box(spoj, box_id), f"Box {box_id} neexistuje.")


def _nacti_pozici(spoj: Spojeni, vnitrni_pozice_id: int) -> dict[str, Any]:
    """Pozice i s boxem; vyřazené místo je NOT_FOUND (na neaktivním místě se měnit nedá)."""
    return _nacti(repozitar.vnitrni_pozice(spoj, vnitrni_pozice_id),
                  f"Pozice {vnitrni_pozice_id} neexistuje nebo není aktivní.")


def _nacti_cleneni(spoj: Spojeni, cleneni_id: int) -> dict[str, Any]:
    return _nacti(repozitar.cleneni(spoj, cleneni_id), f"Členění {cleneni_id} neexistuje (povolené C1–C7).")


def _kod_cleneni(spoj: Spojeni, cleneni_id: int) -> str:
    """Kód členění z ID v kontraktu – repozitář pracuje s kódy (součást kódu boxu a hlášek)."""
    return _nacti_cleneni(spoj, cleneni_id)["KodCleneni"]


def _kod_boxu(spoj: Spojeni, regal_id: int, typ_boxu: str, cislo: int | None) -> str | None:
    """Kód nového boxu z čísla řady (11.2.1); řada platí podle pracoviště regálu.

    None = repozitář vydá další volné číslo. Chyby: NOT_FOUND (regál), VALIDATION_ERROR (číslo).
    """
    if cislo is None:
        return None
    return domena.kod_boxu(typ_boxu, _nacti_regal(spoj, regal_id)["KodPracoviste"], cislo)


def _ids_pozic(spoj: Spojeni, box_id: int) -> list[int]:
    """Aktivní vnitřní pozice boxu – vše, co se při operaci s boxem zamyká (P8)."""
    return [p["VnitrniPoziceID"] for p in repozitar.pozice_boxu(spoj, box_id)]


def _prepsat(spoj: Spojeni, kdo: Kontext, tabulka: str, objekt_id: int, sloupce: dict[str, str],
             puvodni: dict[str, Any], zmeny: dict[str, Any], duvod: str, *,
             typ_objektu: str | None = None) -> None:
    """Zapíše poslaná pole a sepíše o nich řádky AuditZmen; `Pole` je název sloupce, `TypObjektu` tabulka.

    Stejná hodnota se nezapíše ani nezaaudituje (opakování stejného PATCH nesmí zaplavit audit).
    """
    nove = {}
    for pole, hodnota in zmeny.items():
        sloupec = sloupce[pole]
        if puvodni[sloupec] != hodnota:
            zapis(spoj, kdo, typ_objektu or tabulka.upper(), objekt_id, sloupec, puvodni[sloupec], hodnota, duvod)
            nove[sloupec] = hodnota
    if nove:
        repozitar.nastav_pole(spoj, tabulka, objekt_id, nove)


def _over_prazdny(spoj: Spojeni, box: dict[str, Any]) -> None:
    """Strukturální změna jen u boxu bez zásoby a bez statického přiřazení (analýza 9.7, Q-27).

    Obsah i přiřazení se čtou z pohledů ostrova E (P2) a až po zamkni_mista, aby mezi kontrolou
    a zápisem nikdo nenaskladnil. Chyby: NOT_EMPTY.
    """
    obsazene = repozitar.kody_pozic(spoj, box["BoxID"], "dbo.v_ObsahPozice")
    prirazene = repozitar.kody_pozic(spoj, box["BoxID"], "dbo.v_StatickeMisto")
    if obsazene or prirazene:
        duvody = ([f"zásoba na {', '.join(obsazene)}"] if obsazene else []) \
            + ([f"statické přiřazení na {', '.join(prirazene)}"] if prirazene else [])
        raise AppError("NOT_EMPTY", f"Box {box['KodBoxu']} není volný: {'; '.join(duvody)}. "
                                    "Nejdřív zásobu vyskladněte a přiřazení ukončete.")


def _pracoviste(radek: dict[str, Any]) -> PracovisteRadek:
    return PracovisteRadek(pracoviste_id=radek["PracovisteID"], kod_pracoviste=radek["KodPracoviste"],
                           nazev=radek["NazevPracoviste"], aktivni=bool(radek["Aktivni"]))


def _regal(radek: dict[str, Any]) -> RegalRadek:
    return RegalRadek(
        regal_id=radek["RegalID"], pracoviste_id=radek["PracovisteID"], kod_pracoviste=radek["KodPracoviste"],
        kod_regalu=radek["KodRegalu"], kod=domena.kod_regalu_barcode(radek["KodPracoviste"], radek["KodRegalu"]),
        nazev=radek["NazevRegalu"], aktivni=bool(radek["Aktivni"]))


def _uroven(radek: dict[str, Any]) -> UrovenRadek:
    return UrovenRadek(
        uroven_id=radek["UrovenID"], regal_id=radek["RegalID"], kod_urovne=radek["KodUrovne"],
        poradi=radek["Poradi"], delka_plochy_mm=radek["DelkaPlochyMM"], hloubka_plochy_mm=radek["HloubkaPlochyMM"],
        pocet_boxu=radek["PocetBoxu"], aktivni=bool(radek["Aktivni"]))


def _na_urovni(radek: dict[str, Any]) -> BoxNaUrovni:
    return BoxNaUrovni(box_id=radek["BoxID"], kod_boxu=radek["KodBoxu"], typ_boxu=radek["KodTypu"],
                       kod_cleneni=radek["KodCleneni"], poradi=radek["Poradi"],
                       kod_pozice_urovne=domena.kod_pozice_urovne(radek["Poradi"]),
                       blokovany=bool(radek["BoxBlokovany"]))


def _pozice(radek: dict[str, Any], kod_boxu: str) -> VnitrniPoziceRadek:
    return VnitrniPoziceRadek(
        vnitrni_pozice_id=radek["VnitrniPoziceID"], kod_pozice=radek["KodPozice"],
        kod=f"{kod_boxu}-{radek['KodPozice']}", velikost=radek["KodVelikosti"],
        poradi_v_boxu=radek["PoradiVBoxu"], rozmer_c7_delka_mm=radek["RozmerC7DelkaMM"],
        rozmer_c7_hloubka_mm=radek["RozmerC7HloubkaMM"], blokovana=bool(radek["Blokovany"]))


def _detail(spoj: Spojeni, radek: dict[str, Any]) -> BoxDetail:
    """Box + jeho aktivní vnitřní pozice (vyřazený box je dohledat, ale místa už nemá)."""
    return BoxDetail(
        box_id=radek["BoxID"], kod_boxu=radek["KodBoxu"], typ_boxu=radek["KodTypu"],
        cleneni_id=radek["CleneniBoxuID"], kod_cleneni=radek["KodCleneni"], delka_mm=radek["DelkaMM"],
        hloubka_mm=radek["HloubkaMM"], full_box_klic=radek["FullBoxKlic"], blokovany=bool(radek["BoxBlokovany"]),
        aktivni=bool(radek["Aktivni"]), poradi=radek["Poradi"],
        kod_pozice_urovne=domena.kod_pozice_urovne(radek["Poradi"]), uroven_id=radek["UrovenID"],
        kod_urovne=radek["KodUrovne"], regal_id=radek["RegalID"], kod_regalu=radek["KodRegalu"],
        pracoviste_id=radek["PracovisteID"], kod_pracoviste=radek["KodPracoviste"],
        pozice=[_pozice(p, radek["KodBoxu"]) for p in repozitar.pozice_boxu(spoj, radek["BoxID"])])


def _detail_pozice(radek: dict[str, Any]) -> VnitrniPoziceDetail:
    return VnitrniPoziceDetail(
        vnitrni_pozice_id=radek["VnitrniPoziceID"], kod_pozice=radek["KodPozice"],
        kod=f"{radek['KodBoxu']}-{radek['KodPozice']}", velikost=radek["KodVelikosti"],
        poradi_v_boxu=radek["PoradiVBoxu"], rozmer_c7_delka_mm=radek["RozmerC7DelkaMM"],
        rozmer_c7_hloubka_mm=radek["RozmerC7HloubkaMM"], blokovana=bool(radek["Blokovany"]),
        blokovano=bool(radek["BoxBlokovany"]) or bool(radek["Blokovany"]),
        adresa=f"{radek['FullBoxKlic']}-{radek['KodPozice']}", box_id=radek["BoxID"],
        kod_boxu=radek["KodBoxu"], typ_boxu=radek["KodTypu"], kod_cleneni=radek["KodCleneni"],
        box_blokovany=bool(radek["BoxBlokovany"]), uroven_id=radek["UrovenID"], regal_id=radek["RegalID"],
        pracoviste_id=radek["PracovisteID"], kod_pracoviste=radek["KodPracoviste"])


def _seskup_cleneni(radky: list[dict[str, Any]]) -> list[CleneniRadek]:
    """Řádky členění i s přihrádkami šablony (Q-06) seskupené do jednoho řádku za členění."""
    prihradky: dict[int, list[SablonaPozice]] = {}
    for r in radky:
        prihradky.setdefault(r["CleneniBoxuID"], []).append(SablonaPozice(
            dyn_kod=r["DynKod"], stat_kod=r["StatKod"], poradi=r["Poradi"], rada=r["Rada"],
            sloupec=r["Sloupec"], velikost=r["KodVelikosti"], rel_x=float(r["RelX"]), rel_y=float(r["RelY"]),
            rel_sirka=float(r["RelSirka"]), rel_hloubka=float(r["RelHloubka"])))
    hlavicky = {r["CleneniBoxuID"]: r for r in radky}
    return [CleneniRadek(cleneni_id=id_cleneni, kod_cleneni=hlavicky[id_cleneni]["KodCleneni"],
                         pocet_pozic=hlavicky[id_cleneni]["PocetPozic"], pozice=prihradky[id_cleneni])
            for id_cleneni in prihradky]
