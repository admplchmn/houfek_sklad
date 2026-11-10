"""Služby ostrova H – Migrace XLSM: načtení do stage a validační report (fáze 1, krok 1).

`nacti` uloží sešit 1:1 do schématu stg (migrace 007) a nic nepřepočítává – staging nezná sloupce
souboru. `report` z buněk jedné dávky sestaví seznam importu pro sklad a hlásí nálezy ze
docs/migrace-xlsm.md sekce 2 až 4. Import do ostrých tabulek přes rozhraní C, D a E je krok 2.

Co report nemůže ověřit bez databáze ostrovů (délku čísla dílu, formát kódu regálu a úrovně, volnou
pozici), ověří v kroku 2 `import --nanecisto`.
"""
from __future__ import annotations

import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException

from app.ostrovy.dily import rozhrani as dily
from app.ostrovy.struktura import rozhrani as struktura
from app.platforma.chyby import AppError
from app.platforma.db import Spojeni, cteni
from app.platforma.transakce import transakce

from . import domena, repozitar

# --- načtení sešitu -----------------------------------------------------------------------------


@transakce("MIGRACE_NACTENI")
def nacti(spoj: Spojeni, soubor: str) -> tuple[int, dict[str, int]]:
    """Sešit 1:1 do stage: nová stg.Davka a jedna stg.Bunka na každou neprázdnou buňku všech listů.

    Hodnoty se ukládají jako text a `data_only=True` čte hodnoty místo vzorců (FULL_BOX_KLÍČ je v XLSM
    vzorec). Každé načtení je nová dávka, starší se nemění. Vrací DavkaID a počty buněk po listech.
    Chyby: VALIDATION_ERROR (soubor není sešit – tehdy se neuloží nic).
    """
    try:
        bunky = _bunky_seitu(soubor)
    except (InvalidFileException, zipfile.BadZipFile) as chyba:
        raise AppError("VALIDATION_ERROR", f"{Path(soubor).name} není sešit XLSX nebo XLSM.") from chyba
    davka_id = repozitar.zaloz_davku(spoj, Path(soubor).name)
    repozitar.pridej_bunky(spoj, davka_id, bunky)
    return davka_id, dict(Counter(list_ for list_, _, _, _ in bunky))


def _bunky_seitu(soubor: str) -> list[tuple[str, int, int, str]]:
    """[(název listu, řádka, sloupec, text)] – řádky i sloupce se číslují od 1, prázdné buňky chybí."""
    sek = openpyxl.load_workbook(soubor, data_only=True)
    bunky: list[tuple[str, int, int, str]] = []
    for nazev_listu in sek.sheetnames:
        for radek, hodnoty in enumerate(sek[nazev_listu].iter_rows(values_only=True), start=1):
            for sloupec, hodnota in enumerate(hodnoty, start=1):
                if hodnota is not None and str(hodnota) != "":
                    bunky.append((nazev_listu, radek, sloupec, domena.text_bunky(hodnota)))
    return bunky


# --- report -------------------------------------------------------------------------------------


@dataclass
class _Dil:
    """Díl z jednoho řádku listu Databáze (jeden řádek = jeden díl, sekce 1)."""

    radek: int
    cislo: str
    minimum: int | None
    poznamka: str | None
    vault: str


@dataclass
class _Box:
    """Řádky listu Databáze se stejným BOX_ID; údaj boxu se v XLSM opakuje na každém řádku."""

    box_id: str
    kod: str                                    # po převodu na tři číslice (D-02)
    radky: list[tuple[int, dict[str, str]]] = field(default_factory=list)
    dily: list[_Dil] = field(default_factory=list)

    def hodnota(self, klic: str) -> str:
        """První neprázdná hodnota sloupce v boxu (řádky se mohou v údajech boxu shodovat)."""
        return next((hodnoty[klic] for _, hodnoty in self.radky if hodnoty.get(klic)), "")

    @property
    def radek(self) -> int:
        return self.radky[0][0]

    @property
    def pracoviste(self) -> str:
        """Pracoviště už normalizované, aby šlo porovnat s kódem v číselníku i s kódem boxu."""
        return dily.normalizuj_identifikacni_cislo(self.hodnota("pracoviste"))

    @property
    def adresa(self) -> str:
        return " / ".join(self.hodnota(klic) or "?" for klic in ("pracoviste", "regal", "uroven", "pozice"))


@cteni
def report(spoj: Spojeni, davka_id: int | None = None) -> str:
    """Validační report z buněk jedné dávky (docs/migrace-xlsm.md 2 až 4): seznam importu po boxech,
    chyby, které by import zastavily, a upozornění pro sklad. Bez parametru nejnovější dávka.

    Čte jen stg.Bunka dané dávky a nic nezapisuje. Chyby: NOT_FOUND (dávka neexistuje),
    VALIDATION_ERROR (na listu není hlavička nebo potřebný sloupec – vypíše, co našel).
    """
    davka = _nacti_davku(spoj, davka_id)
    radky = _radky_listu(repozitar.bunky_listu(spoj, davka["DavkaID"], domena.LIST_DABAZE))
    radek_hlavicky, sloupce = _hlavicka(radky)
    boxy = _boxy(radky, sloupce, radek_hlavicky)
    chyby = _chyby(spoj, boxy)
    upozorneni = _upozorneni(boxy)
    pocet_dilu = sum(len(box.dily) for box in boxy.values())
    return "\n".join([
        f"Report dávky {davka['DavkaID']} – soubor {davka['Soubor']}, list {domena.LIST_DABAZE}",
        "",
        "Seznam importu:",
        *_seznam(boxy),
        "",
        "Chyby:",
        *(chyby or ["  žádná"]),
        "",
        "Upozornění:",
        *(upozorneni or ["  žádné"]),
        "",
        f"Součet – boxy: {len(boxy)}, díly: {pocet_dilu}, chyby: {len(chyby)}, upozornění: "
        f"{len(upozorneni)}.",
    ])


def _nacti_davku(spoj: Spojeni, davka_id: int | None) -> dict[str, Any]:
    """Dávka, jejíž buňky report čte; bez parametru je to nejnovější (největší DavkaID)."""
    if davka_id is None:
        davka_id = repozitar.nejvyssi_davka_id(spoj)
        if davka_id is None:
            raise AppError("NOT_FOUND", "Nebyl načtený žádný sešit – pusť `flask migrace nacti <soubor>`.")
    davka = repozitar.davka(spoj, davka_id)
    if davka is None:
        raise AppError("NOT_FOUND", f"Dávka {davka_id} neexistuje.")
    return davka


def _radky_listu(bunky: list[dict[str, Any]]) -> list[tuple[int, dict[int, str]]]:
    """Buňky po řádcích: [(řádka, {sloupec: text})] – prázdné řádky, které oddělují úrovně, vypadnou."""
    radky: list[tuple[int, dict[int, str]]] = []
    for bunka in bunky:
        if not radky or radky[-1][0] != bunka["Radek"]:
            radky.append((bunka["Radek"], {}))
        radky[-1][1][bunka["Sloupec"]] = (bunka["Hodnota"] or "").strip()
    return [(radek, sloupce) for radek, sloupce in radky if any(sloupce.values())]


def _hlavicka(radky: list[tuple[int, dict[int, str]]]) -> tuple[int, dict[str, int]]:
    """Řádek hlavičky (obsahuje BOX_ID i IDENTIFIKAČNÍ_ČÍSLO) a mapování klíč → číslo sloupce.

    Report nic nehádá: bez hlavičky nebo s chybějícím sloupcem skončí chybou a vypíše názvy, které
    na listu našel (sekce 2).
    """
    for radek, sloupce in radky:
        najite = {dily.normalizuj_identifikacni_cislo(text): sloupec for sloupec, text in sloupce.items()}
        klice = {klic: dily.normalizuj_identifikacni_cislo(nazev) for klic, nazev in domena.SLOUPCE.items()}
        if not all(klice[klic] in najite for klic in domena.HLAVICKA):
            continue
        chybejici = [domena.SLOUPCE[klic] for klic in domena.SLOUPCE if klice[klic] not in najite]
        if chybejici:
            raise AppError("VALIDATION_ERROR",
                           f"Řádek {radek} nemá sloupce {', '.join(chybejici)}. "
                           f"Našli jsme: {_nazvy_radku(sloupce)}.")
        return radek, {klic: najite[nazev] for klic, nazev in klice.items()}
    if not radky:
        raise AppError("VALIDATION_ERROR", f"List {domena.LIST_DABAZE} nemá žádné buňky.")
    sirka = max(radky, key=lambda bunky: len(bunky[1]))      # řádek, který hlavičkou býval nejspíš
    raise AppError("VALIDATION_ERROR",
                   f"Na listu {domena.LIST_DABAZE} není řádek hlavičky – musí obsahovat "
                   f"{domena.SLOUPCE['box_id']} a {domena.SLOUPCE['cislo_dilu']}. "
                   f"Nejvíc buněk má ř. {sirka[0]}: {_nazvy_radku(sirka[1])}.")


def _nazvy_radku(sloupce: dict[int, str]) -> str:
    """Názvy buněk řádku tak, jak je napsal autor sešitu (pro hlášku o chybějící hlavičce)."""
    return ", ".join(text for _, text in sorted(sloupce.items()))


def _boxy(radky: list[tuple[int, dict[int, str]]], sloupce: dict[str, int],
          radek_hlavicky: int) -> dict[str, _Box]:
    """Boxy po BOX_ID z řádků pod hlavičkou; řádek bez BOX_ID není díl v boxu (sekce 1)."""
    boxy: dict[str, _Box] = {}
    for radek, bunky in radky:
        if radek <= radek_hlavicky:
            continue
        hodnoty = {klic: bunky.get(sloupec, "") for klic, sloupec in sloupce.items()}
        if not hodnoty["box_id"]:
            continue
        box = boxy.setdefault(hodnoty["box_id"],
                              _Box(box_id=hodnoty["box_id"], kod=domena.kod_na_tri_cislice(hodnoty["box_id"])))
        box.radky.append((radek, hodnoty))
        dil = _dil(radek, hodnoty)
        if dil:
            box.dily.append(dil)
    return boxy


def _dil(radek: int, hodnoty: dict[str, str]) -> _Dil | None:
    """Díl z řádku; „Volný box." a „Volný slot." díl nejsou (sekce 2)."""
    text = hodnoty["cislo_dilu"]
    if not text or domena.neni_dil(text):
        return None
    minimum, poznamka = domena.minimum_a_poznamka(hodnoty["minimum"], hodnoty["jine_informace"])
    return _Dil(radek, dily.normalizuj_identifikacni_cislo(text), minimum, poznamka, hodnoty["vault"])


def _chyby(spoj: Spojeni, boxy: dict[str, _Box]) -> list[str]:
    """Chyby, které by import zastavily (sekce 4): týž kód na dvou adresách či ze dvou BOX_ID, kód
    který není kód DYN boxu nebo nesedí s pracovištěm řádku, neznámé pracoviště, chybný rozměr."""
    aktivni = {polozka.kod for polozka in struktura.nacti_ciselniky(spoj)["pracoviste"] if polozka.aktivni}
    vysledek: list[str] = []
    podle_kodu: dict[str, list[_Box]] = {}
    for box in boxy.values():
        podle_kodu.setdefault(box.kod, []).append(box)
    for kod, skupina in podle_kodu.items():
        if len(skupina) > 1:
            adresy = sorted({box.adresa for box in skupina})
            vysledek.append(f"ř. {min(box.radek for box in skupina)}: kód {kod} po převodu používá více BOX_ID "
                            f"({', '.join(box.box_id for box in skupina)}) – adresy {', '.join(adresy)}.")
    for box in boxy.values():
        rozlozeny = struktura.rozloz_kod(box.kod)
        if rozlozeny.typ != "BOX" or rozlozeny.typ_boxu != "DYN":
            vysledek.append(f"ř. {box.radek}: kód {box.kod} není kód DYN boxu (parser ho vidí jako "
                            f"{rozlozeny.typ}).")
        elif rozlozeny.kod_pracoviste != box.pracoviste:
            vysledek.append(f"ř. {box.radek}: kód {box.kod} patří pracovišti {rozlozeny.kod_pracoviste}, "
                            f"řádek má {box.hodnota('pracoviste')}.")
        if box.pracoviste not in aktivni:
            vysledek.append(f"ř. {box.radek}: pracoviště {box.hodnota('pracoviste')} není mezi aktivními "
                            f"pracovišti.")
        for klic, nazev in (("delka_mm", "délka"), ("hloubka_mm", "hloubka")):
            rozmer = box.hodnota(klic)
            if not rozmer:
                vysledek.append(f"ř. {box.radek}: box {box.kod} nemá rozměr {nazev}.")
            elif not domena.je_rozmer(rozmer):
                vysledek.append(f"ř. {box.radek}: rozměr {nazev} boxu {box.kod} není číslo ({rozmer}).")
    return vysledek


def _upozorneni(boxy: dict[str, _Box]) -> list[str]:
    """Upozornění pro sklad (sekce 2 a 3): nálezy, které import nezastaví, ale sklad je řeší v aplikaci."""
    vysledek: list[str] = []
    na_pozici: dict[str, list[_Box]] = {}
    ve_boxech: dict[str, list[_Box]] = {}
    servery: dict[str, list[int]] = {}
    for box in boxy.values():
        na_pozici.setdefault(box.adresa, []).append(box)
        for dil in box.dily:
            ve_boxech.setdefault(dil.cislo, []).append(box)
            if "_" in dil.cislo:
                vysledek.append(f"ř. {dil.radek}: číslo dílu {dil.cislo} má podtržítko – neslučujeme; zda jde "
                                "o samostatné díly, nebo revizi jednoho, zjistí technolog.")
            server = domena.vault_server(dil.vault)
            if server:
                servery.setdefault(server, []).append(dil.radek)
        stav = box.hodnota("stav_boxu")
        vyznam = domena.vyznam_stavu(stav)
        if vyznam:
            vysledek.append(f"ř. {box.radek}: {vyznam} (box {box.kod}).")
        elif (kod := dily.normalizuj_identifikacni_cislo(stav)) and kod not in domena.STAVY_BEZ_PREVODU:
            vysledek.append(f"ř. {box.radek}: STAV_BOXU {stav} není v seznamu 0, OPER, MEOP, POL, BLOK, MULTI.")
        if len(box.dily) > 1:
            navrh = domena.navrh_cleneni(len(box.dily)) or "zvolí sklad"
            vysledek.append(f"ř. {box.radek}: box {box.kod} bez členění a s {len(box.dily)} díly "
                            f"– návrh {navrh}.")
        elif not box.dily and any(hodnoty["minimum"] for _, hodnoty in box.radky):
            vysledek.append(f"ř. {box.radek}: volný box {box.kod} má minimum – minimum bez dílu se nepřevádí.")
    for adresa, skupina in na_pozici.items():
        if len(skupina) > 1:
            vysledek.append(f"ř. {min(box.radek for box in skupina)}: na pozici {adresa} stojí více boxů "
                            f"({', '.join(box.kod for box in skupina)}) – další dostane při importu volnou pozici.")
    for cislo, skupina in ve_boxech.items():
        if len({box.box_id for box in skupina}) > 1:
            vysledek.append(f"ř. {', '.join(str(box.radek) for box in skupina)}: díl {cislo} je ve více boxech – "
                            "založí se jednou.")
    if len(servery) > 1:
        prectene = ", ".join(f"{server} (ř. {', '.join(map(str, radky))})" for server, radky in servery.items())
        vysledek.append(f"odkazy do Vaultu míří na {len(servery)} serverech: {prectene}.")
    return vysledek


def _seznam(boxy: dict[str, _Box]) -> list[str]:
    """Seznam importu po boxech (sekce 4): adresa, kód, rozměry, STAV_BOXU a díly s minimem a poznámkou."""
    radky: list[str] = []
    for box in boxy.values():
        radky.append(f"  ř. {box.radek} {box.kod} – {box.adresa}, {box.hodnota('delka_mm')} × "
                     f"{box.hodnota('hloubka_mm')} mm, STAV_BOXU {box.hodnota('stav_boxu') or 'bez stavu'}")
        for dil in box.dily:
            udaje = [f"díl {dil.cislo}"]
            if dil.minimum is not None:
                udaje.append(f"minimum {dil.minimum} ks")
            if dil.poznamka:
                udaje.append(f"poznámka {dil.poznamka}")
            if dil.vault:
                udaje.append(f"Vault {dil.vault}")
            radky.append(f"    ř. {dil.radek}: " + ", ".join(udaje))
        if not box.dily:
            radky.append("    bez dílu")
    return radky
