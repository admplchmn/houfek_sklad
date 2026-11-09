"""SQL ostrova E – Sklad: pohyby a zásoby. Zápis jen do vlastních tabulek (P1), cizí data jen z pohledů v_* (P2).

Parametry vždy přes `?`, nikdy skládáním textu (SQL injection). Funkce mají stejné podpisy a stejné
chyby jako funkce rozhraní (docs/vyvoj.md 3.4), hromadná čtení chodí po dávkách (`po_davkach`) a zápis
běží v transakci služby (P5) – bez @transakce a bez commitu. Historie pohybů se jen vkládá
(UPDATE/DELETE má role app_sklad odepřená, migrace 001).

Rozhraní a repozitář se navzájem potřebují (repozitář skládá DTO z rozhrani.py, rozhraní volá čtení
tady), proto se importují jako modul, ne jako jednotlivá jména – na jména by cyklus roztrhal import.
"""
from __future__ import annotations

from typing import Any

from app.platforma.chyby import AppError
from app.platforma.db import Spojeni, po_davkach
from app.platforma.typy import Kontext, PolozkaCiselniku

from . import rozhrani
from .kontrakty import UpozorneniFiltr

# --- čtení ----------------------------------------------------------------------------------------

def obsah_mist(spoj: Spojeni, vnitrni_pozice_ids: list[int]) -> dict[int, rozhrani.ObsahInfo]:
    """Aktuální obsah pozic; prázdná pozice ve výsledku chybí (0 ks se řádek maže)."""
    obsah: dict[int, rozhrani.ObsahInfo] = {}
    for davka in po_davkach(sorted(set(vnitrni_pozice_ids))):
        for radek in spoj.dotaz("SELECT VnitrniPoziceID, DilID, PocetKs FROM dbo.ObsahPozice"
                                f" WHERE VnitrniPoziceID IN ({', '.join('?' * len(davka))})", *davka):
            obsah[radek["VnitrniPoziceID"]] = rozhrani.ObsahInfo(radek["VnitrniPoziceID"], radek["DilID"],
                                                                 radek["PocetKs"])
    return obsah


def posledni_pohyby(spoj: Spojeni, vnitrni_pozice_ids: list[int]) -> dict[int, int | None]:
    """PohybID posledního pohybu na každé pozici (None = nikdy). Pro PREPOCITAT v inventuře (Q-16)."""
    posledni = {i: None for i in vnitrni_pozice_ids}
    for davka in po_davkach(sorted(set(vnitrni_pozice_ids))):
        for radek in spoj.dotaz("SELECT VnitrniPoziceID, MAX(PohybID) AS PohybID FROM dbo.SkladovyPohyb"
                                f" WHERE VnitrniPoziceID IN ({', '.join('?' * len(davka))})"
                                " GROUP BY VnitrniPoziceID", *davka):
            posledni[radek["VnitrniPoziceID"]] = radek["PohybID"]
    return posledni


_STAT_MISTO = ("SELECT StatickeUmisteniID, DilID, VnitrniPoziceID, MinimalniPocetKs, OptimalniPocetKs,"
               " MaximalniPocetKs FROM dbo.StatickeUmisteniDilu")


def stat_mista(spoj: Spojeni, *, vnitrni_pozice_ids: list[int] | None = None,
               dil_ids: list[int] | None = None) -> list[rozhrani.StatMistoInfo]:
    """Aktivní statická umístění podle pozic nebo dílů (nejvýše 1 na díl, Q-12). Bez filtru = všechna."""
    if vnitrni_pozice_ids is not None:
        radky = _stat_mista_davka(spoj, "VnitrniPoziceID", vnitrni_pozice_ids)
    elif dil_ids is not None:
        radky = _stat_mista_davka(spoj, "DilID", dil_ids)
    else:
        radky = spoj.dotaz(f"{_STAT_MISTO} WHERE Aktivni = 1 ORDER BY StatickeUmisteniID")
    mista = [rozhrani.StatMistoInfo(r["StatickeUmisteniID"], r["DilID"], r["VnitrniPoziceID"],
                                    r["MinimalniPocetKs"], r["OptimalniPocetKs"], r["MaximalniPocetKs"])
             for r in radky]
    return [m for m in mista if dil_ids is None or m.dil_id in set(dil_ids)]


def _stat_mista_davka(spoj: Spojeni, sloupec: str, ids: list[int]) -> list[dict[str, Any]]:
    radky: list[dict[str, Any]] = []
    for davka in po_davkach(sorted(set(ids))):
        radky += spoj.dotaz(f"{_STAT_MISTO} WHERE Aktivni = 1 AND {sloupec} IN ({', '.join('?' * len(davka))})"
                            " ORDER BY StatickeUmisteniID", *davka)
    return radky


def nacti_ciselniky(spoj: Spojeni) -> dict[str, tuple[PolozkaCiselniku, ...]]:
    """Číselníky skladu pro filtry: "typyPohybu" (PRIJEM, VYDEJ, PRESUN-OUT …)."""
    return {
        "typyPohybu": tuple(
            PolozkaCiselniku(r["TypPohybuID"], r["KodPohybu"], r["NazevPohybu"], bool(r["Aktivni"]))
            for r in spoj.dotaz("SELECT TypPohybuID, KodPohybu, NazevPohybu, Aktivni FROM dbo.TypPohybu"
                                " ORDER BY TypPohybuID")),
    }


# Vlastní tabulky upozornění a přiřazení; číslo dílu a kód pozice přidává služba přes rozhraní D a C.
_UPOZORNENI = ("SELECT u.UpozorneniID, u.StatickeUmisteniID, u.DatumVzniku, u.AktualniPocetKs,"
               " u.MinimalniPocetKs, u.TypStavu, u.StavUpozorneni, u.DatumUzavreni, u.Poznamka,"
               " s.DilID, s.VnitrniPoziceID"
               " FROM dbo.UpozorneniZasoby AS u"
               " JOIN dbo.StatickeUmisteniDilu AS s ON s.StatickeUmisteniID = u.StatickeUmisteniID")


def seznam_upozorneni(spoj: Spojeni, filtr: UpozorneniFiltr) -> tuple[list[dict[str, Any]], int]:
    """Stránka upozornění zásoby (nejnovější první) a jejich celkový počet podle filtru."""
    podminky = ["1 = 1"]
    parametry: list[Any] = []
    for podminka, hodnota in (("u.StavUpozorneni = ?", filtr.stav), ("u.TypStavu = ?", filtr.typ_stavu),
                              ("s.DilID = ?", filtr.dil_id)):
        if hodnota is not None:
            podminky.append(podminka)
            parametry.append(hodnota)
    kde = " AND ".join(podminky)
    celkem = spoj.hodnota("SELECT COUNT(*) FROM dbo.UpozorneniZasoby AS u"
                          " JOIN dbo.StatickeUmisteniDilu AS s ON s.StatickeUmisteniID = u.StatickeUmisteniID"
                          f" WHERE {kde}", *parametry) or 0
    radky = spoj.dotaz(f"{_UPOZORNENI} WHERE {kde} ORDER BY u.DatumVzniku DESC, u.UpozorneniID DESC"
                       " OFFSET ? ROWS FETCH NEXT ? ROWS ONLY",
                       *parametry, (filtr.strana - 1) * filtr.velikost, filtr.velikost)
    return radky, celkem


# --- zápis (běží v transakci služby; P5 – bez @transakce a bez commitu) ---------------------------

def nastav_obsah(spoj: Spojeni, vnitrni_pozice_id: int, dil_id: int, pocet_ks: int) -> None:
    """Nastaví obsah pozice; při 0 ks se řádek maže (DYN pozice je volná, STAT přiřazení zůstává).

    Pozice je zamčená `struktura.zamkni_mista`; souběžný vklad téže pozice oznámí
    UQ_ObsahPozice_VnitrniPozice a @transakce z něj udělá CONCURRENT_CHANGE.
    """
    if pocet_ks <= 0:
        spoj.proved("DELETE FROM dbo.ObsahPozice WHERE VnitrniPoziceID = ?", vnitrni_pozice_id)
        return
    if spoj.proved("UPDATE dbo.ObsahPozice SET PocetKs = ?, DatumZmeny = SYSUTCDATETIME()"
                   " WHERE VnitrniPoziceID = ?", pocet_ks, vnitrni_pozice_id):
        return
    spoj.proved("INSERT INTO dbo.ObsahPozice (VnitrniPoziceID, DilID, PocetKs, DatumZmeny)"
                " VALUES (?, ?, ?, SYSUTCDATETIME())", vnitrni_pozice_id, dil_id, pocet_ks)


def pridej_pohyb(spoj: Spojeni, *, typ_pohybu: str, dil_id: int, vnitrni_pozice_id: int, mnozstvi: int,
                 stav_pred: int, stav_po: int, kdo: Kontext, poznamka: str | None) -> int:
    """Vloží hareket (podepsaná změna, `TransakceID` ze spojení) a vrátí nové PohybID.

    `Mnozstvi <> 0` a `StavPo = StavPred + Mnozstvi` hlídá CHECK ve tabulce; pravidla hlásí
    AppError dřív, než se k SQL dostaneme. Chyby: NOT_FOUND (neznámý typ pohybu).
    """
    typ_pohybu_id = spoj.hodnota("SELECT TypPohybuID FROM dbo.TypPohybu WHERE KodPohybu = ?", typ_pohybu)
    if typ_pohybu_id is None:
        raise AppError("NOT_FOUND", f"Typ pohybu {typ_pohybu} neexistuje.")
    return spoj.vloz(
        "INSERT INTO dbo.SkladovyPohyb (TypPohybuID, DilID, VnitrniPoziceID, Mnozstvi, StavPred, StavPo,"
        " UzivatelID, TerminalID, TransakceID, Poznamka) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        typ_pohybu_id, dil_id, vnitrni_pozice_id, mnozstvi, stav_pred, stav_po, kdo.uzivatel_id,
        kdo.terminal_id, spoj.transakce_id, poznamka)


def otevrene_upozorneni(spoj: Spojeni, stat_umisteni_id: int) -> dict[str, Any] | None:
    """Otevřené upozornění STAT místa, zamčené UPDLOCK (5.8).

    Zámek drží do konce transakce, takže dvě operace nad týmž místem nevytvoří dvě otevřená
    upozornění (UX_UpozorneniZasoby_Otevrene je filtrovaný unikátní index na místo).
    """
    return spoj.jeden("SELECT UpozorneniID, TypStavu, AktualniPocetKs, MinimalniPocetKs"
                      " FROM dbo.UpozorneniZasoby WITH (UPDLOCK, HOLDLOCK)"
                      " WHERE StatickeUmisteniID = ? AND StavUpozorneni = 'OTEVRENE'", stat_umisteni_id)


def zaloz_upozorneni(spoj: Spojeni, stat_umisteni_id: int, pocet_ks: int, minimalni_ks: int,
                     typ_stavu: str) -> int:
    """Vrací UpozorneniID; stav i minimum se ukládají jako snímek okamžiku (Q-13)."""
    return spoj.vloz("INSERT INTO dbo.UpozorneniZasoby (StatickeUmisteniID, AktualniPocetKs, MinimalniPocetKs,"
                     " TypStavu) VALUES (?, ?, ?, ?)", stat_umisteni_id, pocet_ks, minimalni_ks, typ_stavu)


def obnov_upozorneni(spoj: Spojeni, upozorneni_id: int, pocet_ks: int, minimalni_ks: int, typ_stavu: str) -> None:
    """Nový snímek stavu a minima otevřeného upozornění, kterému se změnil TypStavu (5.8)."""
    spoj.proved("UPDATE dbo.UpozorneniZasoby SET AktualniPocetKs = ?, MinimalniPocetKs = ?, TypStavu = ?"
                " WHERE UpozorneniID = ?", pocet_ks, minimalni_ks, typ_stavu, upozorneni_id)


def uzavri_upozorneni(spoj: Spojeni, upozorneni_id: int, kdo: Kontext) -> None:
    """Automatické uzavření při doplnění nad minimum (Q-13); poznámku má jen ruční uzavření."""
    spoj.proved("UPDATE dbo.UpozorneniZasoby SET StavUpozorneni = 'UZAVRENE', DatumUzavreni = SYSUTCDATETIME(),"
                " UzavrelUzivatelID = ? WHERE UpozorneniID = ?", kdo.uzivatel_id, upozorneni_id)
