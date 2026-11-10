"""Služby ostrova F – Inventura. Jedna operace = @transakce, čtení = @cteni.

Inventura je nad SQL Serverem: hlavička i položky žijí ve vlastních tabulkách (repozitar), cizí
data – štítky a velikosti pozic (C), díly (D) a obsah pozic s pohyby (E) – se berou jen jejich
rozhraním. Stav položky se nikam neukládá, počítá se z pohybů po vodoznaku položky (D-26)
a jen dokud je inventura rozpracovaná.

Dokončení (21.1.7): zamkne hlavičku inventury i všechny zúčastněné pozice, přepočítá stavy,
zkontroluje inventuru a její cíle nalezených jiných dílů (D-26, D-27), zaúčtuje plán korekcí
přes sklad.zauctuj_korekci pohyby INVENTURA a inventuru zavře – vše v jedné SQL transakci.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.ostrovy.dily import rozhrani as dily
from app.ostrovy.sklad import rozhrani as sklad
from app.ostrovy.struktura import rozhrani as struktura
from app.platforma.chyby import AppError, chyba_vstupu
from app.platforma.db import Spojeni, cteni
from app.platforma.kontrakty import DuvodVstup, Strana
from app.platforma.transakce import transakce
from app.platforma.typy import Kontext

from . import domena, repozitar
from .kontrakty import (
    DokonceniVstup,
    DokonceniVysledek,
    InventuraDetail,
    InventuraRadek,
    InventuryFiltr,
    NovaInventuraVstup,
    PolozkaInventury,
    ZapisPolozkyVstup,
)

# --- čtení ------------------------------------------------------------------------------------


@cteni
def seznam_inventur(spoj: Spojeni, filtr: InventuryFiltr) -> Strana[InventuraRadek]:
    """Inventury, nejnovější první. Výchozí filtr = rozpracované."""
    radky, celkem = repozitar.inventury(spoj, filtr)
    return Strana[InventuraRadek](polozky=[_radek(spoj, r) for r in radky], strana=filtr.strana,
                                  velikost=filtr.velikost, celkem=celkem)


@cteni
def detail_inventury(spoj: Spojeni, inventura_id: int) -> InventuraDetail:
    """Inventura s položkami; slepá inventura u nezapsaných položek očekávaný stav nevrací."""
    return _detail(spoj, _nacti(spoj, inventura_id))


# --- příkazy ----------------------------------------------------------------------------------------


@transakce("INVENTURA_ZALOZENI")
def zaloz_inventuru(spoj: Spojeni, vstup: NovaInventuraVstup, kdo: Kontext) -> InventuraDetail:
    """Položky pro všechny aktivní pozice v rozsahu, i prázdné, se snímkem očekávaného dílu a počtu (5.11).

    Pozice smí být nejvýš v jedné rozpracované inventuře (jinak by se její rozdíl zaúčtoval
    dvakrát); překryv se kontroluje až po zamčení pozic, aby se dvě souběžná založení seřadila
    za sebe a to druhé překryv uvidělo (S-16).
    Chyby: VALIDATION_ERROR (rozsah), NOT_FOUND (cíl), ALREADY_EXISTS (pozice v jiné rozpracované inventuře).
    """
    domena.over_rozsah(vstup.typ_rozsahu, vstup.cil_id)
    ids = struktura.pozice_v_rozsahu(spoj, vstup.typ_rozsahu, vstup.cil_id)
    struktura.zamkni_mista(spoj, ids)
    prekryv = repozitar.pozice_v_rozpracovanych(spoj, ids)
    if prekryv:
        kody = sorted(m.kod for m in struktura.nacti_mista(
            spoj, [r["VnitrniPoziceID"] for r in prekryv]).values())
        raise AppError("ALREADY_EXISTS", f"Pozice {', '.join(kody)} už jsou v rozpracované inventuře "
                                         f"{prekryv[0]['InventuraID']}. Dokončete ji nebo zrušte.")
    obsah = sklad.obsah_mist(spoj, ids)
    inventura_id = repozitar.zaloz(spoj, typ_rozsahu=vstup.typ_rozsahu, cil_id=vstup.cil_id,
                                   slepa=vstup.slepa, uzivatel_id=kdo.uzivatel_id, poznamka=vstup.poznamka)
    repozitar.pridej_polozky(spoj, inventura_id, [(i, obsah[i].dil_id if i in obsah else None,
                                                   obsah[i].pocet_ks if i in obsah else 0) for i in ids])
    return _detail(spoj, _nacti(spoj, inventura_id))


@transakce("INVENTURA_ZAPIS")
def zapis_polozku(spoj: Spojeni, inventura_id: int, vnitrni_pozice_id: int, vstup: ZapisPolozkyVstup,
                  kdo: Kontext) -> PolozkaInventury:
    """Zápis nalezeného stavu (i opakovaný = přepočet). Očekávaný stav se obnoví z aktuálního obsahu,
    takže pohyby mezi založením a počítáním se započtou; položka si zapamatuje poslední pohyb
    pozice, podle kterého pak pozná, co se změnilo do dokončení (D-26).

    Chyby: NOT_FOUND (inventura, pozice v ní, díl), CONCURRENT_CHANGE (inventura už není rozpracovaná),
    VALIDATION_ERROR (prázdné s počtem, díl bez počtu).
    """
    inventura = _rozpracovana(spoj, inventura_id)
    if repozitar.polozka(spoj, inventura_id, vnitrni_pozice_id) is None:
        raise AppError("NOT_FOUND", f"Pozice {vnitrni_pozice_id} v inventuře {inventura_id} není.")
    domena.over_zapis(vstup.skutecny_dil_id, vstup.skutecny_pocet_ks)
    if vstup.skutecny_dil_id is not None and vstup.skutecny_dil_id not in dily.nacti_dily(
            spoj, [vstup.skutecny_dil_id]):
        raise AppError("NOT_FOUND", f"Díl {vstup.skutecny_dil_id} neexistuje.")
    struktura.zamkni_mista(spoj, [vnitrni_pozice_id])
    obsah = sklad.obsah_mist(spoj, [vnitrni_pozice_id]).get(vnitrni_pozice_id)
    posledni_pohyb_id = sklad.posledni_pohyby(spoj, [vnitrni_pozice_id])[vnitrni_pozice_id]
    ocekavany_dil_id = obsah.dil_id if obsah else None
    ocekavany_pocet_ks = obsah.pocet_ks if obsah else 0
    vysledek, rozdil = domena.vyhodnot(ocekavany_dil_id, ocekavany_pocet_ks, vstup.skutecny_dil_id,
                                       vstup.skutecny_pocet_ks)
    repozitar.zaps_polozku(spoj, inventura_id=inventura_id, vnitrni_pozice_id=vnitrni_pozice_id,
                           ocekavany_dil_id=ocekavany_dil_id, ocekavany_pocet_ks=ocekavany_pocet_ks,
                           skutecny_dil_id=vstup.skutecny_dil_id, skutecny_pocet_ks=vstup.skutecny_pocet_ks,
                           rozdil_ks=rozdil, vyhodnoceni=vysledek, posledni_pohyb_id=posledni_pohyb_id,
                           uzivatel_id=kdo.uzivatel_id)
    return _vystup_polozky(bool(inventura["SlepaInventura"]), _polozka(spoj, inventura_id, vnitrni_pozice_id))


@transakce("INVENTURA_ZRUSENI")
def zrus_inventuru(spoj: Spojeni, inventura_id: int, vstup: DuvodVstup, kdo: Kontext) -> InventuraRadek:
    """Zrušení: žádné pohyby, stav ZRUSENA a důvod v poznámce (5.11). Chyby: NOT_FOUND, CONCURRENT_CHANGE."""
    inventura = _rozpracovana(spoj, inventura_id)
    repozitar.zrus(spoj, inventura_id, vstup.duvod)
    return _radek(spoj, inventura).model_copy(update={"stav_inventury": "ZRUSENA", "poznamka": vstup.duvod})


@transakce("INVENTURA_DOKONCENI", skladova=True)
def dokonci_inventuru(spoj: Spojeni, inventura_id: int, vstup: DokonceniVstup, kdo: Kontext) -> DokonceniVysledek:
    """Zaúčtuje rozdíly a nálezy (21.1.7) a inventuru zavře; všechno v jedné SQL transakci.

    Stav položek i cíle se ověřují až pod zámkem všech zúčastněných pozic, aby plán seděl na data,
    nad kterou se účtuje (D-26, D-27). Jakákoli chyba – přepočet, neplatný cíl i chyba ostrova E –
    vrátí zpět celé dokončení, inventura zůstane rozpracovaná.
    Chyby: NOT_FOUND, CONCURRENT_CHANGE (není rozpracovaná), VALIDATION_ERROR (nezapsané pozice,
    chybějící nebo nevhodný cíl JINY_DIL), INVENTORY_RECOUNT (pozice vrácené k přepočtu).
    """
    _rozpracovana(spoj, inventura_id)
    polozky = _polozky(spoj, inventura_id)
    cile = _preloz_cile(spoj, polozky, vstup.cile_jiny_dil)
    struktura.zamkni_mista(spoj, [p.vnitrni_pozice_id for p in polozky]
                           + [m.vnitrni_pozice_id for m in cile.values()])
    polozky = _polozky(spoj, inventura_id)
    domena.over_dokonceni(polozky, vstup.cile_jiny_dil)
    korekce = domena.planuj_korekce(polozky, _over_cile(spoj, polozky, cile))
    pohyby = _zauctuj_korekce(spoj, kdo, korekce, vstup.poznamka)
    if repozitar.dokonci(spoj, inventura_id, kdo.uzivatel_id) == 0:
        raise AppError("CONCURRENT_CHANGE", f"Inventura {inventura_id} už není rozpracovaná.")
    pocty = domena.souhrn(polozky)
    return DokonceniVysledek(inventura_id=inventura_id, pocet_shod=pocty["SHODA"], pocet_rozdilu=pocty["ROZDIL"],
                             pocet_jinych_dilu=pocty["JINY_DIL"], pohyby=pohyby)


# --- pomocné -------------------------------------------------------------------------------------


def _nacti(spoj: Spojeni, inventura_id: int) -> dict[str, Any]:
    inventura = repozitar.inventura(spoj, inventura_id)
    if inventura is None:
        raise AppError("NOT_FOUND", f"Inventura {inventura_id} neexistuje.")
    return inventura


def _rozpracovana(spoj: Spojeni, inventura_id: int) -> dict[str, Any]:
    """Hlavička čtená se zámkem pro zápis – operace jedné inventury se seřadí za sebe."""
    inventura = repozitar.inventura_s_zamkem(spoj, inventura_id)
    if inventura is None:
        raise AppError("NOT_FOUND", f"Inventura {inventura_id} neexistuje.")
    if inventura["StavInventury"] != "ROZPRACOVANA":
        stav = "dokončená" if inventura["StavInventury"] == "DOKONCENA" else "zrušená"
        raise AppError("CONCURRENT_CHANGE", f"Inventura {inventura_id} už je {stav}.")
    return inventura


def _polozky(spoj: Spojeni, inventura_id: int, *, uzavrena: bool = False) -> list[domena.Polozka]:
    return _polozky_z_radku(spoj, repozitar.polozky(spoj, inventura_id), uzavrena=uzavrena)


def _polozka(spoj: Spojeni, inventura_id: int, vnitrni_pozice_id: int) -> domena.Polozka:
    return _polozky_z_radku(spoj, [repozitar.polozka(spoj, inventura_id, vnitrni_pozice_id)])[0]


def _polozky_z_radku(spoj: Spojeni, radky: list[dict[str, Any]], *,
                     uzavrena: bool = False) -> list[domena.Polozka]:
    """Řádky položek doplněné o aktuální data z C a E; stav CEKA / ZAPSANO / PREPOCITAT dle D-26.

    Neaktivní pozice (po rekonfiguraci) už není ve v_Misto – štítek neznáme, položka se jmenuje
    podle svého ID a jde k přepočtu. `uzavrena` = inventura už není rozpracovaná: stav se
    nepřepočítává, pohyby po vodoznaku se proto ani nečtou.
    """
    ids = [r["VnitrniPoziceID"] for r in radky]
    mista = struktura.nacti_mista(spoj, ids)
    obsah = sklad.obsah_mist(spoj, ids)
    vodoznaky = ({} if uzavrena else
                 {r["VnitrniPoziceID"]: r["PosledniPohybID"] for r in radky if r["SkutecnyPocetKs"] is not None})
    pohyby = repozitar.pohyby_po_vodoznaku(spoj, vodoznaky)
    vysledky = []
    for r in radky:
        i = r["VnitrniPoziceID"]
        misto = mista.get(i)
        zapsano = r["SkutecnyPocetKs"] is not None
        vysledek, rozdil = (domena.vyhodnot(r["OcekavanyDilID"], r["OcekavanyPocetKs"], r["SkutecnyDilID"],
                                            r["SkutecnyPocetKs"]) if zapsano else (None, 0))
        aktualni = obsah[i].pocet_ks if obsah.get(i) and obsah[i].dil_id == r["OcekavanyDilID"] else 0
        stav = domena.stav_polozky(zapsano=zapsano, dil_id=r["OcekavanyDilID"], vysledek=vysledek,
                                   rozdil_ks=rozdil, aktualni_pocet_ks=aktualni, aktivni=misto is not None,
                                   uzavrena=uzavrena, pohyby=pohyby.get(i, []))
        vysledky.append(domena.Polozka(i, misto.kod if misto else str(i), misto.typ_boxu if misto else "",
                                       r["OcekavanyDilID"], r["OcekavanyPocetKs"], r["SkutecnyDilID"],
                                       r["SkutecnyPocetKs"], aktualni, stav, r["DatumKontroly"]))
    return vysledky


def _detail(spoj: Spojeni, radek: dict[str, Any]) -> InventuraDetail:
    polozky = _polozky(spoj, radek["InventuraID"], uzavrena=radek["StavInventury"] != "ROZPRACOVANA")
    return InventuraDetail(**_radek(spoj, radek, polozky).model_dump(exclude={"transakce_id", "varovani"}),
                           polozky=[_vystup_polozky(bool(radek["SlepaInventura"]), p) for p in polozky])


def _radek(spoj: Spojeni, radek: dict[str, Any], polozky: list[domena.Polozka] | None = None) -> InventuraRadek:
    polozky = (polozky if polozky is not None else
               _polozky(spoj, radek["InventuraID"], uzavrena=radek["StavInventury"] != "ROZPRACOVANA"))
    return InventuraRadek(
        inventura_id=radek["InventuraID"], typ_rozsahu=radek["TypRozsahu"], cil_id=repozitar.cil(radek),
        stav_inventury=radek["StavInventury"], slepa=bool(radek["SlepaInventura"]),
        datum_zahajeni=radek["DatumZahajeni"], datum_dokonceni=radek["DatumDokonceni"],
        zalozil_uzivatel_id=radek["ZalozilUzivatelID"], pocet_polozek=len(polozky),
        pocet_zapsanych=sum(1 for p in polozky if p.stav != "CEKA"),
        pocet_k_prepoctu=sum(1 for p in polozky if p.stav == "PREPOCITAT"), poznamka=radek["Poznamka"])


def _vystup_polozky(slepa: bool, p: domena.Polozka) -> PolozkaInventury:
    zapsano = p.skutecny_pocet_ks is not None
    skryt = slepa and not zapsano
    vysledek, rozdil = (domena.vyhodnot(p.ocekavany_dil_id, p.ocekavany_pocet_ks, p.skutecny_dil_id,
                                        p.skutecny_pocet_ks) if zapsano else (None, None))
    return PolozkaInventury(
        vnitrni_pozice_id=p.vnitrni_pozice_id, kod=p.kod, typ_boxu=p.typ_boxu, stav_polozky=p.stav,
        ocekavany_dil_id=None if skryt else p.ocekavany_dil_id,
        ocekavany_pocet_ks=None if skryt else p.ocekavany_pocet_ks,
        skutecny_dil_id=p.skutecny_dil_id, skutecny_pocet_ks=p.skutecny_pocet_ks, rozdil_ks=rozdil,
        vyhodnoceni=vysledek, datum_kontroly=p.datum_kontroly)


def _preloz_cile(spoj: Spojeni, polozky: list[domena.Polozka],
                 zadane: dict[int, str]) -> dict[int, struktura.MistoInfo]:
    """Cíle ze vstupu dokončení přeloží ze štítku na pozici; cíl se smí poslat jen pro jiný díl (D-27).

    Vrací {VnitrniPoziceID položky: cílová pozice}. Chyby: VALIDATION_ERROR (pole cileJinyDil),
    NOT_FOUND a INVALID_BARCODE/WRONG_SCAN_LEVEL z ostrova C.
    """
    podle_pozice = {p.vnitrni_pozice_id: p for p in polozky}
    cile: dict[int, struktura.MistoInfo] = {}
    for pozice_id, kod in zadane.items():
        polozka = podle_pozice.get(pozice_id)
        if polozka is None or not domena.jiny_dil(polozka):
            raise chyba_vstupu(f"Pozice {pozice_id} nemá nalezený jiný díl – cíl se zadává jen pro JINY_DIL.",
                               domena.POLE_CIL)
        cile[pozice_id] = struktura.najdi_vnitrni_pozici(spoj, kod)
    return cile


def _over_cile(spoj: Spojeni, polozky: list[domena.Polozka],
               cile: Mapping[int, struktura.MistoInfo]) -> dict[int, int]:
    """Ověří každý cíl uvnitř transakce (D-27) a vrátí {pozice položky: pozice cíle}.

    Současná pozice položky cílem být může – po odúčtování očekávaného dílu je volná, proto se
    její obsah neposílá a posoudí se jako jakýkoli jiný cíl. Stejná DYN pozice cílem dvou položek
    oběma neslouží: až se zaúčtuje první nález, volná není, takže se posoudí jako obsazená.
    """
    podle_pozice = {p.vnitrni_pozice_id: p for p in polozky}
    overene: dict[int, int] = {}
    obsazeno: dict[int, sklad.ObsahInfo] = {}    # DYN cíl, na který už míří nález jiné položky
    for pozice_id, cil in cile.items():
        polozka = podle_pozice[pozice_id]
        if not domena.jiny_dil(polozka):
            continue    # souběžný zápis položku mezitím přepsal – cíl už nic nepotřebuje
        vlastni_cil = cil.vnitrni_pozice_id == pozice_id
        cil_obsah = (None if vlastni_cil
                     else obsazeno.get(cil.vnitrni_pozice_id)
                     or sklad.obsah_mist(spoj, [cil.vnitrni_pozice_id]).get(cil.vnitrni_pozice_id))
        stat = next((s for s in sklad.stat_mista(spoj, vnitrni_pozice_ids=[cil.vnitrni_pozice_id])
                     if s.dil_id == polozka.skutecny_dil_id), None)
        dil = dily.nacti_dily(spoj, [polozka.skutecny_dil_id])[polozka.skutecny_dil_id]
        domena.over_cil_jiny_dil(cil, nalezeny_dil_id=polozka.skutecny_dil_id, potreba=dil.potreba,
                                 obsah_cilu=cil_obsah, stat_misto_cilu=stat, kod_pozice=polozka.kod)
        if cil.typ_boxu == "DYN":     # STAT místo naproti tomu kusů z více nálezů snese víc (D-27)
            obsazeno[cil.vnitrni_pozice_id] = sklad.ObsahInfo(cil.vnitrni_pozice_id, polozka.skutecny_dil_id,
                                                              polozka.skutecny_pocet_ks)
        overene[pozice_id] = cil.vnitrni_pozice_id
    return overene


def _zauctuj_korekce(spoj: Spojeni, kdo: Kontext, korekce: list[domena.Korekce],
                     poznamka: str | None) -> list[int]:
    """Zaúčtuje plán korekcí (21.1.7) přes ostrov E – pohyby INVENTURA; vrací jejich PohybID.

    Dva průchody: nejdřív absolutní stavy, které vycházejí ze stavu načteného před účtováním,
    teprve pak přičtení na cíle jiného dílu – cílem bývá i inventarizovaná pozice a kdyby se na ni
    přičetlo dřív, její absolutní korekce by přičtené kusy přepsala. Před každým přičtením se čte
    aktuální obsah cíle, takže dvě přičtení na týž cíl kusy sečtou.
    """
    pohyby = []
    for k in korekce:
        if k.novy_stav_ks is not None:
            pohyby.append(sklad.zauctuj_korekci(spoj, kdo, k.vnitrni_pozice_id, k.dil_id, k.novy_stav_ks,
                                                "INVENTURA", poznamka).pohyb_id)
    for k in korekce:
        if k.pricist_ks is not None:
            soucasny = sklad.obsah_mist(spoj, [k.vnitrni_pozice_id]).get(k.vnitrni_pozice_id)
            novy_stav = (soucasny.pocet_ks if soucasny else 0) + k.pricist_ks
            pohyby.append(sklad.zauctuj_korekci(spoj, kdo, k.vnitrni_pozice_id, k.dil_id, novy_stav,
                                                "INVENTURA", poznamka).pohyb_id)
    return pohyby
