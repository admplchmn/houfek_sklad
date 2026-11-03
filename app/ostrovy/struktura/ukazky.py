"""Vzorová data ostrova C pro kostru rozhraní, kostru služeb a testy spotřebitelů.

Malý, ale úplný kus skladu pracoviště PLE (ID odpovídají výchozím datům migrace 001):

    R01-U03  P01 BPLE037  DYN  C1  A (V1)                          obsazená
             P02 BPLE039  DYN  C1  A (V1)                          prázdný
    R01-U04  P01 BPLE052  DYN  C7  R (V6, C7 800 × 400 mm)          prázdný (výměna, rekonfigurace)
             P02 BPLE038  DYN  C4  G H CH I (V3)                    obsazená jen I
    R02-U01  P01 BSTAT037 STAT C4  4 3 1 2 (V3)                     STAT přiřazení: 1 (s obsahem), 2 (prázdná)
    1SV R01-U01  (prázdná úroveň jiného pracoviště – přesun DYN boxu sem je chyba, Q-30)

Obsah a statická přiřazení patří ostrovu E; ostrov C je čte z pohledů (v_ObsahPozice,
v_StatickeMisto), tady jsou jen jako dvě množiny ID.
"""
from __future__ import annotations

from decimal import Decimal

from app.platforma.kostra import jen_ve_vyvoji
from app.platforma.typy import Rozmer

from .domena import PrihradkaSablony
from .kontrakty import (
    BoxDetail,
    CleneniRadek,
    PracovisteRadek,
    RegalRadek,
    SablonaPozice,
    UrovenRadek,
    VnitrniPoziceRadek,
)
from .rozhrani import BoxVRozlozeni, MistoInfo, NalezenyObjekt, PoziceVRozlozeni, RozlozeniUrovne

jen_ve_vyvoji(__name__)  # v provozu vzorová data nikdy (app/platforma/kostra.py)

# --- číselníky a šablona členění (kopie výchozích dat migrace 001, shodu hlídá test) ----------------

PRACOVISTE = [PracovisteRadek(pracoviste_id=i, kod_pracoviste=k, nazev=n, aktivni=True)
              for i, (k, n) in enumerate([
                  ("PLE", "Plechotváření"), ("1SV", "Horní svařovna"), ("2SV", "Spodní svařovna"),
                  ("1MO", "Montáž konvenčních strojů"), ("2MO", "Montáž CNC strojů"), ("OBR", "Obrobna"),
                  ("1LA", "Horní lakovna"), ("2LA", "Spodní lakovna")], start=1)]

VELIKOSTI = [(1, "V1", "Velikost 1"), (2, "V2", "Velikost 2"), (3, "V3", "Velikost 3"), (4, "V4", "Velikost 4"),
             (5, "V5", "Velikost 5"), (6, "V6", "Velikost 6 – variabilní prostor C7")]

POCET_POZIC = {"C1": 1, "C2": 2, "C3": 3, "C4": 4, "C5": 2, "C6": 6, "C7": 1}
CLENENI_ID = {kod: i for i, kod in enumerate(POCET_POZIC, start=1)}

# konfigurace, DYN, STAT, pořadí, řada, sloupec, velikost, RelX, RelY, šířka, hloubka
SABLONA = [
    ("C1", "A", "1", 1, 1, 1, "V1", "0.0000", "0.0000", "1.0000", "1.0000"),
    ("C2", "B", "2", 1, 2, 1, "V2", "0.0000", "0.5000", "1.0000", "0.5000"),
    ("C2", "C", "1", 2, 1, 1, "V2", "0.0000", "0.0000", "1.0000", "0.5000"),
    ("C3", "D", "3", 1, 2, 1, "V2", "0.0000", "0.5000", "1.0000", "0.5000"),
    ("C3", "E", "1", 2, 1, 1, "V3", "0.0000", "0.0000", "0.5000", "0.5000"),
    ("C3", "F", "2", 3, 1, 2, "V3", "0.5000", "0.0000", "0.5000", "0.5000"),
    ("C4", "G", "4", 1, 2, 2, "V3", "0.5000", "0.5000", "0.5000", "0.5000"),
    ("C4", "H", "3", 2, 2, 1, "V3", "0.0000", "0.5000", "0.5000", "0.5000"),
    ("C4", "CH", "1", 3, 1, 1, "V3", "0.0000", "0.0000", "0.5000", "0.5000"),
    ("C4", "I", "2", 4, 1, 2, "V3", "0.5000", "0.0000", "0.5000", "0.5000"),
    ("C5", "J", "2", 1, 2, 1, "V4", "0.0000", "0.5000", "1.0000", "0.5000"),
    ("C5", "K", "1", 2, 1, 1, "V4", "0.0000", "0.0000", "1.0000", "0.5000"),
    ("C6", "L", "6", 1, 2, 3, "V5", "0.6667", "0.5000", "0.3333", "0.5000"),
    ("C6", "M", "5", 2, 2, 2, "V5", "0.3333", "0.5000", "0.3334", "0.5000"),
    ("C6", "N", "4", 3, 2, 1, "V5", "0.0000", "0.5000", "0.3333", "0.5000"),
    ("C6", "O", "1", 4, 1, 1, "V5", "0.0000", "0.0000", "0.3333", "0.5000"),
    ("C6", "P", "2", 5, 1, 2, "V5", "0.3333", "0.0000", "0.3334", "0.5000"),
    ("C6", "Q", "3", 6, 1, 3, "V5", "0.6667", "0.0000", "0.3333", "0.5000"),
    ("C7", "R", "1", 1, 1, 1, "V6", "0.0000", "0.0000", "1.0000", "1.0000"),
]

PRIHRADKY: dict[str, tuple[PrihradkaSablony, ...]] = {
    kod: tuple(PrihradkaSablony(i, r[1], r[2], r[3], r[6]) for i, r in enumerate(SABLONA, start=1) if r[0] == kod)
    for kod in POCET_POZIC
}

CLENENI = [
    CleneniRadek(cleneni_id=CLENENI_ID[kod], kod_cleneni=kod, pocet_pozic=pocet, pozice=[
        SablonaPozice(dyn_kod=r[1], stat_kod=r[2], poradi=r[3], rada=r[4], sloupec=r[5], velikost=r[6],
                      rel_x=float(r[7]), rel_y=float(r[8]), rel_sirka=float(r[9]), rel_hloubka=float(r[10]))
        for r in SABLONA if r[0] == kod])
    for kod, pocet in POCET_POZIC.items()
]

# --- regály, boxy a pozice pracoviště PLE ---------------------------------------------------------

REGALY = [
    RegalRadek(regal_id=1, pracoviste_id=1, kod_pracoviste="PLE", kod_regalu="R01", kod="HOUFEK-PLE-R01",
               nazev="Regál u lisů", aktivni=True),
    RegalRadek(regal_id=2, pracoviste_id=1, kod_pracoviste="PLE", kod_regalu="R02", kod="HOUFEK-PLE-R02",
               nazev=None, aktivni=True),
    RegalRadek(regal_id=3, pracoviste_id=2, kod_pracoviste="1SV", kod_regalu="R01", kod="HOUFEK-1SV-R01",
               nazev=None, aktivni=True),
]


def _pozice(vnitrni_pozice_id: int, kod_boxu: str, kod_pozice: str, velikost: str, poradi: int,
            c7: tuple[str, str] | None = None) -> VnitrniPoziceRadek:
    return VnitrniPoziceRadek(
        vnitrni_pozice_id=vnitrni_pozice_id, kod_pozice=kod_pozice, kod=f"{kod_boxu}-{kod_pozice}",
        velikost=velikost, poradi_v_boxu=poradi,
        rozmer_c7_delka_mm=Decimal(c7[0]) if c7 else None, rozmer_c7_hloubka_mm=Decimal(c7[1]) if c7 else None,
        blokovana=False)


def _box(box_id: int, kod_boxu: str, typ_boxu: str, kod_cleneni: str, rozmer: tuple[str, str],
         misto: tuple[int, str, int, str, int], pozice: list[VnitrniPoziceRadek]) -> BoxDetail:
    regal_id, kod_regalu, uroven_id, kod_urovne, poradi = misto
    return BoxDetail(
        box_id=box_id, kod_boxu=kod_boxu, typ_boxu=typ_boxu, cleneni_id=CLENENI_ID[kod_cleneni],
        kod_cleneni=kod_cleneni, delka_mm=Decimal(rozmer[0]), hloubka_mm=Decimal(rozmer[1]),
        full_box_klic=f"HOUFEK-PLE-{kod_regalu}-{kod_urovne}-{kod_boxu}", blokovany=False, aktivni=True,
        poradi=poradi, kod_pozice_urovne=f"P{poradi:02d}", uroven_id=uroven_id, kod_urovne=kod_urovne,
        regal_id=regal_id, kod_regalu=kod_regalu, pracoviste_id=1, kod_pracoviste="PLE", pozice=pozice)


BOXY: dict[int, BoxDetail] = {b.box_id: b for b in (
    _box(37, "BPLE037", "DYN", "C1", ("400.00", "360.00"), (1, "R01", 3, "U03", 1),
         [_pozice(101, "BPLE037", "A", "V1", 1)]),
    _box(39, "BPLE039", "DYN", "C1", ("400.00", "360.00"), (1, "R01", 3, "U03", 2),
         [_pozice(391, "BPLE039", "A", "V1", 1)]),
    _box(52, "BPLE052", "DYN", "C7", ("1000.00", "500.00"), (1, "R01", 4, "U04", 1),
         [_pozice(152, "BPLE052", "R", "V6", 1, c7=("800.00", "400.00"))]),
    _box(38, "BPLE038", "DYN", "C4", ("400.00", "360.00"), (1, "R01", 4, "U04", 2),
         [_pozice(381, "BPLE038", "G", "V3", 1), _pozice(382, "BPLE038", "H", "V3", 2),
          _pozice(383, "BPLE038", "CH", "V3", 3), _pozice(384, "BPLE038", "I", "V3", 4)]),
    _box(137, "BSTAT037", "STAT", "C4", ("400.00", "360.00"), (2, "R02", 7, "U01", 1),
         [_pozice(504, "BSTAT037", "4", "V3", 1), _pozice(503, "BSTAT037", "3", "V3", 2),
          _pozice(501, "BSTAT037", "1", "V3", 3), _pozice(502, "BSTAT037", "2", "V3", 4)]),
)}

# Použitá čísla boxů v řadách (i vyřazené boxy) – pro další číslo řady (domena.dalsi_cislo_boxu).
POUZITA_CISLA = {"BPLE": {1, 2, 3, 37, 38, 39, 52}, "BSTAT": {1, 37}}

OBSAZENE_POZICE = frozenset({101, 384, 501})   # mají obsah (v_ObsahPozice ostrova E)
STAT_PRIRAZENE_POZICE = frozenset({501, 502})  # aktivní statické umístění (v_StatickeMisto ostrova E)


def _uroven(uroven_id: int, regal_id: int, kod_urovne: str, poradi: int, delka: str, hloubka: str) -> UrovenRadek:
    pocet = sum(1 for b in BOXY.values() if b.uroven_id == uroven_id and b.aktivni)
    return UrovenRadek(uroven_id=uroven_id, regal_id=regal_id, kod_urovne=kod_urovne, poradi=poradi,
                       delka_plochy_mm=Decimal(delka), hloubka_plochy_mm=Decimal(hloubka), pocet_boxu=pocet,
                       aktivni=True)


UROVNE = [_uroven(3, 1, "U03", 3, "2400.00", "800.00"), _uroven(4, 1, "U04", 4, "2400.00", "800.00"),
          _uroven(7, 2, "U01", 1, "1800.00", "600.00"), _uroven(9, 3, "U01", 1, "1800.00", "600.00")]

# --- DTO rozhraní (odvozené z boxů, aby se vzorky nerozešly) ----------------------------------------


def _misto(box: BoxDetail, pozice: VnitrniPoziceRadek) -> MistoInfo:
    c7 = (Rozmer(pozice.rozmer_c7_delka_mm, pozice.rozmer_c7_hloubka_mm)
          if pozice.rozmer_c7_delka_mm is not None and pozice.rozmer_c7_hloubka_mm is not None else None)
    return MistoInfo(
        vnitrni_pozice_id=pozice.vnitrni_pozice_id, box_id=box.box_id, kod=pozice.kod, kod_boxu=box.kod_boxu,
        kod_pozice=pozice.kod_pozice, typ_boxu=box.typ_boxu, velikost=pozice.velikost, rozmer_c7=c7,
        blokovano=box.blokovany or pozice.blokovana, poradi_v_boxu=pozice.poradi_v_boxu,
        pracoviste=box.kod_pracoviste, regal_id=box.regal_id, uroven_id=box.uroven_id,
        adresa=f"{box.full_box_klic}-{pozice.kod_pozice}", box_blokovany=box.blokovany)


MISTA: dict[int, MistoInfo] = {p.vnitrni_pozice_id: _misto(b, p) for b in BOXY.values() for p in b.pozice}

MISTO_BPLE037_A = MISTA[101]
MISTO_BSTAT037_1 = MISTA[501]
MISTO_BPLE052_R = MISTA[152]

OBJEKT_BPLE037_A = NalezenyObjekt(
    typ="POZICE", kod="BPLE037-A", adresa="HOUFEK-PLE-R01-U03-BPLE037-A",
    regal_id=1, uroven_id=3, box_id=37, vnitrni_pozice_id=101,
)

ROZLOZENI_U03 = RozlozeniUrovne(
    uroven_id=3, kod_urovne="U03", regal_id=1, kod_regalu="R01", pracoviste="PLE",
    delka_plochy_mm=2400.0, hloubka_plochy_mm=800.0, sirka_svg_mm=860.0, vyska_svg_mm=400.0,
    boxy=(
        BoxVRozlozeni(box_id=37, kod_boxu="BPLE037", typ_boxu="DYN", kod_cleneni="C1", blokovany=False,
                      x_mm=20.0, y_mm=20.0, delka_mm=400.0, hloubka_mm=360.0,
                      pozice=(PoziceVRozlozeni(101, "A", "V1", False, 0.0, 0.0, 1.0, 1.0),), kod_pozice_urovne="P01"),
        BoxVRozlozeni(box_id=39, kod_boxu="BPLE039", typ_boxu="DYN", kod_cleneni="C1", blokovany=False,
                      x_mm=440.0, y_mm=20.0, delka_mm=400.0, hloubka_mm=360.0,
                      pozice=(PoziceVRozlozeni(391, "A", "V1", False, 0.0, 0.0, 1.0, 1.0),), kod_pozice_urovne="P02"),
    ),
)
