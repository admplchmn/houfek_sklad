"""Služby ostrova G – Přehledy a navigace. Jen čtení (@cteni) – ostrov nic nezapisuje.

Fáze 0 (KOSTRA): data se skládají přes rozhraní ostrovů B, C, D a E nad jejich vzorovými daty;
historie pohybů je vzorová (ukazky). Fáze 1: každý přehled je jeden dotaz nad pohledy v_Misto,
v_Dil, v_ObsahPozice, v_ZasobaDilu, v_PohybDetail, v_Uzivatel a v_SkladovaTransakce (P2) –
podpisy funkcí ani výstupy se nemění. Výkon dotazů a stránkování v SQL patří sem (7.7).
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from app.ostrovy.dily import rozhrani as dily
from app.ostrovy.identita import rozhrani as identita
from app.ostrovy.sklad import rozhrani as sklad
from app.ostrovy.struktura import rozhrani as struktura
from app.platforma.chyby import AppError
from app.platforma.db import Spojeni, cteni
from app.platforma.kontrakty import CiselnikRadek, Strana
from app.platforma.typy import PolozkaCiselniku

from . import domena
from .kontrakty import (
    BoxSvg,
    CiselnikyVystup,
    HledaniFiltr,
    KartaDilu,
    LaserFiltr,
    LaserRadek,
    ObsahNaPozici,
    PohybHistorie,
    PohybyFiltr,
    PoziceSvg,
    RozlozeniVystup,
    SouhrnZasob,
    StatZasoba,
    TransakceDetail,
    UmisteniDilu,
    VysledekHledani,
    Vysledky,
    ZasobaRadek,
    ZasobyFiltr,
    ZasobyVystup,
    Zvyrazneni,
)

MAX_VYSLEDKU = 50
POCET_POHYBU_NA_KARTE = 10
PORADI_STAVU = {"VYCERPANO": 0, "POD_MINIMEM": 1, "NA_MINIMU": 2, "OK": 3}

# --- sken a hledání ---------------------------------------------------------------------------------


@cteni
def sken(spoj: Spojeni, kod: str) -> Vysledky:
    """Naskenovaný nebo zadaný kód (kap. 16): kód skladu → jeden objekt; jinak číslo dílu – přesná
    shoda, jinak část čísla nebo názvu. Chyby: INVALID_BARCODE (poškozený kód skladu), NOT_FOUND."""
    rozlozeny = struktura.rozloz_kod(kod)
    if rozlozeny.typ != "TEXT":
        return Vysledky(polozky=[_objekt(spoj, kod)], presny=True)
    try:
        dil = dily.najdi_dil(spoj, rozlozeny.text)
    except AppError as chyba:
        if chyba.kod != "NOT_FOUND":
            raise
        nalezene = dily.hledej_dily(spoj, rozlozeny.text, limit=MAX_VYSLEDKU)
        return Vysledky(polozky=[_vysledek_dilu(spoj, d) for d in nalezene], presny=False)
    return Vysledky(polozky=[_vysledek_dilu(spoj, dil)], presny=True)


@cteni
def hledej(spoj: Spojeni, filtr: HledaniFiltr) -> Vysledky:
    """Univerzální hledání (21.1.2): kód skladu, nebo díly s filtry podle dílu i jeho umístění."""
    rozlozeny = struktura.rozloz_kod(filtr.q)
    if rozlozeny.typ != "TEXT":
        return Vysledky(polozky=[_objekt(spoj, filtr.q)], presny=True)
    kody = _kody_ciselniku(spoj)
    vysledky = []
    for dil in dily.hledej_dily(spoj, rozlozeny.text, limit=MAX_VYSLEDKU):
        if not _dil_projde(dil, kody, filtr.material_id, filtr.tloustka_id, filtr.prvni_operace_id):
            continue
        umisteni = _umisteni(spoj, dil.dil_id)
        if filtr.typ_boxu and not any(m.typ_boxu == filtr.typ_boxu for m, _ in umisteni):
            continue
        if filtr.pracoviste_id and not any(m.pracoviste == kody["pracoviste"].get(filtr.pracoviste_id)
                                           for m, _ in umisteni):
            continue
        if filtr.stav_zasoby:
            stat = _stat(spoj, dil.dil_id, umisteni)
            if stat is None or stat.stav_zasoby != filtr.stav_zasoby:
                continue
        vysledky.append(_vysledek_dilu(spoj, dil, umisteni))
    return Vysledky(polozky=vysledky, presny=False)


# --- SVG úrovně -------------------------------------------------------------------------------------


@cteni
def rozlozeni(spoj: Spojeni, uroven_id: int) -> RozlozeniVystup:
    """Geometrie z ostrova C (17.1) + obsah z E + barva boxu (7.2). Chyby: NOT_FOUND."""
    geometrie = struktura.rozlozeni_urovne(spoj, uroven_id)
    ids = [p.vnitrni_pozice_id for b in geometrie.boxy for p in b.pozice]
    obsah = sklad.obsah_mist(spoj, ids)
    dil_ids = sorted({o.dil_id for o in obsah.values()})
    nactene = dily.nacti_dily(spoj, dil_ids)
    cisla = {i: d.identifikacni_cislo for i, d in nactene.items()}
    vaulty = {i: d.vault_url for i, d in nactene.items()}
    boxy = []
    for b in geometrie.boxy:
        stav = struktura.stav_boxu(b.blokovany, sum(1 for p in b.pozice if p.vnitrni_pozice_id in obsah))
        boxy.append(BoxSvg(
            box_id=b.box_id, kod_boxu=b.kod_boxu, typ_boxu=b.typ_boxu, kod_cleneni=b.kod_cleneni, stav_boxu=stav,
            barva=domena.barva_boxu(stav, b.typ_boxu), x_mm=b.x_mm, y_mm=b.y_mm, delka_mm=b.delka_mm,
            hloubka_mm=b.hloubka_mm, pozice=[
                PoziceSvg(vnitrni_pozice_id=p.vnitrni_pozice_id, kod_pozice=p.kod_pozice,
                          kod=f"{b.kod_boxu}-{p.kod_pozice}", velikost=p.velikost, blokovana=p.blokovano,
                          rel_x=p.rel_x, rel_y=p.rel_y, rel_sirka=p.rel_sirka, rel_hloubka=p.rel_hloubka,
                          dil_id=obsah[p.vnitrni_pozice_id].dil_id if p.vnitrni_pozice_id in obsah else None,
                          identifikacni_cislo=cisla.get(obsah[p.vnitrni_pozice_id].dil_id)
                          if p.vnitrni_pozice_id in obsah else None,
                          pocet_ks=obsah[p.vnitrni_pozice_id].pocet_ks if p.vnitrni_pozice_id in obsah else 0,
                          vault_url=vaulty.get(obsah[p.vnitrni_pozice_id].dil_id)
                          if p.vnitrni_pozice_id in obsah else None)
                for p in b.pozice], kod_pozice_urovne=b.kod_pozice_urovne))
    return RozlozeniVystup(uroven_id=geometrie.uroven_id, kod_urovne=geometrie.kod_urovne,
                           regal_id=geometrie.regal_id, kod_regalu=geometrie.kod_regalu,
                           pracoviste=geometrie.pracoviste, delka_plochy_mm=geometrie.delka_plochy_mm,
                           hloubka_plochy_mm=geometrie.hloubka_plochy_mm, sirka_svg_mm=geometrie.sirka_svg_mm,
                           vyska_svg_mm=geometrie.vyska_svg_mm, boxy=boxy)


# --- karta dílu, monitoring, laser ------------------------------------------------------------------


@cteni
def karta_dilu(spoj: Spojeni, dil_id: int) -> KartaDilu:
    """Karta dílu (kap. 15): kmenová data, STAT místo s min/max, všechna umístění a poslední pohyby."""
    dil = dily.nacti_dily(spoj, [dil_id]).get(dil_id)
    if dil is None:
        raise AppError("NOT_FOUND", f"Díl {dil_id} neexistuje.")
    umisteni = _umisteni(spoj, dil_id)
    stat = _stat(spoj, dil_id, umisteni)
    dyn_ks = sum(o.pocet_ks for m, o in umisteni if m.typ_boxu == "DYN")
    stat_ks = sum(o.pocet_ks for m, o in umisteni if m.typ_boxu == "STAT")
    pohyby = sorted((p for p in _pohyby_vzory() if p.dil_id == dil_id), key=lambda p: p.datum_cas, reverse=True)
    return KartaDilu(
        dil_id=dil.dil_id, identifikacni_cislo=dil.identifikacni_cislo, nazev=dil.nazev, material=dil.material,
        tloustka_mm=dil.tloustka_mm, prvni_operace=dil.prvni_operace, standardni_davka_ks=dil.standardni_davka_ks,
        velikost=dil.potreba.velikost if dil.potreba else None, vault_url=dil.vault_url, stat=stat, dyn_ks=dyn_ks,
        celkem_ks=dyn_ks + stat_ks, umisteni=_umisteni_radky(umisteni),
        posledni_pohyby=_historie(spoj, pohyby[:POCET_POHYBU_NA_KARTE]))


@cteni
def zasoby(spoj: Spojeni, filtr: ZasobyFiltr) -> ZasobyVystup:
    """Centrální monitoring (13.1): díly se STAT místem, STAT a DYN zvlášť, stav podle STAT (kap. 13).

    jenSeStat=false přidá díly, které leží jen v DYN: bez minima a stavu, řazené na konec.
    Souhrn počítá díly se STAT místem po filtrech dílu a pracoviště – „jen problémové“ ho nemění.
    Řazení: nejhorší stav první, pak číslo dílu.
    """
    kody = _kody_ciselniku(spoj)
    pracoviste = kody["pracoviste"].get(filtr.pracoviste_id) if filtr.pracoviste_id else None
    radky = []
    for stat in sklad.stat_mista(spoj):
        dil = dily.nacti_dily(spoj, [stat.dil_id])[stat.dil_id]
        if not _dil_projde(dil, kody, filtr.material_id, filtr.tloustka_id, filtr.prvni_operace_id):
            continue
        if pracoviste and _pracoviste_mista(spoj, stat.vnitrni_pozice_id) != pracoviste:
            continue
        radky.append(_radek_zasoby(spoj, stat.dil_id, stat))
    if not filtr.jen_se_stat:
        for dil_id in _dily_jen_v_dyn(spoj):
            dil = dily.nacti_dily(spoj, [dil_id])[dil_id]
            radek = _radek_zasoby(spoj, dil_id, None)
            if _dil_projde(dil, kody, filtr.material_id, filtr.tloustka_id, filtr.prvni_operace_id) and (
                    not pracoviste or any(_pracoviste_mista(spoj, m.vnitrni_pozice_id) == pracoviste
                                          for m in radek.mista)):
                radky.append(radek)
    pocty = domena.souhrn_zasob(r.stav_zasoby for r in radky if r.stav_zasoby)
    vybrane = sorted((r for r in radky if (not filtr.jen_problemove or r.stav_zasoby in domena.PROBLEMOVE)
                      and filtr.stav_zasoby in (None, r.stav_zasoby)),
                     key=lambda r: (PORADI_STAVU.get(r.stav_zasoby, len(PORADI_STAVU)), r.identifikacni_cislo))
    zacatek = (filtr.strana - 1) * filtr.velikost
    return ZasobyVystup(
        souhrn=SouhrnZasob(sledovane=pocty["sledovane"], ok=pocty["OK"], na_minimu=pocty["NA_MINIMU"],
                           pod_minimem=pocty["POD_MINIMEM"], vycerpano=pocty["VYCERPANO"]),
        polozky=vybrane[zacatek:zacatek + filtr.velikost], strana=filtr.strana, velikost=filtr.velikost,
        celkem=len(vybrane))


@cteni
def laser(spoj: Spojeni, filtr: LaserFiltr) -> Strana[LaserRadek]:
    """Díly k doplnění na laser (kap. 14): první operace LASER (nebo zvolená), STAT pod maximem.

    Chybí ve STAT = Maximum − STAT; doporučeno podle Q-22 (přepínač odecitatDyn). Řazení: nejvíc chybí první.
    """
    kody = _kody_ciselniku(spoj)
    operace = kody["operace"].get(filtr.prvni_operace_id) if filtr.prvni_operace_id else "LASER"
    radky = []
    for stat in sklad.stat_mista(spoj):
        dil = dily.nacti_dily(spoj, [stat.dil_id])[stat.dil_id]
        if stat.maximalni_ks is None or dil.prvni_operace != operace \
                or not _dil_projde(dil, kody, filtr.material_id, filtr.tloustka_id, None):
            continue
        zasoba = _radek_zasoby(spoj, stat.dil_id, stat)
        chybi, doporuceno = domena.doporuceni_laser(stat.maximalni_ks, zasoba.stat_ks, zasoba.dyn_ks,
                                                    dil.standardni_davka_ks, odecitat_dyn=filtr.odecitat_dyn)
        if filtr.jen_pod_maximem and chybi == 0:
            continue
        radky.append(LaserRadek(dil_id=dil.dil_id, identifikacni_cislo=dil.identifikacni_cislo, material=dil.material,
                                tloustka_mm=dil.tloustka_mm, prvni_operace=dil.prvni_operace, stat_ks=zasoba.stat_ks,
                                dyn_ks=zasoba.dyn_ks, maximalni_ks=stat.maximalni_ks, chybi_ve_stat_ks=chybi,
                                doporuceno_ks=doporuceno, standardni_davka_ks=dil.standardni_davka_ks))
    radky.sort(key=lambda r: (-r.chybi_ve_stat_ks, r.identifikacni_cislo))
    zacatek = (filtr.strana - 1) * filtr.velikost
    return Strana[LaserRadek](polozky=radky[zacatek:zacatek + filtr.velikost], strana=filtr.strana,
                              velikost=filtr.velikost, celkem=len(radky))


# --- historie ---------------------------------------------------------------------------------------


@cteni
def pohyby(spoj: Spojeni, filtr: PohybyFiltr) -> Strana[PohybHistorie]:
    """Historie pohybů, nejnovější první; období od–do včetně (dny v časové zóně Europe/Prague)."""
    pozice_id = filtr.vnitrni_pozice_id
    if filtr.kod:
        pozice_id = struktura.najdi_vnitrni_pozici(spoj, filtr.kod).vnitrni_pozice_id
    vybrane = sorted((p for p in _pohyby_vzory()
                      if filtr.dil_id in (None, p.dil_id) and pozice_id in (None, p.vnitrni_pozice_id)
                      and filtr.typ_pohybu in (None, p.typ_pohybu) and filtr.uzivatel_id in (None, p.uzivatel_id)
                      and (filtr.od is None or p.datum_cas.date() >= filtr.od)
                      and (filtr.do is None or p.datum_cas.date() <= filtr.do)),
                     key=lambda p: p.datum_cas, reverse=True)
    zacatek = (filtr.strana - 1) * filtr.velikost
    return Strana[PohybHistorie](polozky=_historie(spoj, vybrane[zacatek:zacatek + filtr.velikost]),
                                 strana=filtr.strana, velikost=filtr.velikost, celkem=len(vybrane))


@cteni
def transakce(spoj: Spojeni, transakce_id: uuid.UUID) -> TransakceDetail:
    """Skladová transakce s pohyby (např. PRESUN-OUT + PRESUN-IN se stejným TransakceID). Chyby: NOT_FOUND."""
    from . import ukazky  # KOSTRA (fáze 0)

    vzory = [p for p in _pohyby_vzory() if ukazky.transakce_id(p.pohyb_id) == transakce_id]
    if not vzory:
        raise AppError("NOT_FOUND", f"Transakce {transakce_id} neexistuje.")
    prvni = vzory[0]
    uzivatel = identita.nacti_uzivatele(spoj, [prvni.uzivatel_id]).get(prvni.uzivatel_id)
    return TransakceDetail(skladova_transakce_id=transakce_id, typ_operace=prvni.typ_operace,
                           datum_cas=prvni.datum_cas, uzivatel_id=prvni.uzivatel_id,
                           cele_jmeno=uzivatel.cele_jmeno if uzivatel else None, terminal_id=prvni.terminal_id,
                           pohyby=_historie(spoj, vzory))


@cteni
def ciselniky(spoj: Spojeni) -> CiselnikyVystup:
    """Všechny hodnoty pro filtry najednou (7.7): číselníky ostrovů C, D, E a pevné technické kódy."""
    c, d, e = struktura.nacti_ciselniky(spoj), dily.nacti_ciselniky(spoj), sklad.nacti_ciselniky(spoj)
    return CiselnikyVystup(pracoviste=_radky(c["pracoviste"]), velikosti=_radky(c["velikosti"]),
                           materialy=_radky(d["materialy"]), tloustky=_radky(d["tloustky"]),
                           operace=_radky(d["operace"]), typy_pohybu=_radky(e["typyPohybu"]),
                           typy_boxu=["DYN", "STAT"], stavy_zasoby=list(domena.STAVY_ZASOBY))


# --- pomocné -------------------------------------------------------------------------------------


def _zvyrazneni(misto: struktura.MistoInfo) -> Zvyrazneni:
    return Zvyrazneni(regal_id=misto.regal_id, uroven_id=misto.uroven_id, box_id=misto.box_id,
                      vnitrni_pozice_id=misto.vnitrni_pozice_id)


def _objekt(spoj: Spojeni, kod: str) -> VysledekHledani:
    objekt = struktura.najdi_objekt(spoj, kod)
    popis = obsah_pozice = None
    if objekt.typ == "POZICE" and objekt.vnitrni_pozice_id is not None:
        obsah = sklad.obsah_mist(spoj, [objekt.vnitrni_pozice_id]).get(objekt.vnitrni_pozice_id)
        dil = dily.nacti_dily(spoj, [obsah.dil_id]).get(obsah.dil_id) if obsah else None
        popis = f"{dil.identifikacni_cislo} · {obsah.pocet_ks} ks" if obsah and dil else "prázdná"
        if obsah and dil:
            obsah_pozice = ObsahNaPozici(dil_id=dil.dil_id, identifikacni_cislo=dil.identifikacni_cislo,
                                         pocet_ks=obsah.pocet_ks)
    ident = {"REGAL": objekt.regal_id, "BOX": objekt.box_id, "POZICE": objekt.vnitrni_pozice_id}[objekt.typ]
    return VysledekHledani(typ=objekt.typ, id=ident or 0, kod=objekt.kod, popis=popis, adresa=objekt.adresa,
                           zvyrazneni=Zvyrazneni(regal_id=objekt.regal_id, uroven_id=objekt.uroven_id,
                                                 box_id=objekt.box_id, vnitrni_pozice_id=objekt.vnitrni_pozice_id),
                           obsah=obsah_pozice)


def _umisteni(spoj: Spojeni, dil_id: int) -> list[tuple[struktura.MistoInfo, sklad.ObsahInfo]]:
    """Všechna místa s obsahem dílu: STAT první, pak DYN podle čísla boxu (domena.poradi_umisteni).

    KOSTRA: přes celý sklad (vzorek je malý); fáze 1: v_ObsahPozice WHERE DilID = ? JOIN v_Misto.
    """
    mista = struktura.nacti_mista(spoj, struktura.pozice_v_rozsahu(spoj, "FULL", None))
    obsah = sklad.obsah_mist(spoj, list(mista))
    vybrane = [(mista[i], o) for i, o in obsah.items() if o.dil_id == dil_id and i in mista]
    return sorted(vybrane, key=lambda mo: domena.poradi_umisteni(mo[0].typ_boxu, mo[0].kod_boxu, mo[0].poradi_v_boxu))


def _umisteni_radky(umisteni: list[tuple[struktura.MistoInfo, sklad.ObsahInfo]]) -> list[UmisteniDilu]:
    return [UmisteniDilu(vnitrni_pozice_id=m.vnitrni_pozice_id, kod=m.kod, adresa=m.adresa, typ_boxu=m.typ_boxu,
                         pocet_ks=o.pocet_ks, zvyrazneni=_zvyrazneni(m)) for m, o in umisteni]


def _dily_jen_v_dyn(spoj: Spojeni) -> list[int]:
    """Díly s obsahem, které nemají aktivní STAT místo. KOSTRA: přes celý sklad; fáze 1: v_ObsahPozice
    bez řádku v v_ZasobaDilu."""
    mista = struktura.nacti_mista(spoj, struktura.pozice_v_rozsahu(spoj, "FULL", None))
    se_stat = {s.dil_id for s in sklad.stat_mista(spoj)}
    return sorted({o.dil_id for o in sklad.obsah_mist(spoj, list(mista)).values()} - se_stat)


def _stat(spoj: Spojeni, dil_id: int, umisteni) -> StatZasoba | None:
    stat = next(iter(sklad.stat_mista(spoj, dil_ids=[dil_id])), None)
    if stat is None:
        return None
    misto = struktura.nacti_mista(spoj, [stat.vnitrni_pozice_id]).get(stat.vnitrni_pozice_id)
    stav_ks = next((o.pocet_ks for m, o in umisteni if m.vnitrni_pozice_id == stat.vnitrni_pozice_id), 0)
    return StatZasoba(stat_umisteni_id=stat.stat_umisteni_id, kod=misto.kod if misto else "?",
                      minimalni_ks=stat.minimalni_ks, optimalni_ks=stat.optimalni_ks,
                      maximalni_ks=stat.maximalni_ks, stav_ks=stav_ks,
                      stav_zasoby=sklad.stav_zasoby(stav_ks, stat.minimalni_ks),
                      kod_boxu=misto.kod_boxu if misto else "?",
                      chybi_do_maxima_ks=max(0, stat.maximalni_ks - stav_ks) if stat.maximalni_ks is not None else None)


def _vysledek_dilu(spoj: Spojeni, dil: dily.DilInfo, umisteni=None) -> VysledekHledani:
    umisteni = umisteni if umisteni is not None else _umisteni(spoj, dil.dil_id)
    prvni = umisteni[0][0] if umisteni else None
    return VysledekHledani(typ="DIL", id=dil.dil_id, kod=dil.identifikacni_cislo, popis=dil.nazev,
                           adresa=prvni.adresa if prvni else None,
                           zvyrazneni=_zvyrazneni(prvni) if prvni else None, obsah=None)


def _radek_zasoby(spoj: Spojeni, dil_id: int, stat: sklad.StatMistoInfo | None) -> ZasobaRadek:
    """Řádek monitoringu (13.1). Díl bez STAT místa (stat None) nemá minimum ani stav, zvýrazní se jeho první místo."""
    dil = dily.nacti_dily(spoj, [dil_id])[dil_id]
    umisteni = _umisteni(spoj, dil_id)
    stat_ks = sum(o.pocet_ks for m, o in umisteni if stat and m.vnitrni_pozice_id == stat.vnitrni_pozice_id)
    dyn = [(m, o) for m, o in umisteni if m.typ_boxu == "DYN"]
    misto = struktura.nacti_mista(spoj, [stat.vnitrni_pozice_id])[stat.vnitrni_pozice_id] if stat else umisteni[0][0]
    return ZasobaRadek(
        dil_id=dil.dil_id, identifikacni_cislo=dil.identifikacni_cislo, nazev=dil.nazev, material=dil.material,
        tloustka_mm=dil.tloustka_mm, prvni_operace=dil.prvni_operace, stat_ks=stat_ks,
        dyn_ks=sum(o.pocet_ks for _, o in dyn), celkem_ks=stat_ks + sum(o.pocet_ks for _, o in dyn),
        minimalni_ks=stat.minimalni_ks if stat else None, maximalni_ks=stat.maximalni_ks if stat else None,
        stav_zasoby=sklad.stav_zasoby(stat_ks, stat.minimalni_ks) if stat else None,
        umisteni=domena.text_umisteni(stat is not None, len(dyn)), zvyrazneni=_zvyrazneni(misto),
        mista=_umisteni_radky(umisteni))


def _kody_ciselniku(spoj: Spojeni) -> dict[str, dict[int, str]]:
    """ID → kód pro filtry (filtry jsou ID podle 4.2, rozhraní dílů filtruje kódem)."""
    d, c = dily.nacti_ciselniky(spoj), struktura.nacti_ciselniky(spoj)
    return {"materialy": {p.id: p.kod for p in d["materialy"]}, "tloustky": {p.id: p.kod for p in d["tloustky"]},
            "operace": {p.id: p.kod for p in d["operace"]}, "pracoviste": {p.id: p.kod for p in c["pracoviste"]}}


def _dil_projde(dil: dily.DilInfo, kody: dict[str, dict[int, str]], material_id: int | None,
                tloustka_id: int | None, prvni_operace_id: int | None) -> bool:
    if material_id and dil.material != kody["materialy"].get(material_id):
        return False
    tloustka = kody["tloustky"].get(tloustka_id) if tloustka_id else None
    if tloustka_id and (tloustka is None or dil.tloustka_mm != Decimal(tloustka)):
        return False
    return not (prvni_operace_id and dil.prvni_operace != kody["operace"].get(prvni_operace_id))


def _pracoviste_mista(spoj: Spojeni, vnitrni_pozice_id: int) -> str | None:
    misto = struktura.nacti_mista(spoj, [vnitrni_pozice_id]).get(vnitrni_pozice_id)
    return misto.pracoviste if misto else None


def _pohyby_vzory():
    from . import ukazky  # KOSTRA (fáze 0)

    return ukazky.POHYBY


def _historie(spoj: Spojeni, vzory) -> list[PohybHistorie]:
    """Pohyby doplněné o čísla dílů, kódy pozic a jména (přes rozhraní; fáze 1 v jednom dotazu)."""
    from . import ukazky  # KOSTRA (fáze 0)

    cisla = {i: d.identifikacni_cislo for i, d in dily.nacti_dily(spoj, sorted({p.dil_id for p in vzory})).items()}
    kody = {i: m.kod for i, m in struktura.nacti_mista(spoj, sorted({p.vnitrni_pozice_id for p in vzory})).items()}
    uzivatele = identita.nacti_uzivatele(spoj, sorted({p.uzivatel_id for p in vzory}))
    jmena = {i: u.cele_jmeno for i, u in uzivatele.items()}
    return [PohybHistorie(pohyb_id=p.pohyb_id, datum_cas=p.datum_cas, typ_pohybu=p.typ_pohybu, dil_id=p.dil_id,
                          identifikacni_cislo=cisla.get(p.dil_id),
                          vnitrni_pozice_id=p.vnitrni_pozice_id, kod=kody.get(p.vnitrni_pozice_id),
                          mnozstvi=p.mnozstvi, stav_pred_ks=p.stav_pred_ks, stav_po_ks=p.stav_po_ks,
                          uzivatel_id=p.uzivatel_id, cele_jmeno=jmena.get(p.uzivatel_id), terminal_id=p.terminal_id,
                          skladova_transakce_id=ukazky.transakce_id(p.pohyb_id), poznamka=p.poznamka)
            for p in vzory]


def _radky(polozky: tuple[PolozkaCiselniku, ...]) -> list[CiselnikRadek]:
    return [CiselnikRadek(id=p.id, kod=p.kod, nazev=p.nazev, aktivni=p.aktivni) for p in polozky]
