"""SQL ostrova F – Inventura. Zápis jen do vlastních tabulek (P1), cizí data jen z pohledů v_* (P2).

Parametry vždy přes `?`, nikdy skládáním textu (SQL injection); hromadná čtení chodí po dávkách
(`po_davkach`), zápis běží v transakci služby (P5) – bez @transakce a bez commitu.
Pohyby pro pravidlo D-26 se počítají jen z publikovaného pohledu v_PohybDetail, nikdy ne přímo
z tabulek ostrova E.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.platforma.db import Spojeni, po_davkach

from . import domena
from .kontrakty import InventuryFiltr

_INVENTURA = ("SELECT InventuraID, TypRozsahu, PracovisteID, RegalID, UrovenID, BoxID, VnitrniPoziceID,"
              " StavInventury, SlepaInventura, DatumZahajeni, DatumDokonceni, ZalozilUzivatelID, Poznamka"
              " FROM dbo.Inventura")
_POLOZKA = ("SELECT InventuraPolozkaID, VnitrniPoziceID, OcekavanyDilID, OcekavanyPocetKs, SkutecnyDilID,"
            " SkutecnyPocetKs, RozdilKs, Vyhodnoceni, DatumKontroly, UzivatelID, PosledniPohybID"
            " FROM dbo.InventuraPolozka")

# sloupec, do kterého patří cíl rozsahu (CK_Inventura_Rozsah); rozsah FULL cíl nemá
_CIL_ROZSAHU = {"PRAC": "PracovisteID", "REGAL": "RegalID", "UROVEN": "UrovenID", "BOX": "BoxID",
                "POZICE": "VnitrniPoziceID"}

# --- čtení ----------------------------------------------------------------------------------------


def inventury(spoj: Spojeni, filtr: InventuryFiltr) -> tuple[list[dict[str, Any]], int]:
    """Stránka inventur, nejnovější první. filtr.stav None = všechny stavy."""
    kde, parametry = ("WHERE StavInventury = ?", [filtr.stav]) if filtr.stav else ("", [])
    celkem = spoj.hodnota(f"SELECT COUNT(*) FROM dbo.Inventura {kde}", *parametry) or 0
    radky = spoj.dotaz(f"{_INVENTURA} {kde} ORDER BY DatumZahajeni DESC, InventuraID DESC"
                       " OFFSET ? ROWS FETCH NEXT ? ROWS ONLY",
                       *parametry, (filtr.strana - 1) * filtr.velikost, filtr.velikost)
    return radky, celkem


def inventura(spoj: Spojeni, inventura_id: int) -> dict[str, Any] | None:
    return spoj.jeden(f"{_INVENTURA} WHERE InventuraID = ?", inventura_id)


def cil(radek: dict[str, Any]) -> int | None:
    """ID cíle rozsahu z řádku inventury – hodnota sloupce podle TypRozsahu (FULL je bez cíle)."""
    return next((radek[sloupec] for sloupec in _CIL_ROZSAHU.values() if radek[sloupec] is not None), None)


def polozky(spoj: Spojeni, inventura_id: int) -> list[dict[str, Any]]:
    return spoj.dotaz(f"{_POLOZKA} WHERE InventuraID = ? ORDER BY InventuraPolozkaID", inventura_id)


def polozka(spoj: Spojeni, inventura_id: int, vnitrni_pozice_id: int) -> dict[str, Any] | None:
    return spoj.jeden(f"{_POLOZKA} WHERE InventuraID = ? AND VnitrniPoziceID = ?", inventura_id,
                      vnitrni_pozice_id)


def pozice_v_rozpracovanych(spoj: Spojeni, vnitrni_pozice_ids: list[int]) -> list[dict[str, Any]]:
    """Pozice, které už jsou v nějaké rozpracované inventuře (i v té, kterou zrovna zakládáme).

    Volá se až po struktura.zamkni_mista, aby se dvě souběžná založení stejných pozic seřadila
    za sebe a to druhé překryv uvidilo (S-16).
    """
    radky: list[dict[str, Any]] = []
    for davka in po_davkach(sorted(set(vnitrni_pozice_ids))):
        radky += spoj.dotaz("SELECT p.VnitrniPoziceID, p.InventuraID FROM dbo.InventuraPolozka AS p"
                            " JOIN dbo.Inventura AS i ON i.InventuraID = p.InventuraID"
                            " WHERE i.StavInventury = 'ROZPRACOVANA'"
                            f" AND p.VnitrniPoziceID IN ({', '.join('?' * len(davka))})"
                            " ORDER BY p.VnitrniPoziceID", *davka)
    return radky


def pohyby_po_vodoznaku(spoj: Spojeni, vodoznaky: dict[int, int | None]) -> dict[int, list[domena.Pohyb]]:
    """Všechny pohyby na pozicích po jejich vodoznaku (D-26), {VnitrniPoziceID: [Pohyb, …]} vzestupně.

    Vodoznak None = pozice měla při zápisu ještě žádný pohyb, takže se počítají všechny.
    """
    pohyby = {i: [] for i in vodoznaky}
    for davka in po_davkach(sorted(vodoznaky), 500):   # dva parametry na pozici (limit 2100)
        rady = ", ".join("(?, ?)" for _ in davka)
        for radek in spoj.dotaz(
            f"SELECT vod.VnitrniPoziceID, p.DilID, p.StavPo FROM (VALUES {rady})"
            " AS vod (VnitrniPoziceID, Vodoznak)"
            " JOIN dbo.v_PohybDetail AS p ON p.VnitrniPoziceID = vod.VnitrniPoziceID"
            " AND p.PohybID > vod.Vodoznak ORDER BY vod.VnitrniPoziceID, p.PohybID",
            *[hodnota for i in davka for hodnota in (i, vodoznaky[i] or 0)]):
            pohyby[radek["VnitrniPoziceID"]].append(domena.Pohyb(radek["DilID"], radek["StavPo"]))
    return pohyby


# --- zápis ----------------------------------------------------------------------------------------


def zaloz(spoj: Spojeni, *, typ_rozsahu: str, cil_id: int | None, slepa: bool, uzivatel_id: int,
          poznamka: str | None) -> int:
    """Vloží hlavičku inventury jako rozpracovanou – StavInventury DEFAULT v tabulce nemá, proto je
    v INSERTu přímo. DatumZahajeni doplní SYSUTCDATETIME(). Cíl rozsahu jde do sloupce
    podle TypRozsahu, ostatní zůstávají NULL (CK_Inventura_Rozsah). Vrací InventuraID."""
    cil = {sloupec: cil_id if _CIL_ROZSAHU.get(typ_rozsahu) == sloupec else None
           for sloupec in _CIL_ROZSAHU.values()}
    return spoj.vloz("INSERT INTO dbo.Inventura (TypRozsahu, StavInventury, PracovisteID, RegalID, UrovenID,"
                     " BoxID, VnitrniPoziceID, SlepaInventura, ZalozilUzivatelID, Poznamka)"
                     " VALUES (?, 'ROZPRACOVANA', ?, ?, ?, ?, ?, ?, ?)", typ_rozsahu, cil["PracovisteID"],
                     cil["RegalID"], cil["UrovenID"], cil["BoxID"], cil["VnitrniPoziceID"], slepa, uzivatel_id,
                     poznamka)


def pridej_polozky(spoj: Spojeni, inventura_id: int, snimek: Sequence[tuple[int, int | None, int]]) -> None:
    """Vloží položky inventury: (VnitrniPoziceID, OcekavanyDilID, OcekavanyPocetKs) ze snímku
    očekávaného stavu. Zjištěný stav zůstává NULL – položka čeká na fyzickou kontrolu."""
    for vnitrni_pozice_id, dil_id, pocet_ks in snimek:
        spoj.proved("INSERT INTO dbo.InventuraPolozka (InventuraID, VnitrniPoziceID, OcekavanyDilID,"
                    " OcekavanyPocetKs) VALUES (?, ?, ?, ?)", inventura_id, vnitrni_pozice_id, dil_id, pocet_ks)


def zaps_polozku(spoj: Spojeni, *, inventura_id: int, vnitrni_pozice_id: int, ocekavany_dil_id: int | None,
                 ocekavany_pocet_ks: int, skutecny_dil_id: int | None, skutecny_pocet_ks: int,
                 rozdil_ks: int, vyhodnoceni: str, posledni_pohyb_id: int | None, uzivatel_id: int) -> None:
    """Uloží zjištěný stav, obnovený očekávaný stav z aktuálního obsahu a vodoznak posledního pohybu
    pozice (D-26). Zápis jde opakovat – přepočet přepíše i dřívější zjištění."""
    spoj.proved("UPDATE dbo.InventuraPolozka SET OcekavanyDilID = ?, OcekavanyPocetKs = ?, SkutecnyDilID = ?,"
                " SkutecnyPocetKs = ?, RozdilKs = ?, Vyhodnoceni = ?, DatumKontroly = SYSUTCDATETIME(),"
                " UzivatelID = ?, PosledniPohybID = ? WHERE InventuraID = ? AND VnitrniPoziceID = ?",
                ocekavany_dil_id, ocekavany_pocet_ks, skutecny_dil_id, skutecny_pocet_ks, rozdil_ks,
                vyhodnoceni, uzivatel_id, posledni_pohyb_id, inventura_id, vnitrni_pozice_id)


def zrus(spoj: Spojeni, inventura_id: int, duvod: str) -> None:
    """Zrušená inventura: stav a důvod v poznámce; skladové pohyby se nepíšou (5.11)."""
    spoj.proved("UPDATE dbo.Inventura SET StavInventury = 'ZRUSENA', Poznamka = ? WHERE InventuraID = ?",
                duvod, inventura_id)
