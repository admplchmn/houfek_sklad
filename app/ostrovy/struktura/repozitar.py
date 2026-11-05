"""SQL ostrova C – Struktura skladu a kódy. Zápis jen do vlastních tabulek (P1), cizí data jen z pohledů v_* (P2).

Parametry vždy přes `?`, nikdy skládáním textu (SQL injection).

Funkce mají stejné podpisy a stejné chyby jako funkce rozhraní – fáze 2 je v rozhrani.py jen
přepne na tento repozitář (čtecí funkce rozhraní vracejí po celou fázi 1 vzorová data,
docs/vyvoj.md 3.4). Rozhraní a repozitář se navzájem potřebují: repozitář skládá DTO a používá
hotová pravidla rozhraní, rozhraní volá zápisy tady. Proto se navzájem importují jako modul
(`rozhrani.MistoInfo`), ne jako jednotlivá jména – na jména by cyklus roztrhal import.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.platforma.chyby import AppError, chyba_vstupu
from app.platforma.db import Spojeni, po_davkach
from app.platforma.typy import PolozkaCiselniku, Rozmer

from . import domena, rozhrani

_PROVISORNI_POSUN = 10000   # dočasné pořadí při přepočtu (komentář u tabulky Pozice, Δ2)
_NOVA_POZICE = -1           # dočasná hodnota za PoziceID nové pozice (vloz_do_poradi počítá s prvkem)


# --- čtení míst -------------------------------------------------------------------------------
# v_Misto neobsahuje blokaci ani rozměr boxu, proto se připojuje vlastní tabulka Box.

_SLOUPCE_MISTA = """m.VnitrniPoziceID, m.BoxID, m.KodMista, m.KodBoxu, m.KodPozice, m.TypBoxu, m.Velikost,
       m.RozmerC7DelkaMM, m.RozmerC7HloubkaMM, m.Blokovano, m.PoradiVBoxu, m.KodPracoviste,
       m.RegalID, m.UrovenID, m.Adresa, b.Blokovany AS BoxBlokovany"""
_FROM_MISTA = "FROM dbo.v_Misto AS m JOIN dbo.Box AS b ON b.BoxID = m.BoxID"


def _misto(radek: dict) -> rozhrani.MistoInfo:
    """Řádek dotazu na v_Misto + Box → MistoInfo (stejné DTO jako vzorová data rozhraní)."""
    rozmer = None
    if radek["RozmerC7DelkaMM"] is not None and radek["RozmerC7HloubkaMM"] is not None:
        rozmer = Rozmer(radek["RozmerC7DelkaMM"], radek["RozmerC7HloubkaMM"])
    return rozhrani.MistoInfo(
        vnitrni_pozice_id=radek["VnitrniPoziceID"], box_id=radek["BoxID"], kod=radek["KodMista"],
        kod_boxu=radek["KodBoxu"], kod_pozice=radek["KodPozice"], typ_boxu=radek["TypBoxu"],
        velikost=radek["Velikost"], rozmer_c7=rozmer, blokovano=bool(radek["Blokovano"]),
        poradi_v_boxu=radek["PoradiVBoxu"], pracoviste=radek["KodPracoviste"], regal_id=radek["RegalID"],
        uroven_id=radek["UrovenID"], adresa=radek["Adresa"], box_blokovany=bool(radek["BoxBlokovany"]))


def najdi_objekt(spoj: Spojeni, kod: str) -> rozhrani.NalezenyObjekt:
    """Přeloží kód regálu, boxu nebo pozice na objekt (pro sken). Chyby: INVALID_BARCODE, NOT_FOUND."""
    rozlozeny = rozhrani.rozloz_kod(kod)
    if rozlozeny.typ == "TEXT":
        raise AppError("INVALID_BARCODE", f"Kód {rozlozeny.text!r} neodpovídá žádnému kódu skladu.")
    if rozlozeny.typ == "REGAL":
        radek = spoj.jeden("SELECT r.RegalID, r.KodRegalu, p.KodPracoviste FROM dbo.Regal AS r"
                           " JOIN dbo.Pracoviste AS p ON p.PracovisteID = r.PracovisteID"
                           " WHERE r.KodRegalu = ? AND p.KodPracoviste = ? AND r.Aktivni = 1",
                           rozlozeny.kod_regalu, rozlozeny.kod_pracoviste)
        if radek is None:
            raise AppError("NOT_FOUND", f"Regál {rozlozeny.text} neexistuje nebo není aktivní.")
        barcode = domena.kod_regalu_barcode(radek["KodPracoviste"], radek["KodRegalu"])
        return rozhrani.NalezenyObjekt("REGAL", barcode, barcode, radek["RegalID"])
    box = spoj.jeden("SELECT b.BoxID, b.KodBoxu, b.FullBoxKlic, p.UrovenID, u.RegalID FROM dbo.Box AS b"
                     " JOIN dbo.Pozice AS p ON p.PoziceID = b.PoziceID"
                     " JOIN dbo.Uroven AS u ON u.UrovenID = p.UrovenID WHERE b.KodBoxu = ? AND b.Aktivni = 1",
                     rozlozeny.kod_boxu)
    if box is None:
        raise AppError("NOT_FOUND", f"Box {rozlozeny.kod_boxu} neexistuje nebo není aktivní.")
    rozhrani._over_dlouhou_adresu(rozlozeny, box["FullBoxKlic"])
    if rozlozeny.typ == "BOX":
        return rozhrani.NalezenyObjekt("BOX", box["KodBoxu"], box["FullBoxKlic"], box["RegalID"], box["UrovenID"],
                                       box["BoxID"])
    radek = spoj.jeden(f"SELECT {_SLOUPCE_MISTA} {_FROM_MISTA} WHERE m.KodMista = ?", rozlozeny.kod_mista)
    if radek is None:
        raise AppError("NOT_FOUND", f"Pozice {rozlozeny.kod_mista} neexistuje nebo není aktivní.")
    misto = _misto(radek)
    return rozhrani.NalezenyObjekt("POZICE", misto.kod, misto.adresa, misto.regal_id, misto.uroven_id, misto.box_id,
                                   misto.vnitrni_pozice_id)


def najdi_vnitrni_pozici(spoj: Spojeni, kod: str) -> rozhrani.MistoInfo:
    """Přeloží naskenovaný kód na aktivní vnitřní pozici.

    Chyby: INVALID_BARCODE, NOT_FOUND, WRONG_SCAN_LEVEL (naskenován celý box nebo regál).
    """
    rozlozeny = rozhrani._kod_pozice(kod)
    radek = spoj.jeden(f"SELECT {_SLOUPCE_MISTA} {_FROM_MISTA} WHERE m.KodMista = ?", rozlozeny.kod_mista)
    if radek is None:
        raise AppError("NOT_FOUND", f"Pozice {rozlozeny.kod_mista} neexistuje nebo není aktivní.")
    misto = _misto(radek)
    if rozlozeny.kod_urovne is not None:
        rozhrani._over_dlouhou_adresu(rozlozeny, misto.adresa.rsplit("-", 1)[0])
    return misto


def nacti_mista(spoj: Spojeni, vnitrni_pozice_ids: list[int]) -> dict[int, rozhrani.MistoInfo]:
    """Hromadné načtení míst podle ID; neaktivní nebo neexistující ve výsledku chybí."""
    if not vnitrni_pozice_ids:
        return {}
    mista: dict[int, rozhrani.MistoInfo] = {}
    for davka in po_davkach(sorted(set(vnitrni_pozice_ids))):
        znacky = ", ".join("?" for _ in davka)
        for radek in spoj.dotaz(f"SELECT {_SLOUPCE_MISTA} {_FROM_MISTA}"
                                f" WHERE m.VnitrniPoziceID IN ({znacky})", *davka):
            misto = _misto(radek)
            mista[misto.vnitrni_pozice_id] = misto
    return mista


def kandidatni_mista_dyn(spoj: Spojeni, regal_id: int, velikost: str, *,
                         cele_pracoviste: bool = False) -> list[rozhrani.MistoInfo]:
    """Aktivní neblokované DYN pozice dané velikosti na regálu, seřazené podle čísla boxu
    a pořadí v boxu (21.1.3). Obsah neřeší – volná místa vybere ostrov Sklad.

    cele_pracoviste=True: i z ostatních regálů pracoviště zvoleného regálu (Q-10). Chyby: NOT_FOUND (regál).
    """
    pracoviste_id = spoj.hodnota("SELECT PracovisteID FROM dbo.Regal WHERE RegalID = ? AND Aktivni = 1", regal_id)
    if pracoviste_id is None:
        raise AppError("NOT_FOUND", f"Regál {regal_id} neexistuje nebo není aktivní.")
    kde = "m.RegalID = ?" if not cele_pracoviste else "(m.RegalID = ? OR m.PracovisteID = ?)"
    parametry: list = [velikost, regal_id]
    if cele_pracoviste:
        parametry.append(pracoviste_id)
    radky = spoj.dotaz(f"SELECT {_SLOUPCE_MISTA} {_FROM_MISTA}"
                       f" WHERE m.TypBoxu = 'DYN' AND m.Velikost = ? AND m.Blokovano = 0 AND {kde}"
                       f" ORDER BY CAST(RIGHT(m.KodBoxu, 3) AS INT), m.PoradiVBoxu", *parametry)
    return [_misto(r) for r in radky]


_SLOUPEC_ROZSAHU = {"PRAC": "m.PracovisteID", "REGAL": "m.RegalID", "UROVEN": "m.UrovenID", "BOX": "m.BoxID",
                    "POZICE": "m.VnitrniPoziceID"}


def pozice_v_rozsahu(spoj: Spojeni, typ_rozsahu: str, cil_id: int | None) -> list[int]:
    """ID aktivních vnitřních pozic v rozsahu inventury.

    typ_rozsahu: FULL | PRAC | REGAL | UROVEN | BOX | POZICE (cil_id je ID podle typu, u FULL None).
    Chyby: VALIDATION_ERROR (neznámý typ, chybějící nebo přebývající cíl), NOT_FOUND.
    """
    if typ_rozsahu not in rozhrani.ROZSAHY_INVENTURY:
        raise AppError("VALIDATION_ERROR",
                       f"Neznámý rozsah {typ_rozsahu!r}. Povolené: {', '.join(rozhrani.ROZSAHY_INVENTURY)}.")
    if (typ_rozsahu == "FULL") != (cil_id is None):
        raise AppError("VALIDATION_ERROR", "Celá inventura (FULL) nemá cíl, ostatní rozsahy ho mají povinný.")
    sql = "SELECT m.VnitrniPoziceID FROM dbo.v_Misto AS m"
    parametry: tuple = ()
    if typ_rozsahu != "FULL":
        sql += f" WHERE {_SLOUPEC_ROZSAHU[typ_rozsahu]} = ?"
        parametry = (cil_id,)
    ids = [r["VnitrniPoziceID"] for r in spoj.dotaz(sql + " ORDER BY m.VnitrniPoziceID", *parametry)]
    if not ids and typ_rozsahu != "FULL":
        raise AppError("NOT_FOUND", f"Rozsah {typ_rozsahu} {cil_id} neobsahuje žádnou aktivní pozici.")
    return ids


def nacti_ciselniky(spoj: Spojeni) -> dict[str, tuple[PolozkaCiselniku, ...]]:
    """Číselníky struktury pro filtry: "pracoviste" (kód PLE, název) a "velikosti" (V1–V6)."""
    return {
        "pracoviste": tuple(
            PolozkaCiselniku(r["PracovisteID"], r["KodPracoviste"], r["NazevPracoviste"], bool(r["Aktivni"]))
            for r in spoj.dotaz("SELECT PracovisteID, KodPracoviste, NazevPracoviste, Aktivni"
                                " FROM dbo.Pracoviste ORDER BY PracovisteID")),
        "velikosti": tuple(
            PolozkaCiselniku(r["VelikostPoziceID"], r["KodVelikosti"], r["Nazev"], True)
            for r in spoj.dotaz("SELECT VelikostPoziceID, KodVelikosti, Nazev FROM dbo.VelikostPozice"
                                " ORDER BY Poradi")),
    }


# --- rozložení úrovně (SVG, 17.1) ---------------------------------------------------------------


@dataclass(frozen=True)
class _BoxNaUrovni:
    """Řádek Box na úrovni – atributy, které očekává rozhrani._sestav_rozlozeni."""

    box_id: int
    kod_boxu: str
    typ_boxu: str
    kod_cleneni: str
    blokovany: bool
    delka_mm: Decimal
    hloubka_mm: Decimal
    poradi: int


@dataclass(frozen=True)
class _PoziceVBoxu:
    vnitrni_pozice_id: int
    box_id: int
    kod_pozice: str
    velikost: str
    blokovana: bool


@dataclass(frozen=True)
class _Prihradka:
    """Řádek šablony členění pro rozhrani._geometrie (DYN písmeno, STAT číslo, poloha v boxu)."""

    dyn_kod: str
    stat_kod: str
    rel_x: float
    rel_y: float
    rel_sirka: float
    rel_hloubka: float


def rozlozeni_urovne(spoj: Spojeni, uroven_id: int) -> rozhrani.RozlozeniUrovne:
    """Geometrie úrovně v mm pro SVG (pravidla 17.1). Chyby: NOT_FOUND."""
    uroven = spoj.jeden(
        "SELECT u.UrovenID, u.KodUrovne, u.DelkaPlochyMM, u.HloubkaPlochyMM, r.RegalID, r.KodRegalu, p.KodPracoviste"
        " FROM dbo.Uroven AS u JOIN dbo.Regal AS r ON r.RegalID = u.RegalID"
        " JOIN dbo.Pracoviste AS p ON p.PracovisteID = r.PracovisteID WHERE u.UrovenID = ?", uroven_id)
    if uroven is None:
        raise AppError("NOT_FOUND", f"Úroveň {uroven_id} neexistuje.")
    boxy = [_BoxNaUrovni(r["BoxID"], r["KodBoxu"], r["TypBoxu"], r["KodCleneni"], bool(r["Blokovany"]),
                         r["DelkaMM"], r["HloubkaMM"], r["Poradi"])
            for r in spoj.dotaz("SELECT b.BoxID, b.KodBoxu, b.Blokovany, b.DelkaMM, b.HloubkaMM, po.Poradi,"
                                " t.KodTypu AS TypBoxu, c.KodCleneni FROM dbo.Box AS b"
                                " JOIN dbo.Pozice AS po ON po.PoziceID = b.PoziceID"
                                " JOIN dbo.TypBoxu AS t ON t.TypBoxuID = b.TypBoxuID"
                                " JOIN dbo.CleneniBoxu AS c ON c.CleneniBoxuID = b.CleneniBoxuID"
                                " WHERE po.UrovenID = ? AND b.Aktivni = 1 ORDER BY po.Poradi", uroven_id)]
    prihradky = _prihradky_vsech_cleneni(spoj)
    po_boxich: dict[int, list[_PoziceVBoxu]] = {}
    for r in spoj.dotaz("SELECT m.VnitrniPoziceID, m.BoxID, m.KodPozice, m.Velikost, m.Blokovano"
                        " FROM dbo.v_Misto AS m WHERE m.UrovenID = ? ORDER BY m.PoradiVBoxu", uroven_id):
        po_boxich.setdefault(r["BoxID"], []).append(
            _PoziceVBoxu(r["VnitrniPoziceID"], r["BoxID"], r["KodPozice"], r["Velikost"], bool(r["Blokovano"])))
    return rozhrani._sestav_rozlozeni(
        uroven_id=uroven["UrovenID"], kod_urovne=uroven["KodUrovne"], regal_id=uroven["RegalID"],
        kod_regalu=uroven["KodRegalu"], pracoviste=uroven["KodPracoviste"],
        plocha=Rozmer(uroven["DelkaPlochyMM"], uroven["HloubkaPlochyMM"]),
        boxy=[(b, [(p, rozhrani._geometrie(prihradky[b.kod_cleneni], b.typ_boxu, p.kod_pozice))
                   for p in po_boxich.get(b.box_id, [])]) for b in boxy])


def _prihradky_vsech_cleneni(spoj: Spojeni) -> dict[str, list[_Prihradka]]:
    """Šablona členění (19 řádků, Q-06) rozdělená podle kódu členění."""
    vysledek: dict[str, list[_Prihradka]] = {}
    for r in spoj.dotaz("SELECT c.KodCleneni, s.DynKod, s.StatKod, s.RelX, s.RelY, s.RelSirka, s.RelHloubka"
                        " FROM dbo.SablonaCleneni AS s"
                        " JOIN dbo.CleneniBoxu AS c ON c.CleneniBoxuID = s.CleneniBoxuID"
                        " ORDER BY s.CleneniBoxuID, s.Poradi"):
        vysledek.setdefault(r["KodCleneni"], []).append(
            _Prihradka(r["DynKod"], r["StatKod"], float(r["RelX"]), float(r["RelY"]), float(r["RelSirka"]),
                       float(r["RelHloubka"])))
    return vysledek


# --- zápis (běží v transakci volajícího; P5 – bez @transakce a bez commitu) ----------------------


def zaloz_pracoviste(spoj: Spojeni, kod_pracoviste: str, nazev: str | None) -> int:
    """Vrací PracovisteID. Chyby: ALREADY_EXISTS, VALIDATION_ERROR."""
    kod = domena.normalizuj_kod_pracoviste(kod_pracoviste)
    # jediná firma (seed 001), takže kód pracoviště je unikátní i bez filtrování podle FirmaID
    if spoj.hodnota("SELECT COUNT(*) FROM dbo.Pracoviste WHERE KodPracoviste = ?", kod):
        raise AppError("ALREADY_EXISTS", f"Pracoviště {kod} už existuje.")
    return spoj.vloz("INSERT INTO dbo.Pracoviste (FirmaID, KodPracoviste, NazevPracoviste)"
                     " VALUES ((SELECT FirmaID FROM dbo.Firma WHERE KodFirmy = ?), ?, ?)",
                     domena.KOD_FIRMY, kod, nazev)


def zaloz_regal(spoj: Spojeni, pracoviste_id: int, kod_regalu: str, nazev: str | None) -> int:
    """Vrací RegalID. Chyby: ALREADY_EXISTS, NOT_FOUND."""
    kod = domena.normalizuj_kod_regalu(kod_regalu)
    pracoviste = spoj.jeden("SELECT KodPracoviste FROM dbo.Pracoviste WHERE PracovisteID = ? AND Aktivni = 1",
                            pracoviste_id)
    if pracoviste is None:
        raise AppError("NOT_FOUND", f"Pracoviště {pracoviste_id} neexistuje nebo není aktivní.")
    if spoj.hodnota("SELECT COUNT(*) FROM dbo.Regal WHERE PracovisteID = ? AND KodRegalu = ?", pracoviste_id, kod):
        raise AppError("ALREADY_EXISTS", f"Regál {kod} na pracovišti {pracoviste['KodPracoviste']} už existuje.")
    return spoj.vloz("INSERT INTO dbo.Regal (PracovisteID, KodRegalu, NazevRegalu) VALUES (?, ?, ?)",
                     pracoviste_id, kod, nazev)


def zaloz_uroven(spoj: Spojeni, regal_id: int, kod_urovne: str, poradi: int,
                 delka_plochy_mm: Decimal, hloubka_plochy_mm: Decimal) -> int:
    """Vrací UrovenID. Chyby: ALREADY_EXISTS, NOT_FOUND, VALIDATION_ERROR."""
    _over_rozmer("plochy úrovně", delka_plochy_mm, hloubka_plochy_mm)
    kod = domena.normalizuj_kod_urovne(kod_urovne)
    if spoj.hodnota("SELECT COUNT(*) FROM dbo.Regal WHERE RegalID = ? AND Aktivni = 1", regal_id) == 0:
        raise AppError("NOT_FOUND", f"Regál {regal_id} neexistuje nebo není aktivní.")
    if spoj.hodnota("SELECT COUNT(*) FROM dbo.Uroven WHERE RegalID = ? AND KodUrovne = ?", regal_id, kod):
        raise AppError("ALREADY_EXISTS", f"Úroveň {kod} na regálu {regal_id} už existuje.")
    return spoj.vloz("INSERT INTO dbo.Uroven (RegalID, KodUrovne, Poradi, DelkaPlochyMM, HloubkaPlochyMM)"
                     " VALUES (?, ?, ?, ?, ?)", regal_id, kod, poradi, delka_plochy_mm, hloubka_plochy_mm)


def zaloz_box(spoj: Spojeni, uroven_id: int, poradi: int | None, typ_boxu: str, kod_cleneni: str,
              delka_mm: Decimal, hloubka_mm: Decimal, kod_boxu: str | None = None) -> int:
    """Založí Pozice + Box + vnitřní pozice ze šablony. Vrací BoxID.

    Chyby: ALREADY_EXISTS, NOT_FOUND, VALIDATION_ERROR, BOX_SERIES_FULL (řada čísel boxu je obsazená).
    """
    if typ_boxu not in ("DYN", "STAT"):
        zprava = "Povolené typy boxu jsou DYN a STAT."
        raise chyba_vstupu(zprava, {"typBoxu": zprava})
    _over_rozmer("boxu", delka_mm, hloubka_mm)
    adresa = spoj.jeden("SELECT u.KodUrovne, r.KodRegalu, p.KodPracoviste FROM dbo.Uroven AS u"
                        " JOIN dbo.Regal AS r ON r.RegalID = u.RegalID"
                        " JOIN dbo.Pracoviste AS p ON p.PracovisteID = r.PracovisteID"
                        " WHERE u.UrovenID = ? AND u.Aktivni = 1 AND r.Aktivni = 1", uroven_id)
    if adresa is None:
        raise AppError("NOT_FOUND", f"Úroveň {uroven_id} neexistuje nebo není aktivní.")
    cleneni = spoj.jeden("SELECT CleneniBoxuID FROM dbo.CleneniBoxu WHERE KodCleneni = ?", kod_cleneni)
    if cleneni is None:
        raise AppError("NOT_FOUND", f"Členění {kod_cleneni} neexistuje (povolené C1 až C7).")
    prihradky, velikosti = _sablona_cleneni(spoj, cleneni["CleneniBoxuID"])
    kod = _kod_boxu_pro_novy_box(spoj, typ_boxu, adresa["KodPracoviste"], kod_boxu)
    typ_boxu_id = spoj.hodnota("SELECT TypBoxuID FROM dbo.TypBoxu WHERE KodTypu = ?", typ_boxu)
    nova_pozice = _vloz_pozici(spoj, uroven_id, poradi)
    box_id = spoj.vloz(
        "INSERT INTO dbo.Box (PoziceID, KodBoxu, TypBoxuID, CleneniBoxuID, DelkaMM, HloubkaMM, FullBoxKlic)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)", nova_pozice, kod, typ_boxu_id, cleneni["CleneniBoxuID"], delka_mm,
        hloubka_mm, domena.full_box_klic(adresa["KodPracoviste"], adresa["KodRegalu"], adresa["KodUrovne"], kod))
    for pozice in domena.pozice_ze_sablony(typ_boxu, prihradky):
        # rozměr se ukládá jen u variabilní pozice C7 (V6); nový box žádný vlastní rozměr nemá,
        # proto se použije rozměr boxu (Q-01). U ostatních velikostí musejí být oba sloupce NULL.
        c7 = (delka_mm, hloubka_mm) if pozice.velikost == domena.VELIKOST_C7 else (None, None)
        spoj.proved("INSERT INTO dbo.VnitrniPoziceBoxu (BoxID, SablonaCleneniID, KodPozice, VelikostPoziceID,"
                    " DelkaMM, HloubkaMM) VALUES (?, ?, ?, ?, ?, ?)",
                    box_id, pozice.sablona_cleneni_id, pozice.kod_pozice, velikosti[pozice.velikost], *c7)
    return box_id


def _over_rozmer(co: str, delka_mm: Decimal, hloubka_mm: Decimal) -> None:
    """Rozměr nového objektu – CHECK v tabulce (CK_Box_Delka, CK_Uroven_Delka) by hlásil chybu až v SQL.

    Vlastní tabulky si hlídáme sami, aby přes hranici ostrova šla jen AppError (P7).
    """
    chyby = {}
    if delka_mm <= 0:
        chyby["delkaMm"] = f"Délka {co} musí být větší než 0."
    if hloubka_mm <= 0:
        chyby["hloubkaMm"] = f"Hloubka {co} musí být větší než 0."
    if chyby:
        raise chyba_vstupu(f"Rozměr {co} musí být větší než 0.", chyby)


def _sablona_cleneni(spoj: Spojeni, cleneni_id: int) -> tuple[list[domena.PrihradkaSablony], dict[str, int]]:
    """Řádky šablony členění (Q-06) a mapa kódu velikosti na VelikostPoziceID."""
    radky = spoj.dotaz("SELECT s.SablonaCleneniID, s.DynKod, s.StatKod, s.Poradi, v.VelikostPoziceID,"
                       " v.KodVelikosti FROM dbo.SablonaCleneni AS s"
                       " JOIN dbo.VelikostPozice AS v ON v.VelikostPoziceID = s.VelikostPoziceID"
                       " WHERE s.CleneniBoxuID = ? ORDER BY s.Poradi", cleneni_id)
    prihradky = [domena.PrihradkaSablony(r["SablonaCleneniID"], r["DynKod"], r["StatKod"], r["Poradi"],
                                         r["KodVelikosti"]) for r in radky]
    return prihradky, {r["KodVelikosti"]: r["VelikostPoziceID"] for r in radky}


def _kod_boxu_pro_novy_box(spoj: Spojeni, typ_boxu: str, kod_pracoviste: str, zadany_kod: str | None) -> str:
    """Kód nového boxu: buď ze štítku, nebo další volné číslo řady (11.2.1).

    Počítají se i vyřazené boxy – kód ze štítku se znovu nepoužívá (UQ_Box_KodBoxu).
    Chyby: ALREADY_EXISTS, VALIDATION_ERROR, BOX_SERIES_FULL.
    """
    if zadany_kod is not None:
        kod = domena.over_kod_boxu(typ_boxu, kod_pracoviste, zadany_kod)
        if spoj.hodnota("SELECT COUNT(*) FROM dbo.Box WHERE KodBoxu = ?", kod):
            raise AppError("ALREADY_EXISTS", f"Box {kod} už existuje nebo existoval;"
                                             " kód ze štítku se znovu nepoužívá.")
        return kod
    rada = domena.rada_boxu(typ_boxu, kod_pracoviste)
    pouzita = [r["Cislo"] for r in spoj.dotaz(
        "SELECT CAST(RIGHT(KodBoxu, 3) AS INT) AS Cislo FROM dbo.Box WHERE KodBoxu LIKE ?", f"{rada}%")]
    return domena.kod_boxu(typ_boxu, kod_pracoviste, domena.dalsi_cislo_boxu(pouzita))


def _vloz_pozici(spoj: Spojeni, uroven_id: int, poradi: int | None) -> int:
    """Vloží pozici boxu na úrovni; boxy od `poradi` doprava se posunou o jedno (T23, Q-04).

    Pozice ostatních boxů (PoziceID) se nemění, mění se jen Poradi. Chyby: VALIDATION_ERROR (pořadí).
    """
    puvodni = {r["PoziceID"]: r["Poradi"] for r in spoj.dotaz(
        "SELECT PoziceID, Poradi FROM dbo.Pozice WHERE UrovenID = ? AND Aktivni = 1 ORDER BY Poradi", uroven_id)}
    zmeny = domena.zmeny_poradi(domena.vloz_do_poradi(list(puvodni), _NOVA_POZICE, poradi), puvodni)
    nove_poradi = zmeny.pop(_NOVA_POZICE)
    if zmeny:
        znacky = ", ".join("?" for _ in zmeny)
        # dva kroky po sobě: jedním dotazem na cílové hodnoty by se pořadí dočasně opakovalo
        # a narazilo na unikátní index UX_Pozice_Uroven_Poradi_Aktivni (Δ2).
        spoj.proved(f"UPDATE dbo.Pozice SET Poradi = Poradi + {_PROVISORNI_POSUN} WHERE PoziceID IN ({znacky})",
                    *zmeny)
        for pozice_id, cilove_poradi in zmeny.items():
            spoj.proved("UPDATE dbo.Pozice SET Poradi = ? WHERE PoziceID = ?", cilove_poradi, pozice_id)
    return spoj.vloz("INSERT INTO dbo.Pozice (UrovenID, Poradi) VALUES (?, ?)", uroven_id, nove_poradi)
