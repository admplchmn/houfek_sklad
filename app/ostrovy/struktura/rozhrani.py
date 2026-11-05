"""VEŘEJNÉ ROZHRANÍ ostrova C – Struktura skladu a kódy (sekce 7.3).

KDE: každé fyzické místo, jeho kód, velikost a blokace. Jediné místo s formátem kódů
(parser i tisk štítků) a se zámky pozic.

Čisté funkce (rozloz_kod, vejde_se, stav_boxu) jsou hotové podle analýzy 5.1 a 8.1.
Funkce nad DB jsou ve fázi 1 stále kostra se vzorovými daty (import ukazky uvnitř funkce),
aby testy ostatních ostrovů běžely nad stabilními vzorky; skutečné SQL už mají zamkni_mista
(protokol) a zakládání pracoviště, regálu, úrovně a boxu – to je hotové přes repozitar.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.platforma.chyby import AppError
from app.platforma.db import Spojeni, po_davkach
from app.platforma.typy import Kontext, PolozkaCiselniku, PotrebaMista, Rozmer

from . import domena, repozitar

# --- DTO -------------------------------------------------------------------------------


@dataclass(frozen=True)
class RozlozenyKod:
    """Výsledek parseru. typ: REGAL | BOX | POZICE | TEXT (není kód skladu → hledání dílu)."""

    typ: str
    text: str                        # normalizovaný vstup
    typ_boxu: str | None = None      # "DYN" | "STAT"
    kod_pracoviste: str | None = None
    kod_regalu: str | None = None
    kod_urovne: str | None = None    # jen u dlouhého tvaru
    kod_boxu: str | None = None      # "BPLE037"
    kod_pozice: str | None = None    # "A", "CH", "1"

    @property
    def kod_mista(self) -> str | None:
        """Krátký kanonický kód pozice, např. BPLE037-A (Q-02)."""
        return f"{self.kod_boxu}-{self.kod_pozice}" if self.kod_boxu and self.kod_pozice else None


@dataclass(frozen=True)
class MistoInfo:
    """Jedna aktivní vnitřní pozice – skutečné skladové místo."""

    vnitrni_pozice_id: int
    box_id: int
    kod: str                   # "BPLE037-A" – fyzický barcode pozice
    kod_boxu: str              # "BPLE037"
    kod_pozice: str            # "A"
    typ_boxu: str              # "DYN" | "STAT"
    velikost: str              # "V1" … "V6"
    rozmer_c7: Rozmer | None   # jen u V6
    blokovano: bool            # blokovaný box NEBO pozice
    poradi_v_boxu: int         # pořadí kandidátů v boxu (šablona, česká abeceda)
    pracoviste: str            # "PLE"
    regal_id: int
    uroven_id: int
    adresa: str                # "HOUFEK-PLE-R01-U03-BPLE037-A"
    box_blokovany: bool = False   # blokovaný celý box (pro stav boxu VOLNY | OBSAZENY | BLOKOVANY)


@dataclass(frozen=True)
class NalezenyObjekt:
    """Co je naskenovaný kód. typ: REGAL | BOX | POZICE."""

    typ: str
    kod: str
    adresa: str
    regal_id: int
    uroven_id: int | None = None
    box_id: int | None = None
    vnitrni_pozice_id: int | None = None


@dataclass(frozen=True)
class PoziceVRozlozeni:
    vnitrni_pozice_id: int
    kod_pozice: str
    velikost: str
    blokovano: bool
    rel_x: float               # poloha přihrádky v boxu 0–1 (šablona členění)
    rel_y: float
    rel_sirka: float
    rel_hloubka: float


@dataclass(frozen=True)
class BoxVRozlozeni:
    box_id: int
    kod_boxu: str
    typ_boxu: str
    kod_cleneni: str
    blokovany: bool
    x_mm: float                # levý okraj boxu v SVG (pravidla 17.1)
    y_mm: float
    delka_mm: float
    hloubka_mm: float
    pozice: tuple[PoziceVRozlozeni, ...]
    kod_pozice_urovne: str     # "P01" – Pozice boxu na úrovni, pořadí zleva doprava (kap. 6.2, 17.2)


@dataclass(frozen=True)
class RozlozeniUrovne:
    """Geometrie úrovně pro SVG – bez obsahu (obsah a barvy doplní ostrov Přehledy)."""

    uroven_id: int
    kod_urovne: str
    regal_id: int
    kod_regalu: str
    pracoviste: str
    delka_plochy_mm: float     # jen informace, SVG se počítá z boxů
    hloubka_plochy_mm: float
    sirka_svg_mm: float
    vyska_svg_mm: float
    boxy: tuple[BoxVRozlozeni, ...]


# --- čisté funkce (hotové) -------------------------------------------------------------------

_POZICE = r"(CH|[A-R]|[1-9]\d?)"
_VZORY = [
    ("POZICE_STAT", re.compile(r"BSTAT(\d{3})-([1-9]\d?)")),
    ("BOX_STAT", re.compile(r"BSTAT(\d{3})")),
    ("POZICE_DYN", re.compile(r"B([0-9A-Z]{3})(\d{3})-(CH|[A-R])")),
    ("BOX_DYN", re.compile(r"B([0-9A-Z]{3})(\d{3})")),
    ("REGAL", re.compile(r"HOUFEK-([0-9A-Z]{3})-(R\d{2})")),
    ("DLOUHY", re.compile(r"HOUFEK-([0-9A-Z]{3})-(R\d{2})-(U\d{2})-(B[0-9A-Z]+?)(?:-" + _POZICE + r")?")),
]


def _normalizuj(kod: str) -> str:
    return re.sub(r"\s+", " ", kod or "").strip().upper()


def rozloz_kod(kod: str) -> RozlozenyKod:
    """Čistý parser kódů (analýza 5.1). Nikdy nevyvolá chybu: neznámý vstup = typ TEXT."""
    text = _normalizuj(kod)
    for nazev, vzor in _VZORY:
        nalez = vzor.fullmatch(text)
        if not nalez:
            continue
        if nazev == "POZICE_STAT":
            return RozlozenyKod("POZICE", text, "STAT", None, None, None, f"BSTAT{nalez[1]}", nalez[2])
        if nazev == "BOX_STAT":
            return RozlozenyKod("BOX", text, "STAT", None, None, None, text, None)
        if nazev == "POZICE_DYN":
            return RozlozenyKod("POZICE", text, "DYN", nalez[1], None, None, f"B{nalez[1]}{nalez[2]}", nalez[3])
        if nazev == "BOX_DYN":
            return RozlozenyKod("BOX", text, "DYN", nalez[1], None, None, text, None)
        if nazev == "REGAL":
            return RozlozenyKod("REGAL", text, None, nalez[1], nalez[2])
        # dlouhý tvar: rozloží se box/pozice a doplní adresa pro kontrolu proti skutečnosti (Q-02)
        vnitrni = rozloz_kod(nalez[4] + (f"-{nalez[5]}" if nalez[5] else ""))
        if vnitrni.typ not in ("BOX", "POZICE"):
            break
        if vnitrni.typ_boxu == "DYN" and vnitrni.kod_pracoviste != nalez[1]:
            break   # BPLE… v adrese jiného pracoviště je neplatná adresa
        return RozlozenyKod(vnitrni.typ, text, vnitrni.typ_boxu, nalez[1], nalez[2], nalez[3],
                            vnitrni.kod_boxu, vnitrni.kod_pozice)
    return RozlozenyKod("TEXT", text)


def vejde_se(misto: MistoInfo, potreba: PotrebaMista) -> bool:
    """Pravidlo kap. 8.1 a Q-01: stejná velikost; u V6 se požadovaný rozměr vejde do aktuálního C7."""
    if misto.velikost != potreba.velikost:
        return False
    if potreba.velikost != "V6":
        return True
    if misto.rozmer_c7 is None or potreba.rozmer is None:
        return False
    return (potreba.rozmer.delka_mm <= misto.rozmer_c7.delka_mm
            and potreba.rozmer.hloubka_mm <= misto.rozmer_c7.hloubka_mm)


def stav_boxu(blokovany: bool, pocet_obsazenych: int) -> str:
    """VOLNY | OBSAZENY | BLOKOVANY (priorita z analýzy 5.9). Barvu z něj určí ostrov Přehledy."""
    if blokovany:
        return "BLOKOVANY"
    return "OBSAZENY" if pocet_obsazenych > 0 else "VOLNY"


# --- zámky (hotové – protokol, sekce 5.3, docs/adr/0005) ------------------------------------

_ZAMKY_PO_JEDNOM = 20   # nad tímto počtem jeden dotaz (SQL Server má limit 2100 parametrů)

def zamkni_mista(spoj: Spojeni, vnitrni_pozice_ids: list[int]) -> None:
    """Zamkne pozice do konce transakce (UPDLOCK, HOLDLOCK), vzestupně podle ID.

    Volá se jednou na začátku operace pro všechna dotčená místa, ještě před čtením obsahu.
    Chyby: NOT_FOUND, pokud některá pozice neexistuje.
    """
    ids = sorted(set(vnitrni_pozice_ids))
    if not ids:
        return
    if spoj.dialekt != "mssql":
        return   # sqlite v testech zamyká celou databázi při zápisu
    if len(ids) <= _ZAMKY_PO_JEDNOM:
        # Po jednom řádku vzestupně: pořadí zámků je zaručené (u IN (…) ho určuje plán dotazu),
        # takže přesun A→B a současně B→A na sebe nikdy nenarazí do kříže.
        for vnitrni_pozice_id in ids:
            if spoj.jeden("SELECT VnitrniPoziceID FROM dbo.VnitrniPoziceBoxu WITH (UPDLOCK, HOLDLOCK)"
                          " WHERE VnitrniPoziceID = ?", vnitrni_pozice_id) is None:
                raise AppError("NOT_FOUND", f"Pozice {vnitrni_pozice_id} neexistuje.")
        return
    # Velké sady (inventura): po dávkách vzestupně; případný deadlock řeší opakování v @transakce.
    nalezeno = 0
    for davka in po_davkach(ids):
        znacky = ", ".join("?" for _ in davka)
        nalezeno += len(spoj.dotaz(
            f"SELECT VnitrniPoziceID FROM dbo.VnitrniPoziceBoxu WITH (UPDLOCK, HOLDLOCK)"
            f" WHERE VnitrniPoziceID IN ({znacky}) ORDER BY VnitrniPoziceID", *davka))
    if nalezeno != len(ids):
        raise AppError("NOT_FOUND", "Některá pozice neexistuje.")


# --- funkce nad DB (fáze 0: kostra se vzorovými daty) ----------------------------------------
# Rozbor kódu, kontrola úrovně skenu a dlouhé adresy jsou hotové (_kod_pozice, _over_dlouhou_adresu);
# kostra je jen hledání ve vzorových datech místo dotazu na v_Misto.

def najdi_objekt(spoj: Spojeni, kod: str) -> NalezenyObjekt:
    """Přeloží kód regálu, boxu nebo pozice na objekt (pro sken). Chyby: INVALID_BARCODE, NOT_FOUND."""
    rozlozeny = rozloz_kod(kod)
    if rozlozeny.typ == "TEXT":
        raise AppError("INVALID_BARCODE", f"Kód {rozlozeny.text!r} neodpovídá žádnému kódu skladu.")
    from . import ukazky  # KOSTRA (fáze 0)

    if rozlozeny.typ == "REGAL":
        regal = next((r for r in ukazky.REGALY if r.kod == rozlozeny.text and r.aktivni), None)
        if regal is None:
            raise AppError("NOT_FOUND", f"Regál {rozlozeny.text} neexistuje nebo není aktivní.")
        return NalezenyObjekt("REGAL", regal.kod, regal.kod, regal.regal_id)
    box = next((b for b in ukazky.BOXY.values() if b.kod_boxu == rozlozeny.kod_boxu and b.aktivni), None)
    if box is None:
        raise AppError("NOT_FOUND", f"Box {rozlozeny.kod_boxu} neexistuje nebo není aktivní.")
    _over_dlouhou_adresu(rozlozeny, box.full_box_klic)
    if rozlozeny.typ == "BOX":
        return NalezenyObjekt("BOX", box.kod_boxu, box.full_box_klic, box.regal_id, box.uroven_id, box.box_id)
    misto = _misto_podle_kodu(rozlozeny.kod_mista)
    return NalezenyObjekt("POZICE", misto.kod, misto.adresa, misto.regal_id, misto.uroven_id, misto.box_id,
                          misto.vnitrni_pozice_id)


def najdi_vnitrni_pozici(spoj: Spojeni, kod: str) -> MistoInfo:
    """Přeloží naskenovaný kód na aktivní vnitřní pozici.

    Chyby: INVALID_BARCODE, NOT_FOUND, WRONG_SCAN_LEVEL (naskenován celý box nebo regál).
    """
    rozlozeny = _kod_pozice(kod)
    misto = _misto_podle_kodu(rozlozeny.kod_mista)
    if rozlozeny.kod_urovne is not None:
        _over_dlouhou_adresu(rozlozeny, misto.adresa.rsplit("-", 1)[0])
    return misto


def nacti_mista(spoj: Spojeni, vnitrni_pozice_ids: list[int]) -> dict[int, MistoInfo]:
    """Hromadné načtení míst podle ID; neaktivní nebo neexistující ve výsledku chybí."""
    from . import ukazky  # KOSTRA (fáze 0)

    return {i: ukazky.MISTA[i] for i in vnitrni_pozice_ids if i in ukazky.MISTA}


def kandidatni_mista_dyn(spoj: Spojeni, regal_id: int, velikost: str, *,
                         cele_pracoviste: bool = False) -> list[MistoInfo]:
    """Aktivní neblokované DYN pozice dané velikosti na regálu, seřazené podle čísla boxu
    a pořadí v boxu (21.1.3). Obsah neřeší – volná místa vybere ostrov Sklad.

    cele_pracoviste=True: i z ostatních regálů pracoviště zvoleného regálu (Q-10). Chyby: NOT_FOUND (regál).
    """
    from . import ukazky  # KOSTRA (fáze 0)

    regal = next((r for r in ukazky.REGALY if r.regal_id == regal_id and r.aktivni), None)
    if regal is None:
        raise AppError("NOT_FOUND", f"Regál {regal_id} neexistuje nebo není aktivní.")
    mista = [m for m in ukazky.MISTA.values()
             if (m.regal_id == regal_id or (cele_pracoviste and m.pracoviste == regal.kod_pracoviste))
             and m.typ_boxu == "DYN" and m.velikost == velikost and not m.blokovano]
    return sorted(mista, key=lambda m: (domena.cislo_boxu(m.kod_boxu), m.poradi_v_boxu))


ROZSAHY_INVENTURY = ("FULL", "PRAC", "REGAL", "UROVEN", "BOX", "POZICE")


def pozice_v_rozsahu(spoj: Spojeni, typ_rozsahu: str, cil_id: int | None) -> list[int]:
    """ID aktivních vnitřních pozic v rozsahu inventury.

    typ_rozsahu: FULL | PRAC | REGAL | UROVEN | BOX | POZICE (cil_id je ID podle typu, u FULL None).
    Chyby: VALIDATION_ERROR (neznámý typ, chybějící nebo přebývající cíl), NOT_FOUND.
    """
    if typ_rozsahu not in ROZSAHY_INVENTURY:
        raise AppError("VALIDATION_ERROR", f"Neznámý rozsah {typ_rozsahu!r}. Povolené: {', '.join(ROZSAHY_INVENTURY)}.")
    if (typ_rozsahu == "FULL") != (cil_id is None):
        raise AppError("VALIDATION_ERROR", "Celá inventura (FULL) nemá cíl, ostatní rozsahy ho mají povinný.")
    from . import ukazky  # KOSTRA (fáze 0)

    klic = {"PRAC": "pracoviste_id", "REGAL": "regal_id", "UROVEN": "uroven_id", "BOX": "box_id"}.get(typ_rozsahu)
    ids = sorted(p.vnitrni_pozice_id for b in ukazky.BOXY.values() if b.aktivni for p in b.pozice
                 if typ_rozsahu == "FULL" or (klic and getattr(b, klic) == cil_id)
                 or (typ_rozsahu == "POZICE" and p.vnitrni_pozice_id == cil_id))
    if not ids and typ_rozsahu != "FULL":
        raise AppError("NOT_FOUND", f"Rozsah {typ_rozsahu} {cil_id} neobsahuje žádnou aktivní pozici.")
    return ids


def rozlozeni_urovne(spoj: Spojeni, uroven_id: int) -> RozlozeniUrovne:
    """Geometrie úrovně v mm pro SVG (pravidla 17.1). Chyby: NOT_FOUND."""
    from . import ukazky  # KOSTRA (fáze 0)

    uroven = next((u for u in ukazky.UROVNE if u.uroven_id == uroven_id), None)
    if uroven is None:
        raise AppError("NOT_FOUND", f"Úroveň {uroven_id} neexistuje.")
    regal = next(r for r in ukazky.REGALY if r.regal_id == uroven.regal_id)
    boxy = sorted((b for b in ukazky.BOXY.values() if b.uroven_id == uroven_id and b.aktivni), key=lambda b: b.poradi)
    sablony = {c.kod_cleneni: c.pozice for c in ukazky.CLENENI}
    return _sestav_rozlozeni(uroven_id=uroven.uroven_id, kod_urovne=uroven.kod_urovne, regal_id=regal.regal_id,
                            kod_regalu=regal.kod_regalu, pracoviste=regal.kod_pracoviste,
                            plocha=Rozmer(uroven.delka_plochy_mm, uroven.hloubka_plochy_mm),
                            boxy=[(b, [(p, _geometrie(sablony[b.kod_cleneni], b.typ_boxu, p.kod_pozice))
                                       for p in b.pozice]) for b in boxy])


def nacti_ciselniky(spoj: Spojeni) -> dict[str, tuple[PolozkaCiselniku, ...]]:
    """Číselníky struktury pro filtry: "pracoviste" (kód PLE, název) a "velikosti" (V1–V6)."""
    from . import ukazky  # KOSTRA (fáze 0)

    return {
        "pracoviste": tuple(PolozkaCiselniku(p.pracoviste_id, p.kod_pracoviste, p.nazev, p.aktivni)
                            for p in ukazky.PRACOVISTE),
        "velikosti": tuple(PolozkaCiselniku(i, kod, nazev, True) for i, kod, nazev in ukazky.VELIKOSTI),
    }


def _sestav_rozlozeni(*, uroven_id: int, kod_urovne: str, regal_id: int, kod_regalu: str, pracoviste: str,
                     plocha: Rozmer, boxy: list) -> RozlozeniUrovne:
    """Složí DTO rozložení z boxů v pořadí Pozice.Poradi; souřadnice počítá domena.rozmisteni_boxu (17.1).

    boxy: [(box, [(pozice, (rel_x, rel_y, rel_sirka, rel_hloubka)), …]), …], box i pozice s atributy
    jako v pohledu v_Misto (box_id, kod_boxu, typ_boxu, kod_cleneni, blokovany, delka_mm, hloubka_mm, poradi;
    vnitrni_pozice_id, kod_pozice, velikost, blokovana). Hotové – repozitář fáze 1 dodá stejná data.
    """
    souradnice, sirka, vyska = domena.rozmisteni_boxu([Rozmer(b.delka_mm, b.hloubka_mm) for b, _ in boxy])
    return RozlozeniUrovne(
        uroven_id=uroven_id, kod_urovne=kod_urovne, regal_id=regal_id, kod_regalu=kod_regalu, pracoviste=pracoviste,
        delka_plochy_mm=float(plocha.delka_mm), hloubka_plochy_mm=float(plocha.hloubka_mm),
        sirka_svg_mm=float(sirka), vyska_svg_mm=float(vyska),
        boxy=tuple(
            BoxVRozlozeni(box_id=b.box_id, kod_boxu=b.kod_boxu, typ_boxu=b.typ_boxu, kod_cleneni=b.kod_cleneni,
                          blokovany=b.blokovany, x_mm=float(x), y_mm=float(y), delka_mm=float(b.delka_mm),
                          hloubka_mm=float(b.hloubka_mm),
                          pozice=tuple(PoziceVRozlozeni(p.vnitrni_pozice_id, p.kod_pozice, p.velikost, p.blokovana,
                                                        *geometrie) for p, geometrie in pozice),
                          kod_pozice_urovne=domena.kod_pozice_urovne(b.poradi))
            for (b, pozice), (x, y) in zip(boxy, souradnice, strict=True)),
    )


def _geometrie(prihradky: list, typ_boxu: str, kod_pozice: str) -> tuple[float, float, float, float]:
    """Poloha přihrádky v boxu ze šablony členění (DYN podle písmene, STAT podle čísla)."""
    for p in prihradky:
        if (p.dyn_kod if typ_boxu == "DYN" else p.stat_kod) == kod_pozice:
            return p.rel_x, p.rel_y, p.rel_sirka, p.rel_hloubka
    raise AppError("INTERNAL_ERROR", f"Pozice {kod_pozice} neodpovídá šabloně.")


def _kod_pozice(kod: str) -> RozlozenyKod:
    """Rozloží kód a ověří, že jde o pozici (hotové). Chyby: INVALID_BARCODE, WRONG_SCAN_LEVEL."""
    rozlozeny = rozloz_kod(kod)
    if rozlozeny.typ == "TEXT":
        raise AppError("INVALID_BARCODE", f"Kód {rozlozeny.text!r} neodpovídá žádnému kódu skladu.")
    if rozlozeny.typ == "REGAL":
        raise AppError("WRONG_SCAN_LEVEL", "Naskenujte štítek pozice, ne regál.")
    if rozlozeny.typ == "BOX":
        raise AppError("WRONG_SCAN_LEVEL", f"Naskenujte štítek pozice, ne celý box {rozlozeny.kod_boxu}.")
    return rozlozeny


def _over_dlouhou_adresu(rozlozeny: RozlozenyKod, ulozena_adresa_boxu: str) -> None:
    if rozlozeny.kod_urovne is not None and rozlozeny.kod_boxu is not None:
        domena.over_adresu(rozlozeny.kod_pracoviste or "", rozlozeny.kod_regalu or "", rozlozeny.kod_urovne,
                           rozlozeny.kod_boxu, ulozena_adresa_boxu)


def _misto_podle_kodu(kod_mista: str | None) -> MistoInfo:
    from . import ukazky  # KOSTRA (fáze 0)

    misto = next((m for m in ukazky.MISTA.values() if m.kod == kod_mista), None)
    if misto is None:
        raise AppError("NOT_FOUND", f"Pozice {kod_mista} neexistuje nebo není aktivní.")
    return misto


# --- zakládání (pro migraci; ve stejné transakci volajícího) -------------------------------

def zaloz_pracoviste(spoj: Spojeni, kdo: Kontext, kod_pracoviste: str, nazev: str | None) -> int:
    """Vrací PracovisteID. Chyby: ALREADY_EXISTS, VALIDATION_ERROR."""
    return repozitar.zaloz_pracoviste(spoj, kod_pracoviste, nazev)


def zaloz_regal(spoj: Spojeni, kdo: Kontext, pracoviste_id: int, kod_regalu: str, nazev: str | None) -> int:
    """Vrací RegalID. Chyby: ALREADY_EXISTS, NOT_FOUND."""
    return repozitar.zaloz_regal(spoj, pracoviste_id, kod_regalu, nazev)


def zaloz_uroven(spoj: Spojeni, kdo: Kontext, regal_id: int, kod_urovne: str, poradi: int,
                 delka_plochy_mm: float, hloubka_plochy_mm: float) -> int:
    """Vrací UrovenID. Chyby: ALREADY_EXISTS, NOT_FOUND, VALIDATION_ERROR."""
    return repozitar.zaloz_uroven(spoj, regal_id, kod_urovne, poradi, delka_plochy_mm, hloubka_plochy_mm)


def zaloz_box(spoj: Spojeni, kdo: Kontext, uroven_id: int, poradi: int | None, typ_boxu: str,
              kod_cleneni: str, delka_mm: float, hloubka_mm: float, kod_boxu: str | None = None) -> int:
    """Založí Pozici + Box + vnitřní pozice ze šablony v transakci volajícího. Vrací BoxID.

    poradi None = na konec úrovně; kod_boxu None = další volné číslo řady (11.2.1).
    Chyby: ALREADY_EXISTS, NOT_FOUND, VALIDATION_ERROR.
    """
    return repozitar.zaloz_box(spoj, uroven_id, poradi, typ_boxu, kod_cleneni, delka_mm, hloubka_mm, kod_boxu)
