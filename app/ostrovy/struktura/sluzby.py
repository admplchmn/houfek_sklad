"""Služby ostrova C – Struktura skladu a kódy. Jedna operace = @transakce, čtení = @cteni.

Fáze 0: kontrakt a čistá pravidla (domena) jsou hotové, data jsou vzorová (KOSTRA).
Ve fázi 1 vlastník nahradí řádky `from . import ukazky` voláním repozitar.* – podpisy se nemění.

Postup každé strukturální operace s boxem ve fázi 1 (jedna transakce, sekce 5.3 a P8):
  1. rozhrani.zamkni_mista(spoj, všechny aktivní pozice dotčených boxů) – stejné zámky jako sklad,
     takže během operace nikdo nenaskladní ani nevydá,
  2. obsah z v_ObsahPozice a statická přiřazení z v_StatickeMisto (ostrov E) → NOT_EMPTY,
  3. zápis Pozice / Box / VnitrniPoziceBoxu; pořadí na úrovni ve dvou krocích (domena.zmeny_poradi, Δ2),
  4. přepočet FullBoxKlic dotčených boxů (Q-03) a AuditZmen s důvodem (app.platforma.audit),
  5. v testu po operaci v_KontrolaIntegrity bez nálezů pro dotčené boxy (7.3 „Hotovo, když“).
"""
from __future__ import annotations

from app.platforma.chyby import AppError, chyba_vstupu
from app.platforma.db import Spojeni, cteni
from app.platforma.kontrakty import DuvodVstup, Seznam, Varovani
from app.platforma.transakce import transakce
from app.platforma.typy import Kontext, Rozmer

from . import domena
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
    UrovenRadek,
    UrovneFiltr,
    VnitrniPoziceDetail,
    VnitrniPoziceRadek,
    VymenaBoxuVstup,
    ZmenaPracovisteVstup,
    ZmenaRegaluVstup,
    ZmenaUrovneVstup,
)
from .rozhrani import rozloz_kod

NOVE_ID = 9001            # KOSTRA: ID nově založeného objektu ve vzorových odpovědích
NOVE_ID_POZICE = 9101

# --- čtení ------------------------------------------------------------------------------------


@cteni
def seznam_pracovist(spoj: Spojeni, filtr: PracovisteFiltr) -> Seznam[PracovisteRadek]:
    from . import ukazky  # KOSTRA (fáze 0)

    return Seznam[PracovisteRadek](polozky=[p for p in ukazky.PRACOVISTE if _aktivita(p.aktivni, filtr.aktivni)])


@cteni
def seznam_regalu(spoj: Spojeni, filtr: RegalyFiltr) -> Seznam[RegalRadek]:
    from . import ukazky  # KOSTRA (fáze 0)

    return Seznam[RegalRadek](polozky=[
        r for r in ukazky.REGALY
        if filtr.pracoviste_id in (None, r.pracoviste_id) and _aktivita(r.aktivni, filtr.aktivni)])


@cteni
def seznam_urovni(spoj: Spojeni, filtr: UrovneFiltr) -> Seznam[UrovenRadek]:
    """Úrovně regálu shora dolů podle svislého pořadí."""
    from . import ukazky  # KOSTRA (fáze 0)

    urovne = [u for u in ukazky.UROVNE if u.regal_id == filtr.regal_id and _aktivita(u.aktivni, filtr.aktivni)]
    return Seznam[UrovenRadek](polozky=sorted(urovne, key=lambda u: -u.poradi))


@cteni
def boxy_urovne(spoj: Spojeni, uroven_id: int) -> Seznam[BoxNaUrovni]:
    """Aktivní boxy úrovně zleva doprava (Pozice.Poradi ASC). Chyby: NOT_FOUND."""
    _nacti_uroven(uroven_id)
    return Seznam[BoxNaUrovni](polozky=[_na_urovni(b, b.poradi) for b in _boxy_na_urovni(uroven_id)])


@cteni
def detail_boxu(spoj: Spojeni, box_id: int) -> BoxDetail:
    return _nacti_box(box_id)


@cteni
def detail_vnitrni_pozice(spoj: Spojeni, vnitrni_pozice_id: int) -> VnitrniPoziceDetail:
    box, pozice = _nacti_pozici(vnitrni_pozice_id)
    return _detail_pozice(box, pozice)


@cteni
def seznam_cleneni(spoj: Spojeni) -> Seznam[CleneniRadek]:
    """Konfigurace C1–C7 se šablonou přihrádek (Q-06) – pro formulář boxu a náhled SVG."""
    from . import ukazky  # KOSTRA (fáze 0)

    return Seznam[CleneniRadek](polozky=ukazky.CLENENI)


# --- blokace (BLOKACE, skladový příkaz) ----------------------------------------------------------------


@transakce("BLOKACE", skladova=True)
def blokuj(spoj: Spojeni, vstup: BlokaceVstup, kdo: Kontext) -> BlokaceVysledek:
    """Zablokuje nebo odblokuje celý box či jednu pozici. Stejný stav = nic se nezapíše, varování BEZ_ZMENY.

    Fáze 1: zamkni_mista(pozice boxu nebo pozice) → UPDATE Blokovany → AuditZmen (Pole Blokovany, důvod).
    Chyby: INVALID_BARCODE, VALIDATION_ERROR (regál), NOT_FOUND.
    """
    rozlozeny = rozloz_kod(vstup.kod)
    typ = domena.cil_blokace(rozlozeny.typ)
    box = _box_podle_kodu(rozlozeny.kod_boxu)
    if rozlozeny.kod_urovne is not None:
        domena.over_adresu(rozlozeny.kod_pracoviste or "", rozlozeny.kod_regalu or "", rozlozeny.kod_urovne,
                           box.kod_boxu, box.full_box_klic)
    if typ == "BOX":
        kod, pozice_id, puvodne = box.kod_boxu, None, box.blokovany
        nazev = f"Box {kod}"
    else:
        pozice = next((p for p in box.pozice if p.kod_pozice == rozlozeny.kod_pozice), None)
        if pozice is None:
            raise AppError("NOT_FOUND", f"Pozice {rozlozeny.kod_mista} neexistuje nebo není aktivní.")
        kod, pozice_id, puvodne = pozice.kod, pozice.vnitrni_pozice_id, pozice.blokovana
        nazev = f"Pozice {kod}"
    varovani = ()
    if puvodne == vstup.blokovat:
        stav = "blokovaná" if vstup.blokovat else "odblokovaná"
        varovani = (Varovani(VAROVANI_BEZ_ZMENY, f"{nazev} už je {stav}, nic se nezměnilo."),)
    return BlokaceVysledek(typ=typ, kod=kod, box_id=box.box_id, vnitrni_pozice_id=pozice_id,
                           blokovano=vstup.blokovat, zmeneno=puvodne != vstup.blokovat, varovani=varovani)


# --- pracoviště, regály, úrovně (BOX_EDIT) ---------------------------------------------------------------


@transakce("PRACOVISTE_ZALOZENI")
def zaloz_pracoviste(spoj: Spojeni, vstup: NovePracovisteVstup, kdo: Kontext) -> PracovisteRadek:
    """Chyby: VALIDATION_ERROR (kód), ALREADY_EXISTS."""
    from . import ukazky  # KOSTRA (fáze 0)

    kod = domena.normalizuj_kod_pracoviste(vstup.kod_pracoviste)
    if any(p.kod_pracoviste == kod for p in ukazky.PRACOVISTE):
        raise AppError("ALREADY_EXISTS", f"Pracoviště {kod} už existuje.")
    return PracovisteRadek(pracoviste_id=NOVE_ID, kod_pracoviste=kod, nazev=vstup.nazev, aktivni=True)


@transakce("PRACOVISTE_ZMENA")
def zmen_pracoviste(spoj: Spojeni, pracoviste_id: int, vstup: ZmenaPracovisteVstup, kdo: Kontext) -> PracovisteRadek:
    return _nacti_pracoviste(pracoviste_id).model_copy(update=vstup.zmenena_pole())


@transakce("PRACOVISTE_DEAKTIVACE")
def deaktivuj_pracoviste(spoj: Spojeni, pracoviste_id: int, vstup: DuvodVstup, kdo: Kontext) -> PracovisteRadek:
    """Chyby: NOT_EMPTY (pracoviště má aktivní regál), NOT_FOUND."""
    from . import ukazky  # KOSTRA (fáze 0)

    pracoviste = _nacti_pracoviste(pracoviste_id)
    regaly = [r.kod_regalu for r in ukazky.REGALY if r.pracoviste_id == pracoviste_id and r.aktivni]
    if regaly:
        raise AppError("NOT_EMPTY", f"Pracoviště {pracoviste.kod_pracoviste} má aktivní regály "
                                    f"{', '.join(regaly)}. Nejdřív je vyřaďte.")
    return pracoviste.model_copy(update={"aktivni": False})


@transakce("REGAL_ZALOZENI")
def zaloz_regal(spoj: Spojeni, vstup: NovyRegalVstup, kdo: Kontext) -> RegalRadek:
    """Chyby: VALIDATION_ERROR (kód), NOT_FOUND (pracoviště), ALREADY_EXISTS (kód na pracovišti)."""
    from . import ukazky  # KOSTRA (fáze 0)

    kod = domena.normalizuj_kod_regalu(vstup.kod_regalu)
    pracoviste = _nacti_pracoviste(vstup.pracoviste_id)
    if any(r.pracoviste_id == pracoviste.pracoviste_id and r.kod_regalu == kod for r in ukazky.REGALY):
        raise AppError("ALREADY_EXISTS", f"Regál {kod} na pracovišti {pracoviste.kod_pracoviste} už existuje.")
    return RegalRadek(regal_id=NOVE_ID, pracoviste_id=pracoviste.pracoviste_id,
                      kod_pracoviste=pracoviste.kod_pracoviste, kod_regalu=kod,
                      kod=domena.kod_regalu_barcode(pracoviste.kod_pracoviste, kod), nazev=vstup.nazev, aktivni=True)


@transakce("REGAL_ZMENA")
def zmen_regal(spoj: Spojeni, regal_id: int, vstup: ZmenaRegaluVstup, kdo: Kontext) -> RegalRadek:
    return _nacti_regal(regal_id).model_copy(update=vstup.zmenena_pole())


@transakce("REGAL_DEAKTIVACE")
def deaktivuj_regal(spoj: Spojeni, regal_id: int, vstup: DuvodVstup, kdo: Kontext) -> RegalRadek:
    """Chyby: NOT_EMPTY (regál má aktivní úroveň), NOT_FOUND."""
    from . import ukazky  # KOSTRA (fáze 0)

    regal = _nacti_regal(regal_id)
    urovne = [u.kod_urovne for u in ukazky.UROVNE if u.regal_id == regal_id and u.aktivni]
    if urovne:
        raise AppError("NOT_EMPTY", f"Regál {regal.kod} má aktivní úrovně {', '.join(urovne)}. Nejdřív je vyřaďte.")
    return regal.model_copy(update={"aktivni": False})


@transakce("UROVEN_ZALOZENI")
def zaloz_uroven(spoj: Spojeni, vstup: NovaUrovenVstup, kdo: Kontext) -> UrovenRadek:
    """Chyby: VALIDATION_ERROR (kód), NOT_FOUND (regál), ALREADY_EXISTS (kód na regálu)."""
    from . import ukazky  # KOSTRA (fáze 0)

    kod = domena.normalizuj_kod_urovne(vstup.kod_urovne)
    regal = _nacti_regal(vstup.regal_id)
    if any(u.regal_id == regal.regal_id and u.kod_urovne == kod for u in ukazky.UROVNE):
        raise AppError("ALREADY_EXISTS", f"Úroveň {kod} na regálu {regal.kod} už existuje.")
    poradi = vstup.poradi if vstup.poradi is not None else domena.poradi_z_kodu_urovne(kod)
    return UrovenRadek(uroven_id=NOVE_ID, regal_id=regal.regal_id, kod_urovne=kod, poradi=poradi,
                       delka_plochy_mm=vstup.delka_plochy_mm, hloubka_plochy_mm=vstup.hloubka_plochy_mm,
                       pocet_boxu=0, aktivni=True)


@transakce("UROVEN_ZMENA")
def zmen_uroven(spoj: Spojeni, uroven_id: int, vstup: ZmenaUrovneVstup, kdo: Kontext) -> UrovenRadek:
    """Rozměr plochy je jen informace (17.1): změna nepřepočítává SVG ani boxy."""
    return _nacti_uroven(uroven_id).model_copy(update=vstup.zmenena_pole())


@transakce("UROVEN_DEAKTIVACE")
def deaktivuj_uroven(spoj: Spojeni, uroven_id: int, vstup: DuvodVstup, kdo: Kontext) -> UrovenRadek:
    """Chyby: NOT_EMPTY (na úrovni stojí aktivní box), NOT_FOUND."""
    uroven = _nacti_uroven(uroven_id)
    boxy = [b.kod_boxu for b in _boxy_na_urovni(uroven_id)]
    if boxy:
        raise AppError("NOT_EMPTY", f"Na úrovni {uroven.kod_urovne} stojí boxy {', '.join(boxy)}. "
                                    "Nejdřív je přesuňte nebo vyřaďte.")
    return uroven.model_copy(update={"aktivni": False})


# --- operace s boxem (BOX_EDIT) ----------------------------------------------------------------------


@transakce("BOX_ZALOZENI")
def zaloz_box(spoj: Spojeni, uroven_id: int, vstup: NovyBoxVstup, kdo: Kontext) -> BoxDetail:
    """Pozice (pořadí na úrovni) + Box + vnitřní pozice ze šablony. Boxy od zvoleného pořadí se posunou.

    Chyby: NOT_FOUND (úroveň, členění), VALIDATION_ERROR (pořadí, číslo), ALREADY_EXISTS (kód boxu),
    BOX_SERIES_FULL.
    """
    uroven = _nacti_uroven(uroven_id)
    regal = _nacti_regal(uroven.regal_id)
    kod = _novy_kod_boxu(vstup.typ_boxu, regal.kod_pracoviste, vstup.cislo_boxu)
    cleneni = _nacti_cleneni(vstup.cleneni_id)
    poradi = domena.vloz_do_poradi([b.box_id for b in _boxy_na_urovni(uroven_id)], NOVE_ID, vstup.poradi)
    rozmer = Rozmer(vstup.delka_mm, vstup.hloubka_mm)
    return BoxDetail(
        box_id=NOVE_ID, kod_boxu=kod, typ_boxu=vstup.typ_boxu, cleneni_id=cleneni.cleneni_id,
        kod_cleneni=cleneni.kod_cleneni, delka_mm=vstup.delka_mm, hloubka_mm=vstup.hloubka_mm,
        full_box_klic=domena.full_box_klic(regal.kod_pracoviste, regal.kod_regalu, uroven.kod_urovne, kod),
        blokovany=False, aktivni=True, poradi=poradi.index(NOVE_ID) + 1,
        kod_pozice_urovne=domena.kod_pozice_urovne(poradi.index(NOVE_ID) + 1),
        uroven_id=uroven.uroven_id, kod_urovne=uroven.kod_urovne, regal_id=regal.regal_id,
        kod_regalu=regal.kod_regalu, pracoviste_id=regal.pracoviste_id, kod_pracoviste=regal.kod_pracoviste,
        pozice=_nove_pozice(kod, vstup.typ_boxu, cleneni.kod_cleneni, rozmer),
    )


@transakce("BOX_VYMENA")
def vymen_box(spoj: Spojeni, box_id: int, vstup: VymenaBoxuVstup, kdo: Kontext) -> BoxDetail:
    """Nový box na stejné Pozici (PoziceID i pořadí zůstávají); starý prázdný box Aktivni = 0 (Q-04).

    Chyby: NOT_FOUND, NOT_EMPTY (obsah nebo STAT přiřazení), ALREADY_EXISTS, BOX_SERIES_FULL.
    """
    stary = _nacti_box(box_id)
    kod = _novy_kod_boxu(vstup.typ_boxu, stary.kod_pracoviste, vstup.cislo_boxu)
    cleneni = _nacti_cleneni(vstup.cleneni_id)
    _over_prazdny(stary)
    return stary.model_copy(update={
        "box_id": NOVE_ID, "kod_boxu": kod, "typ_boxu": vstup.typ_boxu, "cleneni_id": cleneni.cleneni_id,
        "kod_cleneni": cleneni.kod_cleneni, "delka_mm": vstup.delka_mm, "hloubka_mm": vstup.hloubka_mm,
        "full_box_klic": domena.full_box_klic(stary.kod_pracoviste, stary.kod_regalu, stary.kod_urovne, kod),
        "blokovany": False,
        "pozice": _nove_pozice(kod, vstup.typ_boxu, cleneni.kod_cleneni, Rozmer(vstup.delka_mm, vstup.hloubka_mm)),
    })


@transakce("BOX_PRESUN")
def presun_box(spoj: Spojeni, box_id: int, vstup: PresunBoxuVstup, kdo: Kontext) -> BoxDetail:
    """Box i s obsahem na jinou úroveň, bez skladového pohybu; obsah zůstává na svých pozicích.

    Stará Pozice se vyřadí a zbytek její úrovně se přečísluje; na cílové úrovni se boxy od zvoleného
    pořadí posunou. FullBoxKlic se přepočítá (Q-03), barcode pozic (BPLE037-A) se nemění (Q-02).
    Chyby: NOT_FOUND, VALIDATION_ERROR (stejná úroveň, cizí pracoviště DYN boxu – Q-30, pořadí).
    """
    box = _nacti_box(box_id)
    cil = _nacti_uroven(vstup.cil_uroven_id)
    regal = _nacti_regal(cil.regal_id)
    if cil.uroven_id == box.uroven_id:
        raise chyba_vstupu("Box už na této úrovni stojí.",
                           {"cilUrovenId": "Pořadí na stejné úrovni se mění přes POST /boxy/{id}/poradi."})
    domena.over_presun_boxu(box.typ_boxu, box.kod_boxu, regal.kod_pracoviste)
    poradi = domena.vloz_do_poradi([b.box_id for b in _boxy_na_urovni(cil.uroven_id)], box.box_id, vstup.poradi)
    nove_poradi = poradi.index(box.box_id) + 1
    return box.model_copy(update={
        "uroven_id": cil.uroven_id, "kod_urovne": cil.kod_urovne, "regal_id": regal.regal_id,
        "kod_regalu": regal.kod_regalu, "poradi": nove_poradi,
        "kod_pozice_urovne": domena.kod_pozice_urovne(nove_poradi),
        "full_box_klic": domena.full_box_klic(regal.kod_pracoviste, regal.kod_regalu, cil.kod_urovne, box.kod_boxu),
    })


@transakce("BOX_PORADI")
def zmen_poradi_boxu(spoj: Spojeni, box_id: int, vstup: PoradiBoxuVstup, kdo: Kontext) -> Seznam[BoxNaUrovni]:
    """Přesune box na nové pořadí v rámci jeho úrovně; vrací celou úroveň v novém pořadí."""
    box = _nacti_box(box_id)
    boxy = {b.box_id: b for b in _boxy_na_urovni(box.uroven_id)}
    poradi = domena.presun_v_poradi(list(boxy), box.box_id, vstup.nove_poradi)
    return Seznam[BoxNaUrovni](polozky=[_na_urovni(boxy[i], n) for n, i in enumerate(poradi, start=1)])


@transakce("BOX_REKONFIGURACE")
def rekonfiguruj_box(spoj: Spojeni, box_id: int, vstup: RekonfiguraceVstup, kdo: Kontext) -> BoxDetail:
    """Staré vnitřní pozice Aktivni = 0, nové ze šablony; štítky pozic se tisknou znovu (Q-27, A-14).

    Chyby: NOT_FOUND, VALIDATION_ERROR (stejné členění), NOT_EMPTY (obsah nebo STAT přiřazení).
    """
    box = _nacti_box(box_id)
    cleneni = _nacti_cleneni(vstup.cleneni_id)
    domena.over_rekonfiguraci(box.kod_cleneni, cleneni.kod_cleneni)
    _over_prazdny(box)
    return box.model_copy(update={
        "cleneni_id": cleneni.cleneni_id, "kod_cleneni": cleneni.kod_cleneni,
        "pozice": _nove_pozice(box.kod_boxu, box.typ_boxu, cleneni.kod_cleneni, Rozmer(box.delka_mm, box.hloubka_mm)),
    })


@transakce("BOX_DEAKTIVACE")
def deaktivuj_box(spoj: Spojeni, box_id: int, vstup: DuvodVstup, kdo: Kontext) -> BoxDetail:
    """Box i jeho Pozice Aktivni = 0, boxy vpravo se posunou doleva. Chyby: NOT_FOUND, NOT_EMPTY."""
    box = _nacti_box(box_id)
    _over_prazdny(box)
    return box.model_copy(update={"aktivni": False})


@transakce("C7_ROZMER")
def nastav_rozmer_c7(spoj: Spojeni, vnitrni_pozice_id: int, vstup: RozmerC7Vstup, kdo: Kontext
                     ) -> VnitrniPoziceDetail:
    """Nový rozměr variabilní pozice C7 (Q-01); jen u prázdné pozice. Chyby: NOT_FOUND, VALIDATION_ERROR, NOT_EMPTY."""
    from . import ukazky  # KOSTRA (fáze 0)

    box, pozice = _nacti_pozici(vnitrni_pozice_id)
    rozmer = domena.over_rozmer_c7(pozice.velikost, Rozmer(vstup.delka_mm, vstup.hloubka_mm),
                                   Rozmer(box.delka_mm, box.hloubka_mm))
    if pozice.vnitrni_pozice_id in ukazky.OBSAZENE_POZICE:
        raise AppError("NOT_EMPTY", f"Na pozici {pozice.kod} je zásoba. Rozměr C7 se mění jen u prázdné pozice.")
    return _detail_pozice(box, pozice.model_copy(update={"rozmer_c7_delka_mm": rozmer.delka_mm,
                                                         "rozmer_c7_hloubka_mm": rozmer.hloubka_mm}))


# --- pomocné -------------------------------------------------------------------------------------


def _aktivita(aktivni: bool, filtr: bool | None) -> bool:
    return filtr is None or aktivni == filtr


def _nacti_pracoviste(pracoviste_id: int) -> PracovisteRadek:
    from . import ukazky  # KOSTRA (fáze 0)

    for pracoviste in ukazky.PRACOVISTE:
        if pracoviste.pracoviste_id == pracoviste_id:
            return pracoviste
    raise AppError("NOT_FOUND", f"Pracoviště {pracoviste_id} neexistuje.")


def _nacti_regal(regal_id: int) -> RegalRadek:
    from . import ukazky  # KOSTRA (fáze 0)

    for regal in ukazky.REGALY:
        if regal.regal_id == regal_id:
            return regal
    raise AppError("NOT_FOUND", f"Regál {regal_id} neexistuje.")


def _nacti_uroven(uroven_id: int) -> UrovenRadek:
    from . import ukazky  # KOSTRA (fáze 0)

    for uroven in ukazky.UROVNE:
        if uroven.uroven_id == uroven_id:
            return uroven
    raise AppError("NOT_FOUND", f"Úroveň {uroven_id} neexistuje.")


def _nacti_cleneni(cleneni_id: int) -> CleneniRadek:
    from . import ukazky  # KOSTRA (fáze 0)

    for cleneni in ukazky.CLENENI:
        if cleneni.cleneni_id == cleneni_id:
            return cleneni
    raise AppError("NOT_FOUND", f"Členění {cleneni_id} neexistuje (povolené C1–C7).")


def _nacti_box(box_id: int) -> BoxDetail:
    """Fáze 1: repozitar.nacti_box(spoj, box_id) nad Box + v_Misto."""
    from . import ukazky  # KOSTRA (fáze 0)

    box = ukazky.BOXY.get(box_id)
    if box is None:
        raise AppError("NOT_FOUND", f"Box {box_id} neexistuje.")
    return box


def _box_podle_kodu(kod_boxu: str | None) -> BoxDetail:
    from . import ukazky  # KOSTRA (fáze 0)

    box = next((b for b in ukazky.BOXY.values() if b.kod_boxu == kod_boxu and b.aktivni), None)
    if box is None:
        raise AppError("NOT_FOUND", f"Box {kod_boxu} neexistuje nebo není aktivní.")
    return box


def _nacti_pozici(vnitrni_pozice_id: int) -> tuple[BoxDetail, VnitrniPoziceRadek]:
    from . import ukazky  # KOSTRA (fáze 0)

    for box in ukazky.BOXY.values():
        for pozice in box.pozice:
            if pozice.vnitrni_pozice_id == vnitrni_pozice_id and box.aktivni:
                return box, pozice
    raise AppError("NOT_FOUND", f"Pozice {vnitrni_pozice_id} neexistuje nebo není aktivní.")


def _boxy_na_urovni(uroven_id: int) -> list[BoxDetail]:
    from . import ukazky  # KOSTRA (fáze 0)

    return sorted((b for b in ukazky.BOXY.values() if b.uroven_id == uroven_id and b.aktivni), key=lambda b: b.poradi)


def _na_urovni(box: BoxDetail, poradi: int) -> BoxNaUrovni:
    return BoxNaUrovni(box_id=box.box_id, kod_boxu=box.kod_boxu, typ_boxu=box.typ_boxu, kod_cleneni=box.kod_cleneni,
                       poradi=poradi, kod_pozice_urovne=domena.kod_pozice_urovne(poradi), blokovany=box.blokovany)


def _detail_pozice(box: BoxDetail, pozice: VnitrniPoziceRadek) -> VnitrniPoziceDetail:
    return VnitrniPoziceDetail(
        **pozice.model_dump(exclude={"transakce_id", "varovani"}),
        blokovano=box.blokovany or pozice.blokovana, adresa=f"{box.full_box_klic}-{pozice.kod_pozice}",
        box_id=box.box_id, kod_boxu=box.kod_boxu, typ_boxu=box.typ_boxu, kod_cleneni=box.kod_cleneni,
        box_blokovany=box.blokovany, uroven_id=box.uroven_id, regal_id=box.regal_id,
        pracoviste_id=box.pracoviste_id, kod_pracoviste=box.kod_pracoviste)


def _novy_kod_boxu(typ_boxu: str, kod_pracoviste: str, cislo: int | None) -> str:
    """Kód nového boxu z řady (11.2.1). Chyby: ALREADY_EXISTS (číslo už bylo vydáno), BOX_SERIES_FULL."""
    from . import ukazky  # KOSTRA (fáze 0)

    rada = domena.rada_boxu(typ_boxu, kod_pracoviste)
    pouzita = ukazky.POUZITA_CISLA.get(rada, set())
    if cislo is not None and cislo in pouzita:
        raise AppError("ALREADY_EXISTS", f"Box {domena.kod_boxu(typ_boxu, kod_pracoviste, cislo)} už existuje "
                                         "nebo existoval; kód ze štítku se znovu nepoužívá.")
    return domena.kod_boxu(typ_boxu, kod_pracoviste, cislo if cislo is not None else domena.dalsi_cislo_boxu(pouzita))


def _nove_pozice(kod_boxu: str, typ_boxu: str, kod_cleneni: str, rozmer_boxu: Rozmer) -> list[VnitrniPoziceRadek]:
    """Vnitřní pozice ze šablony; variabilní C7 dostane výchozí rozměr = vnitřek boxu (upraví /rozmer-c7)."""
    from . import ukazky  # KOSTRA (fáze 0)

    return [
        VnitrniPoziceRadek(
            vnitrni_pozice_id=NOVE_ID_POZICE + i, kod_pozice=p.kod_pozice, kod=f"{kod_boxu}-{p.kod_pozice}",
            velikost=p.velikost, poradi_v_boxu=p.poradi_v_boxu,
            rozmer_c7_delka_mm=rozmer_boxu.delka_mm if p.velikost == domena.VELIKOST_C7 else None,
            rozmer_c7_hloubka_mm=rozmer_boxu.hloubka_mm if p.velikost == domena.VELIKOST_C7 else None,
            blokovana=False)
        for i, p in enumerate(domena.pozice_ze_sablony(typ_boxu, ukazky.PRIHRADKY[kod_cleneni]))
    ]


def _over_prazdny(box: BoxDetail) -> None:
    """Strukturální změna jen u boxu bez zásoby a bez statického přiřazení (analýza 9.7, Q-27).

    Fáze 1: v_ObsahPozice a v_StatickeMisto ostrova E po zamkni_mista. Chyby: NOT_EMPTY.
    """
    from . import ukazky  # KOSTRA (fáze 0)

    obsazene = [p.kod for p in box.pozice if p.vnitrni_pozice_id in ukazky.OBSAZENE_POZICE]
    prirazene = [p.kod for p in box.pozice if p.vnitrni_pozice_id in ukazky.STAT_PRIRAZENE_POZICE]
    if obsazene or prirazene:
        duvody = ([f"zásoba na {', '.join(obsazene)}"] if obsazene else []) \
            + ([f"statické přiřazení na {', '.join(prirazene)}"] if prirazene else [])
        raise AppError("NOT_EMPTY", f"Box {box.kod_boxu} není volný: {'; '.join(duvody)}. "
                                    "Nejdřív zásobu vyskladněte a přiřazení ukončete.")
