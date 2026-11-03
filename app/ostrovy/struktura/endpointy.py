"""HTTP endpointy ostrova C – Struktura skladu a kódy (/api/struktura). Kontrakt: sekce 7.3 dokumentu Ostrovy.

Cesty pod /api/struktura:
    GET /pracoviste, GET /regaly?pracovisteId=, GET /urovne?regalId=, GET /urovne/{id}/boxy,
    GET /boxy/{id}, GET /vnitrni-pozice/{id}, GET /cleneni                                    (DIL_CIST)
    POST /blokace                                                         (BLOKACE, requestId)
    POST /pracoviste|/regaly|/urovne, PATCH …/{id}, POST …/{id}/deaktivovat                  (BOX_EDIT)
    POST /urovne/{id}/boxy, POST /boxy/{id}/vymena|presun|poradi|rekonfigurace|deaktivovat,
    POST /vnitrni-pozice/{id}/rozmer-c7                                                      (BOX_EDIT)
Štítky (GET /stitky, PDF) přijdou po rozhodnutí o vzhledu štítku (Q-19) – kódy už generuje domena.
Endpoint dělá jen: vstup → služba → obálka.
"""
from flask import Blueprint

from app.platforma.auth import kontext, vyzaduje
from app.platforma.http import dokumentuj, nacti_parametry, nacti_vstup, odpoved
from app.platforma.kontrakty import DuvodVstup, Seznam

from . import sluzby
from .kontrakty import (
    BlokaceVstup,
    BlokaceVysledek,
    BoxDetail,
    BoxNaUrovni,
    CleneniRadek,
    NovaUrovenVstup,
    NovePracovisteVstup,
    NovyBoxVstup,
    NovyRegalVstup,
    PoradiBoxuVstup,
    PracovisteFiltr,
    PracovisteRadek,
    PresunBoxuVstup,
    RegalRadek,
    RegalyFiltr,
    RekonfiguraceVstup,
    RozmerC7Vstup,
    UrovenRadek,
    UrovneFiltr,
    VnitrniPoziceDetail,
    VymenaBoxuVstup,
    ZmenaPracovisteVstup,
    ZmenaRegaluVstup,
    ZmenaUrovneVstup,
)

api = Blueprint("struktura_api", __name__)

# --- čtení (DIL_CIST) ----------------------------------------------------------------------------


@api.get("/pracoviste")
@vyzaduje("DIL_CIST")
@dokumentuj(parametry=PracovisteFiltr, vystup=Seznam[PracovisteRadek], popis="Pracoviště (PLE, 1SV …).")
def pracoviste():
    return odpoved(sluzby.seznam_pracovist(nacti_parametry(PracovisteFiltr)), "Načteno.")


@api.get("/regaly")
@vyzaduje("DIL_CIST")
@dokumentuj(parametry=RegalyFiltr, vystup=Seznam[RegalRadek], popis="Regály, volitelně jednoho pracoviště.")
def regaly():
    return odpoved(sluzby.seznam_regalu(nacti_parametry(RegalyFiltr)), "Načteno.")


@api.get("/urovne")
@vyzaduje("DIL_CIST")
@dokumentuj(parametry=UrovneFiltr, vystup=Seznam[UrovenRadek], popis="Úrovně regálu shora dolů.")
def urovne():
    return odpoved(sluzby.seznam_urovni(nacti_parametry(UrovneFiltr)), "Načteno.")


@api.get("/urovne/<int:uroven_id>/boxy")
@vyzaduje("DIL_CIST")
@dokumentuj(vystup=Seznam[BoxNaUrovni], popis="Boxy úrovně zleva doprava (Pozice P01…Pn). SVG vrací Přehledy.")
def boxy_urovne(uroven_id: int):
    return odpoved(sluzby.boxy_urovne(uroven_id), "Načteno.")


@api.get("/boxy/<int:box_id>")
@vyzaduje("DIL_CIST")
@dokumentuj(vystup=BoxDetail, popis="Struktura boxu a jeho vnitřní pozice, bez obsahu.")
def box(box_id: int):
    return odpoved(sluzby.detail_boxu(box_id), "Načteno.")


@api.get("/vnitrni-pozice/<int:vnitrni_pozice_id>")
@vyzaduje("DIL_CIST")
@dokumentuj(vystup=VnitrniPoziceDetail, popis="Vnitřní pozice s boxem, adresou a skutečným stavem blokace.")
def vnitrni_pozice(vnitrni_pozice_id: int):
    return odpoved(sluzby.detail_vnitrni_pozice(vnitrni_pozice_id), "Načteno.")


@api.get("/cleneni")
@vyzaduje("DIL_CIST")
@dokumentuj(vystup=Seznam[CleneniRadek], popis="Konfigurace C1–C7 se šablonou přihrádek (Q-06).")
def cleneni():
    return odpoved(sluzby.seznam_cleneni(), "Načteno.")


# --- blokace (BLOKACE) -----------------------------------------------------------------------------


@api.post("/blokace")
@vyzaduje("BLOKACE")
@dokumentuj(vstup=BlokaceVstup, vystup=BlokaceVysledek,
            popis="Zablokuje nebo odblokuje box či pozici podle naskenovaného kódu. Skladový příkaz s requestId.")
def blokace():
    vysledek = sluzby.blokuj(vstup=nacti_vstup(BlokaceVstup), kdo=kontext())
    stav = "zablokováno" if vysledek.blokovano else "odblokováno"
    return odpoved(vysledek, f"{vysledek.kod} {stav}." if vysledek.zmeneno else "Beze změny.")


# --- pracoviště, regály, úrovně (BOX_EDIT) -----------------------------------------------------------


@api.post("/pracoviste")
@vyzaduje("BOX_EDIT")
@dokumentuj(vstup=NovePracovisteVstup, vystup=PracovisteRadek, popis="Založí pracoviště; kód má 3 znaky.")
def zaloz_pracoviste():
    radek = sluzby.zaloz_pracoviste(vstup=nacti_vstup(NovePracovisteVstup), kdo=kontext())
    return odpoved(radek, f"Pracoviště {radek.kod_pracoviste} založeno.")


@api.patch("/pracoviste/<int:pracoviste_id>")
@vyzaduje("BOX_EDIT")
@dokumentuj(vstup=ZmenaPracovisteVstup, vystup=PracovisteRadek, popis="Změní název pracoviště (kód je v barcode).")
def zmen_pracoviste(pracoviste_id: int):
    return odpoved(sluzby.zmen_pracoviste(pracoviste_id=pracoviste_id, vstup=nacti_vstup(ZmenaPracovisteVstup),
                                          kdo=kontext()), "Uloženo.")


@api.post("/pracoviste/<int:pracoviste_id>/deaktivovat")
@vyzaduje("BOX_EDIT")
@dokumentuj(vstup=DuvodVstup, vystup=PracovisteRadek, popis="Vyřadí pracoviště bez aktivních regálů.")
def deaktivuj_pracoviste(pracoviste_id: int):
    return odpoved(sluzby.deaktivuj_pracoviste(pracoviste_id=pracoviste_id, vstup=nacti_vstup(DuvodVstup),
                                               kdo=kontext()), "Pracoviště vyřazeno.")


@api.post("/regaly")
@vyzaduje("BOX_EDIT")
@dokumentuj(vstup=NovyRegalVstup, vystup=RegalRadek, popis="Založí regál na pracovišti (R01–R99).")
def zaloz_regal():
    radek = sluzby.zaloz_regal(vstup=nacti_vstup(NovyRegalVstup), kdo=kontext())
    return odpoved(radek, f"Regál {radek.kod} založen.")


@api.patch("/regaly/<int:regal_id>")
@vyzaduje("BOX_EDIT")
@dokumentuj(vstup=ZmenaRegaluVstup, vystup=RegalRadek, popis="Změní název regálu (kód je v barcode).")
def zmen_regal(regal_id: int):
    return odpoved(sluzby.zmen_regal(regal_id=regal_id, vstup=nacti_vstup(ZmenaRegaluVstup), kdo=kontext()),
                   "Uloženo.")


@api.post("/regaly/<int:regal_id>/deaktivovat")
@vyzaduje("BOX_EDIT")
@dokumentuj(vstup=DuvodVstup, vystup=RegalRadek, popis="Vyřadí regál bez aktivních úrovní.")
def deaktivuj_regal(regal_id: int):
    return odpoved(sluzby.deaktivuj_regal(regal_id=regal_id, vstup=nacti_vstup(DuvodVstup), kdo=kontext()),
                   "Regál vyřazen.")


@api.post("/urovne")
@vyzaduje("BOX_EDIT")
@dokumentuj(vstup=NovaUrovenVstup, vystup=UrovenRadek, popis="Založí úroveň regálu (U00–U99).")
def zaloz_uroven():
    radek = sluzby.zaloz_uroven(vstup=nacti_vstup(NovaUrovenVstup), kdo=kontext())
    return odpoved(radek, f"Úroveň {radek.kod_urovne} založena.")


@api.patch("/urovne/<int:uroven_id>")
@vyzaduje("BOX_EDIT")
@dokumentuj(vstup=ZmenaUrovneVstup, vystup=UrovenRadek, popis="Změní pořadí nebo informační rozměr plochy úrovně.")
def zmen_uroven(uroven_id: int):
    return odpoved(sluzby.zmen_uroven(uroven_id=uroven_id, vstup=nacti_vstup(ZmenaUrovneVstup), kdo=kontext()),
                   "Uloženo.")


@api.post("/urovne/<int:uroven_id>/deaktivovat")
@vyzaduje("BOX_EDIT")
@dokumentuj(vstup=DuvodVstup, vystup=UrovenRadek, popis="Vyřadí úroveň bez aktivních boxů.")
def deaktivuj_uroven(uroven_id: int):
    return odpoved(sluzby.deaktivuj_uroven(uroven_id=uroven_id, vstup=nacti_vstup(DuvodVstup), kdo=kontext()),
                   "Úroveň vyřazena.")


# --- operace s boxem (BOX_EDIT) ------------------------------------------------------------------


@api.post("/urovne/<int:uroven_id>/boxy")
@vyzaduje("BOX_EDIT")
@dokumentuj(vstup=NovyBoxVstup, vystup=BoxDetail,
            popis="Přidá box na úroveň (na konec nebo na pořadí); kód boxu z řady pracoviště nebo BSTAT.")
def zaloz_box(uroven_id: int):
    novy = sluzby.zaloz_box(uroven_id=uroven_id, vstup=nacti_vstup(NovyBoxVstup), kdo=kontext())
    return odpoved(novy, f"Box {novy.kod_boxu} založen na pozici {novy.kod_pozice_urovne}.")


@api.post("/boxy/<int:box_id>/vymena")
@vyzaduje("BOX_EDIT")
@dokumentuj(vstup=VymenaBoxuVstup, vystup=BoxDetail, popis="Vymění prázdný box za nový na stejné Pozici.")
def vymen_box(box_id: int):
    novy = sluzby.vymen_box(box_id=box_id, vstup=nacti_vstup(VymenaBoxuVstup), kdo=kontext())
    return odpoved(novy, f"Box vyměněn, nový box {novy.kod_boxu}.")


@api.post("/boxy/<int:box_id>/presun")
@vyzaduje("BOX_EDIT")
@dokumentuj(vstup=PresunBoxuVstup, vystup=BoxDetail,
            popis="Přesune box i s obsahem na jinou úroveň; DYN jen v rámci svého pracoviště (Q-30).")
def presun_box(box_id: int):
    box_po = sluzby.presun_box(box_id=box_id, vstup=nacti_vstup(PresunBoxuVstup), kdo=kontext())
    return odpoved(box_po, f"Box {box_po.kod_boxu} přesunut na {box_po.full_box_klic}.")


@api.post("/boxy/<int:box_id>/poradi")
@vyzaduje("BOX_EDIT")
@dokumentuj(vstup=PoradiBoxuVstup, vystup=Seznam[BoxNaUrovni], popis="Změní pořadí boxu na jeho úrovni.")
def poradi_boxu(box_id: int):
    return odpoved(sluzby.zmen_poradi_boxu(box_id=box_id, vstup=nacti_vstup(PoradiBoxuVstup), kdo=kontext()),
                   "Pořadí změněno.")


@api.post("/boxy/<int:box_id>/rekonfigurace")
@vyzaduje("BOX_EDIT")
@dokumentuj(vstup=RekonfiguraceVstup, vystup=BoxDetail,
            popis="Nové členění prázdného boxu bez STAT přiřazení; štítky pozic se tisknou znovu (Q-27).")
def rekonfiguruj_box(box_id: int):
    box_po = sluzby.rekonfiguruj_box(box_id=box_id, vstup=nacti_vstup(RekonfiguraceVstup), kdo=kontext())
    return odpoved(box_po, f"Box {box_po.kod_boxu} má členění {box_po.kod_cleneni}.")


@api.post("/boxy/<int:box_id>/deaktivovat")
@vyzaduje("BOX_EDIT")
@dokumentuj(vstup=DuvodVstup, vystup=BoxDetail, popis="Vyřadí prázdný box; boxy vpravo se posunou.")
def deaktivuj_box(box_id: int):
    box_po = sluzby.deaktivuj_box(box_id=box_id, vstup=nacti_vstup(DuvodVstup), kdo=kontext())
    return odpoved(box_po, f"Box {box_po.kod_boxu} vyřazen.")


@api.post("/vnitrni-pozice/<int:vnitrni_pozice_id>/rozmer-c7")
@vyzaduje("BOX_EDIT")
@dokumentuj(vstup=RozmerC7Vstup, vystup=VnitrniPoziceDetail, popis="Nastaví rozměr variabilní pozice C7 (Q-01).")
def rozmer_c7(vnitrni_pozice_id: int):
    pozice = sluzby.nastav_rozmer_c7(vnitrni_pozice_id=vnitrni_pozice_id, vstup=nacti_vstup(RozmerC7Vstup),
                                     kdo=kontext())
    return odpoved(pozice, f"Rozměr pozice {pozice.kod} uložen.")
