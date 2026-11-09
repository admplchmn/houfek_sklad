"""Služby ostrova G – Přehledy a navigace. Jen čtení (@cteni) – ostrov nic nezapisuje.

Fáze 1: každý přehled je jeden dotaz nad pohledy v_* (`repozitar.py`, S-18); data se neskládají
z více volání rozhraní. Rozhraní zůstává tam, kde jedno volání stačí: C překládá kód skladu
a geometrii úrovně, D hledá díly podle čísla, E dává číselníky pohybů.

Pravidla jsou jediná v `domena.py` (barva boxu, pořadí umístění, doporučení pro laser), proto
se monitoring a laser vyhodnocují a řadí tady – v SQL by se musela opsat.
"""
from __future__ import annotations

import uuid
from typing import Any

from app.ostrovy.dily import rozhrani as dily
from app.ostrovy.sklad import rozhrani as sklad
from app.ostrovy.struktura import rozhrani as struktura
from app.platforma.chyby import AppError
from app.platforma.db import Spojeni, cteni
from app.platforma.kontrakty import CiselnikRadek, Strana
from app.platforma.typy import PolozkaCiselniku

from . import domena, repozitar
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
        nalezene = [(d.dil_id, d.identifikacni_cislo, d.nazev)
                    for d in dily.hledej_dily(spoj, rozlozeny.text, limit=MAX_VYSLEDKU)]
        return Vysledky(polozky=_vysledky_dilu(spoj, nalezene), presny=False)
    return Vysledky(polozky=_vysledky_dilu(spoj, [(dil.dil_id, dil.identifikacni_cislo, dil.nazev)]), presny=True)


@cteni
def hledej(spoj: Spojeni, filtr: HledaniFiltr) -> Vysledky:
    """Univerzální hledání (21.1.2): kód skladu, nebo díly s filtry podle dílu i jeho umístění.

    Filtry umístění a zásobového stavu jsou součástí dotazu (21.1.2), umístění výsledků
    se dopočítá jedním hromadným dotazem.
    """
    rozlozeny = struktura.rozloz_kod(filtr.q)
    if rozlozeny.typ != "TEXT":
        return Vysledky(polozky=[_objekt(spoj, filtr.q)], presny=True)
    nalezene = [(r["DilID"], r["IdentifikacniCislo"], r["NazevDilu"])
                for r in repozitar.hledani(spoj, rozlozeny.text, filtr, MAX_VYSLEDKU)]
    return Vysledky(polozky=_vysledky_dilu(spoj, nalezene), presny=False)


# --- SVG úrovně -------------------------------------------------------------------------------------


@cteni
def rozlozeni(spoj: Spojeni, uroven_id: int) -> RozlozeniVystup:
    """Geometrie z ostrova C (17.1) + obsah pozic jedním dotazem + barva boxu (7.2). Chyby: NOT_FOUND."""
    geometrie = struktura.rozlozeni_urovne(spoj, uroven_id)
    obsah = _obsah_pozic(spoj, [p.vnitrni_pozice_id for b in geometrie.boxy for p in b.pozice])
    boxy = []
    for b in geometrie.boxy:
        stav = struktura.stav_boxu(b.blokovany, sum(1 for p in b.pozice if p.vnitrni_pozice_id in obsah))
        boxy.append(BoxSvg(box_id=b.box_id, kod_boxu=b.kod_boxu, typ_boxu=b.typ_boxu, kod_cleneni=b.kod_cleneni,
                           stav_boxu=stav, barva=domena.barva_boxu(stav, b.typ_boxu), x_mm=b.x_mm, y_mm=b.y_mm,
                           delka_mm=b.delka_mm, hloubka_mm=b.hloubka_mm,
                           pozice=[_pozice_svg(b.kod_boxu, p, obsah) for p in b.pozice],
                           kod_pozice_urovne=b.kod_pozice_urovne))
    return RozlozeniVystup(uroven_id=geometrie.uroven_id, kod_urovne=geometrie.kod_urovne,
                           regal_id=geometrie.regal_id, kod_regalu=geometrie.kod_regalu,
                           pracoviste=geometrie.pracoviste, delka_plochy_mm=geometrie.delka_plochy_mm,
                           hloubka_plochy_mm=geometrie.hloubka_plochy_mm, sirka_svg_mm=geometrie.sirka_svg_mm,
                           vyska_svg_mm=geometrie.vyska_svg_mm, boxy=boxy)


# --- karta dílu, monitoring, laser ------------------------------------------------------------------


@cteni
def karta_dilu(spoj: Spojeni, dil_id: int) -> KartaDilu:
    """Karta dílu (kap. 15): kmenová data, STAT místo s min/max, všechna umístění a poslední pohyby.

    Tři cílené dotazy (kmenová data i s STAT místem, umístění, pohyby) – dřív devět přes rozhraní,
    z toho dva přes celý sklad.
    """
    dil = repozitar.dil(spoj, dil_id)
    if dil is None:
        raise AppError("NOT_FOUND", f"Díl {dil_id} neexistuje.")
    umisteni = _umisteni(spoj, [dil_id]).get(dil_id, [])
    stat_ks = sum(m["PocetKs"] for m in umisteni if m["TypBoxu"] == "STAT")
    dyn_ks = sum(m["PocetKs"] for m in umisteni if m["TypBoxu"] == "DYN")
    return KartaDilu(
        dil_id=dil["DilID"], identifikacni_cislo=dil["IdentifikacniCislo"], nazev=dil["NazevDilu"],
        material=dil["KodMaterialu"], tloustka_mm=dil["TloustkaMM"], prvni_operace=dil["KodPrvniOperace"],
        standardni_davka_ks=dil["StandardniDavkaKs"], velikost=dil["Velikost"], vault_url=dil["VaultVykresURL"],
        stat=_stat(spoj, dil_id), dyn_ks=dyn_ks, celkem_ks=dyn_ks + stat_ks, umisteni=_umisteni_radky(umisteni),
        posledni_pohyby=_historie(repozitar.pohyby_dilu(spoj, dil_id, POCET_POHYBU_NA_KARTE)))


@cteni
def zasoby(spoj: Spojeni, filtr: ZasobyFiltr) -> ZasobyVystup:
    """Centrální monitoring (13.1): díly se STAT místem, STAT a DYN zvlášť, stav podle STAT (kap. 13).

    jenSeStat=false přidá díly, které leží jen v DYN: bez minima a stavu, řazené na konec.
    Souhrn počítá díly se STAT místem po filtrech dílu a pracoviště – „jen problémové“ ho nemění.
    Řazení: nejhorší stav první, pak číslo dílu; vyhodnocuje se tady (PORADI_STAVU + `domena`).
    """
    radky = repozitar.zasoby(spoj, filtr)
    mista = _umisteni(spoj, [r["DilID"] for r in radky])
    vysledky = [_radek_zasoby(r, mista.get(r["DilID"], [])) for r in radky]
    pocty = domena.souhrn_zasob(r.stav_zasoby for r in vysledky if r.stav_zasoby)
    vybrane = sorted((r for r in vysledky if (not filtr.jen_problemove or r.stav_zasoby in domena.PROBLEMOVE)
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

    Chybí ve STAT = Maximum − STAT; doporučeno podle Q-22 (přepínač odecitatDyn), zaokrouhleno
    na standardní dávku – oboje `domena.doporuceni_laser`. Řazení: nejvíc chybí první.
    """
    radky = []
    for r in repozitar.laser(spoj, filtr):
        chybi, doporuceno = domena.doporuceni_laser(r["MaximalniPocetKs"], r["StatKs"], r["DynKs"],
                                                    r["StandardniDavkaKs"], odecitat_dyn=filtr.odecitat_dyn)
        if filtr.jen_pod_maximem and chybi == 0:
            continue
        radky.append(LaserRadek(dil_id=r["DilID"], identifikacni_cislo=r["IdentifikacniCislo"],
                                material=r["KodMaterialu"], tloustka_mm=r["TloustkaMM"],
                                prvni_operace=r["KodPrvniOperace"], stat_ks=r["StatKs"], dyn_ks=r["DynKs"],
                                maximalni_ks=r["MaximalniPocetKs"], chybi_ve_stat_ks=chybi,
                                doporuceno_ks=doporuceno, standardni_davka_ks=r["StandardniDavkaKs"]))
    radky.sort(key=lambda r: (-r.chybi_ve_stat_ks, r.identifikacni_cislo))
    zacatek = (filtr.strana - 1) * filtr.velikost
    return Strana[LaserRadek](polozky=radky[zacatek:zacatek + filtr.velikost], strana=filtr.strana,
                              velikost=filtr.velikost, celkem=len(radky))


# --- historie ---------------------------------------------------------------------------------------


@cteni
def pohyby(spoj: Spojeni, filtr: PohybyFiltr) -> Strana[PohybHistorie]:
    """Historie pohybů, nejnovější první; období od–do včetně (dny v časové zóně Europe/Prague)."""
    pozice_id = struktura.najdi_vnitrni_pozici(spoj, filtr.kod).vnitrni_pozice_id if filtr.kod else None
    radky, celkem = repozitar.stranka_pohybu(spoj, filtr, pozice_id)
    return Strana[PohybHistorie](polozky=_historie(radky), strana=filtr.strana, velikost=filtr.velikost,
                                 celkem=celkem)


@cteni
def transakce(spoj: Spojeni, transakce_id: uuid.UUID) -> TransakceDetail:
    """Skladová transakce s pohyby (např. PRESUN-OUT + PRESUN-IN se stejným TransakceID). Chyby: NOT_FOUND.

    Typ operace, čas a uživatel jsou z hlavičky (ne z prvního pohybu, jak bylo v kostře).
    """
    radky = repozitar.transakce(spoj, transakce_id)
    if not radky:
        raise AppError("NOT_FOUND", f"Transakce {transakce_id} neexistuje.")
    prvni = radky[0]
    return TransakceDetail(skladova_transakce_id=transakce_id, typ_operace=prvni["TransakceTypOperace"],
                           datum_cas=prvni["TransakceDatumCas"], uzivatel_id=prvni["TransakceUzivatelID"],
                           cele_jmeno=prvni["TransakceCeleJmeno"], terminal_id=prvni["TransakceTerminalID"],
                           pohyby=_historie([r for r in radky if r["PohybID"] is not None]))


@cteni
def ciselniky(spoj: Spojeni) -> CiselnikyVystup:
    """Všechny hodnoty pro filtry najednou (7.7): číselníky ostrovů C, D, E a pevné technické kódy."""
    c, d, e = struktura.nacti_ciselniky(spoj), dily.nacti_ciselniky(spoj), sklad.nacti_ciselniky(spoj)
    return CiselnikyVystup(pracoviste=_radky(c["pracoviste"]), velikosti=_radky(c["velikosti"]),
                           materialy=_radky(d["materialy"]), tloustky=_radky(d["tloustky"]),
                           operace=_radky(d["operace"]), typy_pohybu=_radky(e["typyPohybu"]),
                           typy_boxu=["DYN", "STAT"], stavy_zasoby=list(domena.STAVY_ZASOBY))


# --- pomocné ----------------------------------------------------------------------------------------


def _zvyrazneni(misto: dict[str, Any]) -> Zvyrazneni:
    return Zvyrazneni(regal_id=misto["RegalID"], uroven_id=misto["UrovenID"], box_id=misto["BoxID"],
                      vnitrni_pozice_id=misto["VnitrniPoziceID"])


def _objekt(spoj: Spojeni, kod: str) -> VysledekHledani:
    """Naskenovaný kód skladu: objekt z ostrova C, obsah pozice jedním dotazem (12.2)."""
    objekt = struktura.najdi_objekt(spoj, kod)
    obsah = _obsah_pozic(spoj, [objekt.vnitrni_pozice_id]).get(objekt.vnitrni_pozice_id) \
        if objekt.vnitrni_pozice_id is not None else None
    ident = {"REGAL": objekt.regal_id, "BOX": objekt.box_id, "POZICE": objekt.vnitrni_pozice_id}[objekt.typ]
    popis = (f"{obsah['IdentifikacniCislo']} · {obsah['PocetKs']} ks" if obsah
             else "prázdná" if objekt.typ == "POZICE" else None)
    return VysledekHledani(
        typ=objekt.typ, id=ident or 0, kod=objekt.kod, popis=popis,
        adresa=objekt.adresa,
        zvyrazneni=Zvyrazneni(regal_id=objekt.regal_id, uroven_id=objekt.uroven_id, box_id=objekt.box_id,
                              vnitrni_pozice_id=objekt.vnitrni_pozice_id),
        obsah=ObsahNaPozici(dil_id=obsah["DilID"], identifikacni_cislo=obsah["IdentifikacniCislo"],
                            pocet_ks=obsah["PocetKs"]) if obsah else None)


def _obsah_pozic(spoj: Spojeni, vnitrni_pozice_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Obsah pozic podle ID; prázdné pozice ve výsledku chybí."""
    return {radek["VnitrniPoziceID"]: radek for radek in repozitar.obsah_pozic(spoj, vnitrni_pozice_ids)}


def _umisteni(spoj: Spojeni, dil_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    """Místa s obsahem po dílech, STAT první, pak DYN podle čísla boxu (domena.poradi_umisteni).

    Jeden hromadný dotaz pro celý přehled – dřív se projížděl celý sklad pro každý díl zvlášť.
    """
    mista: dict[int, list[dict[str, Any]]] = {}
    for radek in repozitar.umisteni_dilu(spoj, list(dict.fromkeys(dil_ids))):
        mista.setdefault(radek["DilID"], []).append(radek)
    for radky in mista.values():
        radky.sort(key=lambda m: domena.poradi_umisteni(m["TypBoxu"], m["KodBoxu"], m["PoradiVBoxu"]))
    return mista


def _umisteni_radky(mista: list[dict[str, Any]]) -> list[UmisteniDilu]:
    return [UmisteniDilu(vnitrni_pozice_id=m["VnitrniPoziceID"], kod=m["KodMista"], adresa=m["Adresa"],
                         typ_boxu=m["TypBoxu"], pocet_ks=m["PocetKs"], zvyrazneni=_zvyrazneni(m)) for m in mista]


def _vysledky_dilu(spoj: Spojeni, nalezene: list[tuple[int, str, str | None]]) -> list[VysledekHledani]:
    """(DilID, číslo, název) na výsledky hledání: adresa a zvýraznění prvního umístění."""
    mista = _umisteni(spoj, [dil_id for dil_id, _, _ in nalezene])
    vysledky = []
    for dil_id, kod, popis in nalezene:
        mista_dilu = mista.get(dil_id) or []
        prvni = mista_dilu[0] if mista_dilu else None
        vysledky.append(VysledekHledani(typ="DIL", id=dil_id, kod=kod, popis=popis,
                                        adresa=prvni["Adresa"] if prvni else None,
                                        zvyrazneni=_zvyrazneni(prvni) if prvni else None, obsah=None))
    return vysledky


def _pozice_svg(kod_boxu: str, pozice: struktura.PoziceVRozlozeni,
                obsah: dict[int, dict[str, Any]]) -> PoziceSvg:
    """Pozice v SVG: geometrie z ostrova C a díl, který v ní leží (prázdná pozice jen s geometrií)."""
    d = obsah.get(pozice.vnitrni_pozice_id)
    return PoziceSvg(vnitrni_pozice_id=pozice.vnitrni_pozice_id, kod_pozice=pozice.kod_pozice,
                     kod=f"{kod_boxu}-{pozice.kod_pozice}", velikost=pozice.velikost, blokovana=pozice.blokovano,
                     rel_x=pozice.rel_x, rel_y=pozice.rel_y, rel_sirka=pozice.rel_sirka,
                     rel_hloubka=pozice.rel_hloubka, dil_id=d["DilID"] if d else None,
                     identifikacni_cislo=d["IdentifikacniCislo"] if d else None, pocet_ks=d["PocetKs"] if d else 0,
                     vault_url=d["VaultVykresURL"] if d else None)


def _stat(spoj: Spojeni, dil_id: int) -> StatZasoba | None:
    """STAT místo dílu ze v_ZasobaDilu; stav zásoby počítá pohled (ostrov E), ne G."""
    radek = repozitar.stat_zasoba(spoj, dil_id)
    if radek is None:
        return None
    maximum, stav_ks = radek["MaximalniPocetKs"], radek["StatKs"]
    return StatZasoba(stat_umisteni_id=radek["StatickeUmisteniID"], kod=radek["StatKod"] or "?",
                      minimalni_ks=radek["MinimalniPocetKs"], optimalni_ks=radek["OptimalniPocetKs"],
                      maximalni_ks=maximum, stav_ks=stav_ks, stav_zasoby=radek["StavZasoby"],
                      kod_boxu=radek["StatKodBoxu"] or "?",
                      chybi_do_maxima_ks=max(0, maximum - stav_ks) if maximum is not None else None)


def _radek_zasoby(radek: dict[str, Any], mista: list[dict[str, Any]]) -> ZasobaRadek:
    """Řádek monitoringu (13.1); díl jen v DYN (druhá větev dotazu) nemá minimum ani stav."""
    stat_ks, dyn_ks = radek["StatKs"], radek["DynKs"]
    return ZasobaRadek(
        dil_id=radek["DilID"], identifikacni_cislo=radek["IdentifikacniCislo"], nazev=radek["NazevDilu"],
        material=radek["KodMaterialu"], tloustka_mm=radek["TloustkaMM"], prvni_operace=radek["KodPrvniOperace"],
        stat_ks=stat_ks, dyn_ks=dyn_ks, celkem_ks=stat_ks + dyn_ks,
        minimalni_ks=radek["MinimalniPocetKs"], maximalni_ks=radek["MaximalniPocetKs"],
        stav_zasoby=radek["StavZasoby"],
        umisteni=domena.text_umisteni(radek["StatickeUmisteniID"] is not None,
                                      sum(1 for m in mista if m["TypBoxu"] == "DYN")),
        zvyrazneni=_zvyrazneni_z_asoby(radek, mista), mista=_umisteni_radky(mista))


def _zvyrazneni_z_asoby(radek: dict[str, Any], mista: list[dict[str, Any]]) -> Zvyrazneni:
    """Zvýrazní STAT místo dílu; pokud v něm nic neleží (nebo STAT nemá), zvýrazní se první umístění."""
    if radek["StatRegalID"] is None:
        return _zvyrazneni(mista[0])
    return Zvyrazneni(regal_id=radek["StatRegalID"], uroven_id=radek["StatUrovenID"],
                      box_id=radek["StatBoxID"], vnitrni_pozice_id=radek["StatVnitrniPoziceID"])


def _historie(radky: list[dict[str, Any]]) -> list[PohybHistorie]:
    """Řádky v_PohybDetail na/history: čísla dílů, kódy pozic a jména uživatele už jsou v dotazu."""
    return [PohybHistorie(pohyb_id=p["PohybID"], datum_cas=p["DatumCas"], typ_pohybu=p["TypPohybu"],
                          dil_id=p["DilID"], identifikacni_cislo=p["IdentifikacniCislo"],
                          vnitrni_pozice_id=p["VnitrniPoziceID"], kod=p["KodMista"], mnozstvi=p["Mnozstvi"],
                          stav_pred_ks=p["StavPred"], stav_po_ks=p["StavPo"], uzivatel_id=p["UzivatelID"],
                          cele_jmeno=p["CeleJmeno"], terminal_id=p["TerminalID"],
                          skladova_transakce_id=_uuid(p["TransakceID"]), poznamka=p["Poznamka"])
            for p in radky]


def _uuid(hodnota: Any) -> uuid.UUID | None:
    """Uniqueidentifier z pyodbc → UUID; TransakceID pohybu je voluntářní (pohyb bez transakce)."""
    return uuid.UUID(str(hodnota)) if hodnota is not None else None


def _radky(polozky: tuple[PolozkaCiselniku, ...]) -> list[CiselnikRadek]:
    return [CiselnikRadek(id=p.id, kod=p.kod, nazev=p.nazev, aktivni=p.aktivni) for p in polozky]
