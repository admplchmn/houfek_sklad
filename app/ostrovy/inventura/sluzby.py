"""Služby ostrova F – Inventura. Jedna operace = @transakce, čtení = @cteni.

Fáze 0: kontrakt a čistá pravidla (domena) jsou hotové, inventury jsou vzorové (KOSTRA) a nic se
neukládá; dokončení vrátí souhrn a čísla pohybů, ale korekce nezaúčtuje (sklad.zauctuj_korekci je fáze 1).
Ve fázi 1 vlastník nahradí řádky `from . import ukazky` voláním repozitar.*; podpisy se nemění.

Dokončení ve fázi 1 (jedna transakce): struktura.zamkni_mista(všechny pozice inventury + cíle)
→ znovu stav položek (posledni_pohyby) → domena.over_dokonceni → domena.planuj_korekce →
sklad.zauctuj_korekci pro každou korekci (typ INVENTURA) → Inventura DOKONCENA.
"""
from __future__ import annotations

from app.ostrovy.dily import rozhrani as dily
from app.ostrovy.sklad import rozhrani as sklad
from app.ostrovy.struktura import rozhrani as struktura
from app.platforma.chyby import AppError, chyba_vstupu
from app.platforma.db import Spojeni, cteni
from app.platforma.kontrakty import DuvodVstup, Strana, teď
from app.platforma.transakce import transakce
from app.platforma.typy import Kontext

from . import domena
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

NOVE_ID = 9001        # KOSTRA: ID nové inventury ve vzorové odpovědi
NOVY_POHYB = 70001    # KOSTRA: PohybID prvního korekčního pohybu

# --- čtení ------------------------------------------------------------------------------------


@cteni
def seznam_inventur(spoj: Spojeni, filtr: InventuryFiltr) -> Strana[InventuraRadek]:
    """Inventury, nejnovější první. Výchozí filtr = rozpracované."""
    from . import ukazky  # KOSTRA (fáze 0)

    vybrane = sorted((i for i in ukazky.INVENTURY.values() if filtr.stav in (None, i.stav_inventury)),
                     key=lambda i: (i.datum_zahajeni, i.inventura_id), reverse=True)
    radky = [_radek(spoj, i) for i in vybrane]
    return Strana[InventuraRadek](polozky=radky, strana=filtr.strana, velikost=filtr.velikost, celkem=len(radky))


@cteni
def detail_inventury(spoj: Spojeni, inventura_id: int) -> InventuraDetail:
    """Inventura s položkami; slepá inventura u nezapsaných položek očekávaný stav nevrací."""
    inventura = _nacti(inventura_id)
    polozky = _polozky(spoj, inventura)
    return InventuraDetail(**_radek(spoj, inventura, polozky).model_dump(exclude={"transakce_id", "varovani"}),
                           polozky=[_vystup_polozky(inventura.slepa, p, v) for p, v in zip(
                               polozky, inventura.polozky, strict=True)])


# --- příkazy ----------------------------------------------------------------------------------------


@transakce("INVENTURA_ZALOZENI")
def zaloz_inventuru(spoj: Spojeni, vstup: NovaInventuraVstup, kdo: Kontext) -> InventuraDetail:
    """Položky pro všechny aktivní pozice v rozsahu, i prázdné, se snímkem očekávaného dílu a počtu (5.11).

    Pozice smí být nejvýš v jedné rozpracované inventuře (jinak by se rozdíl zaúčtoval dvakrát).
    Fáze 1: kontrola překryvu až po struktura.zamkni_mista(ids) – dvě souběžná založení se stejnými
    pozicemi se tak seřadí za sebe a druhé překryv uvidí.
    Chyby: VALIDATION_ERROR (rozsah), NOT_FOUND (cíl), ALREADY_EXISTS (pozice v jiné rozpracované inventuře).
    """
    from . import ukazky  # KOSTRA (fáze 0)

    domena.over_rozsah(vstup.typ_rozsahu, vstup.cil_id)
    ids = struktura.pozice_v_rozsahu(spoj, vstup.typ_rozsahu, vstup.cil_id)
    for jina in ukazky.INVENTURY.values():
        spolecne = {p.kod for p in jina.polozky if p.vnitrni_pozice_id in ids}
        if jina.stav_inventury == "ROZPRACOVANA" and spolecne:
            raise AppError("ALREADY_EXISTS", f"Pozice {', '.join(sorted(spolecne))} už jsou v rozpracované "
                                             f"inventuře {jina.inventura_id}. Dokončete ji nebo zrušte.")
    mista = struktura.nacti_mista(spoj, ids)
    obsah = sklad.obsah_mist(spoj, ids)
    nova = ukazky.VzorInventury(
        NOVE_ID, vstup.typ_rozsahu, vstup.cil_id, "ROZPRACOVANA", vstup.slepa, teď(), None,
        kdo.uzivatel_id, tuple(
            ukazky.VzorPolozky(i, mista[i].kod, mista[i].typ_boxu, obsah[i].dil_id if i in obsah else None,
                               obsah[i].pocet_ks if i in obsah else 0)
            for i in ids if i in mista), vstup.poznamka)
    polozky = _polozky(spoj, nova)
    return InventuraDetail(**_radek(spoj, nova, polozky).model_dump(exclude={"transakce_id", "varovani"}),
                           polozky=[_vystup_polozky(nova.slepa, p, v) for p, v in zip(polozky, nova.polozky,
                                                                                         strict=True)])


@transakce("INVENTURA_ZAPIS")
def zapis_polozku(spoj: Spojeni, inventura_id: int, vnitrni_pozice_id: int, vstup: ZapisPolozkyVstup,
                  kdo: Kontext) -> PolozkaInventury:
    """Zápis nalezeného stavu (i opakovaný = přepočet). Očekávaný stav se obnoví z aktuálního obsahu,
    takže pohyby mezi založením a počítáním se započtou; položka si zapamatuje poslední pohyb (Q-16).

    Chyby: NOT_FOUND (inventura, pozice v ní, díl), CONCURRENT_CHANGE (inventura už není rozpracovaná),
    VALIDATION_ERROR (prázdné s počtem, díl bez počtu).
    """
    from . import ukazky  # KOSTRA (fáze 0)

    inventura = _rozpracovana(inventura_id)
    vzor = next((p for p in inventura.polozky if p.vnitrni_pozice_id == vnitrni_pozice_id), None)
    if vzor is None:
        raise AppError("NOT_FOUND", f"Pozice {vnitrni_pozice_id} v inventuře {inventura_id} není.")
    domena.over_zapis(vstup.skutecny_dil_id, vstup.skutecny_pocet_ks)
    dil_id = vstup.skutecny_dil_id
    if dil_id is not None and dil_id not in dily.nacti_dily(spoj, [dil_id]):
        raise AppError("NOT_FOUND", f"Díl {dil_id} neexistuje.")
    obsah = sklad.obsah_mist(spoj, [vnitrni_pozice_id]).get(vnitrni_pozice_id)
    zapsano = ukazky.VzorPolozky(
        vnitrni_pozice_id, vzor.kod, vzor.typ_boxu, obsah.dil_id if obsah else None, obsah.pocet_ks if obsah else 0,
        vstup.skutecny_dil_id, vstup.skutecny_pocet_ks,
        sklad.posledni_pohyby(spoj, [vnitrni_pozice_id]).get(vnitrni_pozice_id), teď())
    return _vystup_polozky(inventura.slepa, _polozky(spoj, inventura, [zapsano])[0], zapsano)


@transakce("INVENTURA_ZRUSENI")
def zrus_inventuru(spoj: Spojeni, inventura_id: int, vstup: DuvodVstup, kdo: Kontext) -> InventuraRadek:
    """Zrušení: žádné pohyby, stav ZRUSENA (5.11). Chyby: NOT_FOUND, CONCURRENT_CHANGE."""
    inventura = _rozpracovana(inventura_id)
    return _radek(spoj, inventura).model_copy(update={"stav_inventury": "ZRUSENA", "poznamka": vstup.duvod})


@transakce("INVENTURA_DOKONCENI", skladova=True)
def dokonci_inventuru(spoj: Spojeni, inventura_id: int, vstup: DokonceniVstup, kdo: Kontext) -> DokonceniVysledek:
    """Zaúčtuje všechny rozdíly v jedné transakci pohyby INVENTURA a uzavře inventuru (21.1.7).

    Chyby: NOT_FOUND, CONCURRENT_CHANGE (není rozpracovaná), VALIDATION_ERROR (nezapsané pozice,
    chybějící nebo nevhodný cíl JINY_DIL), INVENTORY_RECOUNT (pohyb od zápisu, Q-16).
    """
    inventura = _rozpracovana(inventura_id)
    polozky = _polozky(spoj, inventura)
    domena.over_dokonceni(polozky, vstup.cile_jiny_dil)
    cile = _cile_jiny_dil(spoj, polozky, vstup.cile_jiny_dil)
    korekce = domena.planuj_korekce(polozky, cile)
    pocty = domena.souhrn(polozky)
    return DokonceniVysledek(inventura_id=inventura.inventura_id, pocet_shod=pocty["SHODA"],
                             pocet_rozdilu=pocty["ROZDIL"], pocet_jinych_dilu=pocty["JINY_DIL"],
                             pohyby=[NOVY_POHYB + i for i in range(len(korekce))])


# --- pomocné -------------------------------------------------------------------------------------


def _nacti(inventura_id: int):
    from . import ukazky  # KOSTRA (fáze 0)

    inventura = ukazky.INVENTURY.get(inventura_id)
    if inventura is None:
        raise AppError("NOT_FOUND", f"Inventura {inventura_id} neexistuje.")
    return inventura


def _rozpracovana(inventura_id: int):
    inventura = _nacti(inventura_id)
    if inventura.stav_inventury != "ROZPRACOVANA":
        stav = "dokončená" if inventura.stav_inventury == "DOKONCENA" else "zrušená"
        raise AppError("CONCURRENT_CHANGE", f"Inventura {inventura_id} už je {stav}.")
    return inventura


def _polozky(spoj: Spojeni, inventura, vzory=None) -> list[domena.Polozka]:
    """Položky pro pravidla se stavem CEKA / ZAPSANO / PREPOCITAT podle posledního pohybu na pozici."""
    vzory = list(vzory if vzory is not None else inventura.polozky)
    posledni = sklad.posledni_pohyby(spoj, [v.vnitrni_pozice_id for v in vzory])
    return [domena.Polozka(v.vnitrni_pozice_id, v.kod, v.typ_boxu, v.ocekavany_dil_id, v.ocekavany_pocet_ks,
                           v.skutecny_dil_id, v.skutecny_pocet_ks,
                           domena.stav_polozky(v.skutecny_pocet_ks is not None, v.pohyb_pri_zapisu,
                                               posledni.get(v.vnitrni_pozice_id)))
            for v in vzory]


def _radek(spoj: Spojeni, inventura, polozky: list[domena.Polozka] | None = None) -> InventuraRadek:
    polozky = polozky if polozky is not None else _polozky(spoj, inventura)
    return InventuraRadek(
        inventura_id=inventura.inventura_id, typ_rozsahu=inventura.typ_rozsahu, cil_id=inventura.cil_id,
        stav_inventury=inventura.stav_inventury, slepa=inventura.slepa, datum_zahajeni=inventura.datum_zahajeni,
        datum_dokonceni=inventura.datum_dokonceni, zalozil_uzivatel_id=inventura.zalozil_uzivatel_id,
        pocet_polozek=len(polozky), pocet_zapsanych=sum(1 for p in polozky if p.stav != "CEKA"),
        pocet_k_prepoctu=sum(1 for p in polozky if p.stav == "PREPOCITAT"), poznamka=inventura.poznamka)


def _vystup_polozky(slepa: bool, p: domena.Polozka, vzor) -> PolozkaInventury:
    zapsano = p.skutecny_pocet_ks is not None
    skryt = slepa and not zapsano
    vysledek, rozdil = (domena.vyhodnot(p.ocekavany_dil_id, p.ocekavany_pocet_ks, p.skutecny_dil_id,
                                        p.skutecny_pocet_ks) if zapsano else (None, None))
    return PolozkaInventury(
        vnitrni_pozice_id=p.vnitrni_pozice_id, kod=p.kod, typ_boxu=p.typ_boxu, stav_polozky=p.stav,
        ocekavany_dil_id=None if skryt else p.ocekavany_dil_id,
        ocekavany_pocet_ks=None if skryt else p.ocekavany_pocet_ks,
        skutecny_dil_id=p.skutecny_dil_id, skutecny_pocet_ks=p.skutecny_pocet_ks, rozdil_ks=rozdil,
        vyhodnoceni=vysledek, datum_kontroly=vzor.datum_kontroly)


def _cile_jiny_dil(spoj: Spojeni, polozky: list[domena.Polozka], zadane: dict[int, str]) -> dict[int, int]:
    """Cíl pro jiný díl nalezený na STAT pozici (Q-17): prázdná DYN pozice, do které se díl vejde,
    nebo STAT místo právě nalezeného dílu. Vrací {VnitrniPoziceID položky: VnitrniPoziceID cíle}."""
    podle_pozice = {p.vnitrni_pozice_id: p for p in polozky}
    cile: dict[int, int] = {}
    for pozice_id, kod in zadane.items():
        polozka = podle_pozice.get(pozice_id)
        if polozka is None or polozka.typ_boxu != "STAT" or polozka.skutecny_dil_id in (None, polozka.ocekavany_dil_id):
            raise chyba_vstupu(f"Pozice {pozice_id} není STAT pozice s nalezeným jiným dílem.",
                               {"cileJinyDil": "Cíl se zadává jen pro JINY_DIL ve STAT pozici."})
        cil = struktura.najdi_vnitrni_pozici(spoj, kod)
        dil = dily.nacti_dily(spoj, [polozka.skutecny_dil_id]).get(polozka.skutecny_dil_id)
        if cil.typ_boxu == "DYN":
            vhodny = (not sklad.obsah_mist(spoj, [cil.vnitrni_pozice_id]) and dil is not None
                      and dil.potreba is not None and struktura.vejde_se(cil, dil.potreba))
        else:
            vhodny = any(s.dil_id == polozka.skutecny_dil_id
                         for s in sklad.stat_mista(spoj, vnitrni_pozice_ids=[cil.vnitrni_pozice_id]))
        if not vhodny:
            raise chyba_vstupu(f"{cil.kod} není vhodný cíl pro nalezený díl z {polozka.kod}.",
                               {"cileJinyDil": "Prázdná DYN pozice stejné velikosti nebo STAT místo dílu."})
        cile[pozice_id] = cil.vnitrni_pozice_id
    return cile
