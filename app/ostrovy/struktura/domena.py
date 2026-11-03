"""Čistá pravidla ostrova C – Struktura skladu a kódy: bez DB a bez Flasku.

Hotová ve fázi 0, protože nezávisí na otevřených otázkách:
- kódy pracoviště, regálu a úrovně – musí jít přečíst parserem rozhrani.rozloz_kod (kap. 11),
- kód boxu a číselné řady (11.2, 11.2.1) a uložená adresa FullBoxKlic (Q-03),
- pořadí boxů na úrovni – Pozice P01…Pn (kap. 6, Q-04),
- vnitřní pozice ze šablony členění (Q-05, Q-06) a rozměr variabilní pozice C7 (Q-01),
- přesun DYN boxu jen v rámci pracoviště (Q-30), cíl blokace, kontrola dlouhé adresy (Q-02),
- rozmístění boxů úrovně pro SVG (17.1).
Modul nesmí importovat rozhrani.py (rozhraní používá tato pravidla, ne naopak).
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.platforma.chyby import AppError, chyba_vstupu
from app.platforma.typy import Rozmer

KOD_FIRMY = "HOUFEK"        # Firma.KodFirmy – první část každé adresy (jediná firma, seed migrace 001)
RADA_STAT = "STAT"          # statické boxy mají jednu řadu pro celý sklad: BSTAT001–BSTAT999
MAX_CISLO_BOXU = 999        # třímístné číslo boxu (CK_Box_KodBoxu)
VELIKOST_C7 = "V6"          # jediná pozice variabilního členění C7 (Q-01)


@dataclass(frozen=True)
class PrihradkaSablony:
    """Řádek šablony členění (SablonaCleneni, Q-06) – vstup pro založení a rekonfiguraci boxu."""

    sablona_cleneni_id: int
    dyn_kod: str                # "A" … "R", včetně "CH"
    stat_kod: str               # "1" … "9"
    poradi: int                 # pořadí kandidátů v boxu (česká abeceda DYN kódu)
    velikost: str               # "V1" … "V6"


@dataclass(frozen=True)
class NovaVnitrniPozice:
    sablona_cleneni_id: int
    kod_pozice: str             # DYN písmeno, STAT číslo
    velikost: str
    poradi_v_boxu: int


@dataclass(frozen=True)
class OkrajeSvg:
    """Prezentační parametry SVG v mm (17.1) – jednotné pro celou aplikaci, nejsou to rozměry úrovně."""

    levy: Decimal = Decimal(20)
    pravy: Decimal = Decimal(20)
    horni: Decimal = Decimal(20)
    dolni: Decimal = Decimal(20)
    mezera: Decimal = Decimal(20)


OKRAJE_SVG = OkrajeSvg()


# --- kódy pracoviště, regálu a úrovně -------------------------------------------------------------


def normalizuj_kod_pracoviste(kod: str) -> str:
    """Přesně 3 znaky 0–9 A–Z (PLE, 1SV): kód je součástí DYN kódu boxu (B+PLE+037) i adresy."""
    text = _text(kod)
    if not re.fullmatch(r"[0-9A-Z]{3}", text):
        raise _chyba("kodPracoviste", "Kód pracoviště má přesně 3 znaky A–Z nebo 0–9, např. PLE nebo 1SV.")
    return text


def normalizuj_kod_regalu(kod: str) -> str:
    """R01–R99; "r1" i "R 1" → "R01". Regál R00 neexistuje (předpoklad, potvrdí vlastník procesu)."""
    return _kod_s_cislem(kod, "R", 1, "kodRegalu", "Kód regálu je R a číslo 1–99, např. R01.")


def normalizuj_kod_urovne(kod: str) -> str:
    """U00–U99; "u3" → "U03". U00 = úroveň u podlahy."""
    return _kod_s_cislem(kod, "U", 0, "kodUrovne", "Kód úrovně je U a číslo 0–99, např. U03.")


def poradi_z_kodu_urovne(kod_urovne: str) -> int:
    """Výchozí svislé pořadí úrovně = číslo v kódu (U03 → 3)."""
    return int(kod_urovne[1:])


def kod_regalu_barcode(kod_pracoviste: str, kod_regalu: str) -> str:
    """Barcode regálu pro hledání kandidátních pozic: HOUFEK-PLE-R01 (kap. 11)."""
    return f"{KOD_FIRMY}-{kod_pracoviste}-{kod_regalu}"


def full_box_klic(kod_pracoviste: str, kod_regalu: str, kod_urovne: str, kod_boxu: str) -> str:
    """Uložená adresa boxu HOUFEK-PLE-R01-U03-BPLE037 (Q-03). Přepočítává ji transakce přesunu boxu."""
    return f"{KOD_FIRMY}-{kod_pracoviste}-{kod_regalu}-{kod_urovne}-{kod_boxu}"


# --- kód boxu a číselné řady (11.2, 11.2.1) --------------------------------------------------------


def rada_boxu(typ_boxu: str, kod_pracoviste: str) -> str:
    """Prefix řady: DYN = B + kód pracoviště (BPLE), STAT = BSTAT (jedna řada pro celý sklad)."""
    if typ_boxu == "DYN":
        return f"B{kod_pracoviste}"
    if typ_boxu == "STAT":
        return f"B{RADA_STAT}"
    raise ValueError(f"Neznámý typ boxu {typ_boxu!r}")


def kod_boxu(typ_boxu: str, kod_pracoviste: str, cislo: int) -> str:
    """BPLE037 / BSTAT037 – třímístné číslo s nulami zleva."""
    if not 1 <= cislo <= MAX_CISLO_BOXU:
        raise _chyba("cisloBoxu", f"Číslo boxu musí být 1 až {MAX_CISLO_BOXU}.")
    return f"{rada_boxu(typ_boxu, kod_pracoviste)}{cislo:03d}"


def cislo_boxu(kod: str) -> int:
    """Číslo v řadě: BPLE037 → 37."""
    return int(kod[-3:])


def dalsi_cislo_boxu(pouzita: Iterable[int]) -> int:
    """Další číslo řady = nejvyšší použité + 1, počítají se i vyřazené boxy (kód ze štítku se nikdy
    nevydá znovu, UQ_Box_KodBoxu). Mezery v řadě se samy nedoplňují – volné číslo lze zadat ručně.

    Předpoklad k potvrzení vlastníkem procesu (11.2.1 říká jen „souvislá řada“).
    Chyby: BOX_SERIES_FULL.
    """
    dalsi = max(pouzita, default=0) + 1
    if dalsi > MAX_CISLO_BOXU:
        raise AppError("BOX_SERIES_FULL",
                       f"Řada je obsazená až po číslo {MAX_CISLO_BOXU}. "
                       "Volné číslo z mezery zadejte ručně (cisloBoxu).")
    return dalsi


# --- pořadí boxů na úrovni (Pozice P01…Pn) --------------------------------------------------------


def kod_pozice_urovne(poradi: int) -> str:
    """Pozice.KodPozice (počítaný sloupec, Δ2): P01 … P09, P10 …"""
    return f"P{poradi:02d}"


def vloz_do_poradi(poradi: Sequence[int], prvek: int, na: int | None, *, pole: str = "poradi") -> list[int]:
    """Vloží prvek (PoziceID) na pořadí `na` (1 = vlevo, None = na konec); prvky od `na` se posunou o 1."""
    cil = len(poradi) + 1 if na is None else na
    if not 1 <= cil <= len(poradi) + 1:
        raise _chyba(pole, f"Pořadí musí být 1 až {len(poradi) + 1}.")
    vysledek = list(poradi)
    vysledek.insert(cil - 1, prvek)
    return vysledek


def presun_v_poradi(poradi: Sequence[int], prvek: int, na: int) -> list[int]:
    """Přesune prvek na pořadí `na` v rámci stejné úrovně; ostatní se posunou."""
    if prvek not in poradi:
        raise ValueError(f"{prvek} není v pořadí {list(poradi)}")
    if not 1 <= na <= len(poradi):
        raise _chyba("novePoradi", f"Pořadí musí být 1 až {len(poradi)}.")
    vysledek = [p for p in poradi if p != prvek]
    vysledek.insert(na - 1, prvek)
    return vysledek


def odeber_z_poradi(poradi: Sequence[int], prvek: int) -> list[int]:
    """Odebere prvek (vyřazený nebo přesunutý box); boxy vpravo se posunou doleva."""
    return [p for p in poradi if p != prvek]


def zmeny_poradi(nove: Sequence[int], puvodni: dict[int, int]) -> dict[int, int]:
    """{PoziceID: nové Poradi} jen pro pozice, kterým se pořadí mění.

    Repozitář je zapíše ve dvou krocích (Poradi + 10000, pak cílové hodnoty) kvůli unikátnímu
    indexu pořadí na úrovni (Δ2). Nové prvky (bez původního pořadí) jsou ve výsledku vždy.
    """
    return {prvek: i for i, prvek in enumerate(nove, start=1) if puvodni.get(prvek) != i}


# --- členění a vnitřní pozice (Q-05, Q-06, Q-01, Q-27) ---------------------------------------------


def pozice_ze_sablony(typ_boxu: str, sablona: Sequence[PrihradkaSablony]) -> list[NovaVnitrniPozice]:
    """Vnitřní pozice nového nebo rekonfigurovaného boxu: kód podle typu boxu (DYN písmeno A–R
    včetně CH, STAT číslo 1–n), velikost ze šablony i u STAT (Q-05), pořadí ze šablony."""
    if typ_boxu not in ("DYN", "STAT"):
        raise ValueError(f"Neznámý typ boxu {typ_boxu!r}")
    if not sablona:
        raise ValueError("Šablona členění je prázdná.")
    return [NovaVnitrniPozice(p.sablona_cleneni_id, p.dyn_kod if typ_boxu == "DYN" else p.stat_kod,
                              p.velikost, p.poradi)
            for p in sorted(sablona, key=lambda p: p.poradi)]


def over_rekonfiguraci(kod_cleneni: str, novy_kod_cleneni: str) -> None:
    if kod_cleneni == novy_kod_cleneni:
        raise _chyba("cleneniId", f"Box už má členění {kod_cleneni}.")


def over_rozmer_c7(velikost: str, rozmer: Rozmer, rozmer_boxu: Rozmer) -> Rozmer:
    """Rozměr se nastavuje jen u variabilní pozice C7 (V6) a musí se vejít do vnitřku boxu (Q-01)."""
    if velikost != VELIKOST_C7:
        raise chyba_vstupu(f"Rozměr se nastavuje jen u variabilní pozice C7 (velikost {VELIKOST_C7}), "
                           f"tato pozice má {velikost}.")
    chyby = {}
    if not 0 < rozmer.delka_mm <= rozmer_boxu.delka_mm:
        chyby["delkaMm"] = f"Délka musí být větší než 0 a nejvýše {_mm(rozmer_boxu.delka_mm)} mm (délka boxu)."
    if not 0 < rozmer.hloubka_mm <= rozmer_boxu.hloubka_mm:
        chyby["hloubkaMm"] = f"Hloubka musí být větší než 0 a nejvýše {_mm(rozmer_boxu.hloubka_mm)} mm (hloubka boxu)."
    if chyby:
        raise chyba_vstupu("Rozměr C7 se musí vejít do boxu.", chyby)
    return rozmer


# --- přesun, blokace a adresa ---------------------------------------------------------------------


def over_presun_boxu(typ_boxu: str, kod: str, kod_pracoviste_cile: str) -> None:
    """DYN box nese kód pracoviště (BPLE037), proto smí stát jen na regálu svého pracoviště (Q-30)."""
    if typ_boxu == "DYN" and kod[1:4] != kod_pracoviste_cile:
        raise _chyba("cilUrovenId", f"Box {kod} patří pracovišti {kod[1:4]}, nemůže stát na pracovišti "
                                    f"{kod_pracoviste_cile}.")


def cil_blokace(typ_kodu: str) -> str:
    """Blokuje se celý box nebo jedna vnitřní pozice (kap. 7.2, 12): typ kódu z rozloz_kod → BOX | POZICE.

    Chyby: INVALID_BARCODE (není kód skladu), VALIDATION_ERROR (regál).
    """
    if typ_kodu in ("BOX", "POZICE"):
        return typ_kodu
    if typ_kodu == "REGAL":
        raise _chyba("kod", "Blokuje se box nebo pozice, ne celý regál.")
    raise AppError("INVALID_BARCODE")


def over_adresu(kod_pracoviste: str, kod_regalu: str, kod_urovne: str, kod: str, ulozena_adresa: str) -> None:
    """Dlouhý kód (HOUFEK-PLE-R01-U03-BPLE037[-A]) je jen kontrola proti uložené adrese boxu (Q-02).

    Starý štítek po přesunu boxu nesmí poslat obsluhu jinam. Chyby: INVALID_BARCODE.
    """
    adresa = full_box_klic(kod_pracoviste, kod_regalu, kod_urovne, kod)
    if adresa != ulozena_adresa:
        raise AppError("INVALID_BARCODE", f"Adresa {adresa} už neplatí, box {kod} je na {ulozena_adresa}. "
                                          "Naskenujte krátký kód boxu nebo pozice.")


# --- SVG (17.1) -----------------------------------------------------------------------------------


def rozmisteni_boxu(rozmery: Sequence[Rozmer], okraje: OkrajeSvg = OKRAJE_SVG
                    ) -> tuple[list[tuple[Decimal, Decimal]], Decimal, Decimal]:
    """Souřadnice boxů úrovně v mm, boxy v pořadí Pozice.Poradi (17.1).

    X(1) = levý okraj, X(n) = X(n-1) + šířka(n-1) + mezera; Y = horní okraj + (max hloubka − hloubka) / 2.
    Šířka plochy = okraje + součet šířek + (n − 1) × mezera; výška = okraje + max hloubka.
    Vrací ([(x, y) pro každý box], šířka plochy, výška plochy).
    """
    max_hloubka = max((r.hloubka_mm for r in rozmery), default=Decimal(0))
    souradnice = []
    x = okraje.levy
    for rozmer in rozmery:
        souradnice.append((x, okraje.horni + (max_hloubka - rozmer.hloubka_mm) / 2))
        x += rozmer.delka_mm + okraje.mezera
    sirka = okraje.levy + sum((r.delka_mm for r in rozmery), Decimal(0)) \
        + okraje.mezera * max(len(rozmery) - 1, 0) + okraje.pravy
    return souradnice, sirka, okraje.horni + max_hloubka + okraje.dolni


# --- pomocné --------------------------------------------------------------------------------------


def _text(kod: str | None) -> str:
    return re.sub(r"\s+", "", kod or "").upper()


def _kod_s_cislem(kod: str, pismeno: str, minimum: int, pole: str, zprava: str) -> str:
    nalez = re.fullmatch(pismeno + r"(\d{1,2})", _text(kod))
    if not nalez or int(nalez[1]) < minimum:
        raise _chyba(pole, zprava)
    return f"{pismeno}{int(nalez[1]):02d}"


def _mm(hodnota: Decimal) -> str:
    """Milimetry pro text v češtině: 1000.00 → "1000", 412.50 → "412,5"."""
    return f"{hodnota.normalize():f}".replace(".", ",")


def _chyba(pole: str, zprava: str) -> AppError:
    return chyba_vstupu(zprava, {pole: zprava})
