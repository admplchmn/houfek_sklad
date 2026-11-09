"""HTTP endpointy ostrova B – Identita (/api/identita). Kontrakt: sekce 7.2 dokumentu Ostrovy.

Cesty pod /api/identita:
    POST /prihlaseni, POST /odhlaseni                                        (veřejné)
    GET /ja                                                                  (přihlášený)
    GET|POST /uzivatele, PATCH /uzivatele/{id},
    POST /uzivatele/{id}/deaktivovat, POST /uzivatele/{id}/reset-pinu        (UZIVATEL_EDIT)
    POST /uzivatele/{id}/odemknout                                           (UZIVATEL_EDIT)
    GET /role, PATCH /role/{id}                                              (UZIVATEL_EDIT)
    GET|POST /terminaly, PATCH /terminaly/{id}                               (UZIVATEL_EDIT)
Session plní a maže jen tento ostrov (app.platforma.auth.prihlas / odhlas, docs/adr/0007).
"""
from flask import Blueprint

from app.platforma.auth import kontext, odhlas, prihlas, verejne, vyzaduje
from app.platforma.chyby import AppError
from app.platforma.http import dokumentuj, nacti_parametry, nacti_vstup, odpoved
from app.platforma.kontrakty import DuvodVstup, Seznam, Strana
from app.platforma.typy import Kontext

from . import sluzby
from .kontrakty import (
    NovyTerminalVstup,
    NovyUzivatelVstup,
    PrihlaseniVstup,
    PrihlasenyUzivatel,
    ResetPinuVstup,
    RoleRadek,
    TerminalRadek,
    UzivateleFiltr,
    UzivatelRadek,
    ZmenaRoleVstup,
    ZmenaTerminaluVstup,
    ZmenaUzivateleVstup,
)

api = Blueprint("identita_api", __name__)

# --- přihlášení ------------------------------------------------------------------------------------


@api.post("/prihlaseni")
@verejne
@dokumentuj(vstup=PrihlaseniVstup, vystup=PrihlasenyUzivatel,
            popis="Přihlášení osobním číslem a PINem; PDA posílá i kód terminálu. Chyba je vždy stejná.")
def prihlaseni():
    uzivatel = sluzby.over_prihlaseni(nacti_vstup(PrihlaseniVstup))
    if uzivatel is None:
        # až tady, po potvrzení transakce: počítadlo, zámek i řádek pokusu zůstanou (D-33, S-17)
        raise AppError("NOT_AUTHENTICATED", sluzby.ZPRAVA_NEPLATNE)
    prihlas(Kontext(uzivatel.uzivatel_id, uzivatel.terminal_id, uzivatel.kod_role, frozenset(uzivatel.opravneni)))
    return odpoved(uzivatel, f"Přihlášen {uzivatel.cele_jmeno}.")


@api.post("/odhlaseni")
@verejne
@dokumentuj(popis="Odhlásí (smaže session). Bez přihlášení nic nedělá.")
def odhlaseni():
    odhlas()
    return odpoved(zprava="Odhlášeno.")


@api.get("/ja")
@dokumentuj(vystup=PrihlasenyUzivatel, popis="Přihlášený uživatel s aktuálními oprávněními.")
def ja():
    return odpoved(sluzby.ja(kontext()), "Načteno.")


# --- uživatelé (UZIVATEL_EDIT) ---------------------------------------------------------------------


@api.get("/uzivatele")
@vyzaduje("UZIVATEL_EDIT")
@dokumentuj(parametry=UzivateleFiltr, vystup=Strana[UzivatelRadek], popis="Uživatelé s filtrem (bez PINu a karty).")
def uzivatele():
    return odpoved(sluzby.seznam_uzivatelu(nacti_parametry(UzivateleFiltr)), "Načteno.")


@api.post("/uzivatele")
@vyzaduje("UZIVATEL_EDIT")
@dokumentuj(vstup=NovyUzivatelVstup, vystup=UzivatelRadek, popis="Založí uživatele; PIN se uloží jen jako hash.")
def zaloz_uzivatele():
    uzivatel = sluzby.zaloz_uzivatele(vstup=nacti_vstup(NovyUzivatelVstup), kdo=kontext())
    return odpoved(uzivatel, f"Uživatel {uzivatel.cele_jmeno} založen.")


@api.patch("/uzivatele/<int:uzivatel_id>")
@vyzaduje("UZIVATEL_EDIT")
@dokumentuj(vstup=ZmenaUzivateleVstup, vystup=UzivatelRadek, popis="Změní jméno, roli nebo kartu uživatele.")
def zmen_uzivatele(uzivatel_id: int):
    return odpoved(sluzby.zmen_uzivatele(uzivatel_id=uzivatel_id, vstup=nacti_vstup(ZmenaUzivateleVstup),
                                         kdo=kontext()), "Uloženo.")


@api.post("/uzivatele/<int:uzivatel_id>/deaktivovat")
@vyzaduje("UZIVATEL_EDIT")
@dokumentuj(vstup=DuvodVstup, vystup=UzivatelRadek, popis="Vyřadí uživatele; jeho přihlášení přestane platit hned.")
def deaktivuj_uzivatele(uzivatel_id: int):
    return odpoved(sluzby.deaktivuj_uzivatele(uzivatel_id=uzivatel_id, vstup=nacti_vstup(DuvodVstup),
                                              kdo=kontext()), "Uživatel vyřazen.")


@api.post("/uzivatele/<int:uzivatel_id>/reset-pinu")
@vyzaduje("UZIVATEL_EDIT")
@dokumentuj(vstup=ResetPinuVstup, vystup=UzivatelRadek, popis="Nastaví uživateli nový PIN (4–8 číslic).")
def reset_pinu(uzivatel_id: int):
    return odpoved(sluzby.nastav_pin(uzivatel_id=uzivatel_id, vstup=nacti_vstup(ResetPinuVstup), kdo=kontext()),
                   "PIN nastaven.")


@api.post("/uzivatele/<int:uzivatel_id>/odemknout")
@vyzaduje("UZIVATEL_EDIT")
@dokumentuj(vstup=DuvodVstup, vystup=UzivatelRadek,
            popis="Uvolní účet zamčený po chybných PINech a vynuluje počítadlo (D-33).")
def odemknout_uzivatele(uzivatel_id: int):
    return odpoved(sluzby.odemknout_uzivatele(uzivatel_id=uzivatel_id, vstup=nacti_vstup(DuvodVstup),
                                              kdo=kontext()), "Uživatel odemčen.")


# --- role a terminály (UZIVATEL_EDIT) -------------------------------------------------------------


@api.get("/role")
@vyzaduje("UZIVATEL_EDIT")
@dokumentuj(vystup=Seznam[RoleRadek], popis="Role s oprávněními.")
def role():
    return odpoved(sluzby.seznam_roli(), "Načteno.")


@api.patch("/role/<int:role_id>")
@vyzaduje("UZIVATEL_EDIT")
@dokumentuj(vstup=ZmenaRoleVstup, vystup=RoleRadek, popis="Změní název, popis nebo celý seznam oprávnění role.")
def zmen_roli(role_id: int):
    return odpoved(sluzby.zmen_roli(role_id=role_id, vstup=nacti_vstup(ZmenaRoleVstup), kdo=kontext()), "Uloženo.")


@api.get("/terminaly")
@vyzaduje("UZIVATEL_EDIT")
@dokumentuj(vystup=Seznam[TerminalRadek], popis="Evidované terminály (PDA).")
def terminaly():
    return odpoved(sluzby.seznam_terminalu(), "Načteno.")


@api.post("/terminaly")
@vyzaduje("UZIVATEL_EDIT")
@dokumentuj(vstup=NovyTerminalVstup, vystup=TerminalRadek, popis="Zaeviduje terminál.")
def zaloz_terminal():
    terminal = sluzby.zaloz_terminal(vstup=nacti_vstup(NovyTerminalVstup), kdo=kontext())
    return odpoved(terminal, f"Terminál {terminal.kod_terminalu} založen.")


@api.patch("/terminaly/<int:terminal_id>")
@vyzaduje("UZIVATEL_EDIT")
@dokumentuj(vstup=ZmenaTerminaluVstup, vystup=TerminalRadek, popis="Změní název, pracoviště nebo aktivitu terminálu.")
def zmen_terminal(terminal_id: int):
    return odpoved(sluzby.zmen_terminal(terminal_id=terminal_id, vstup=nacti_vstup(ZmenaTerminaluVstup),
                                        kdo=kontext()), "Uloženo.")
