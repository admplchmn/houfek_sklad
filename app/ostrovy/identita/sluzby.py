"""Služby ostrova B – Identita. Jedna operace = @transakce, čtení = @cteni.

Fáze 0: kontrakt a čistá pravidla (domena) jsou hotové, data jsou vzorová (KOSTRA).
Ve fázi 1 vlastník nahradí řádky `from . import ukazky` voláním repozitar.*, ověření PINu
domena.pin_sedi (argon2) a doplní audit; podpisy funkcí se nemění.

Session nečte ani nezapisuje žádná služba – to dělá endpoint přes app.platforma.auth.
"""
from __future__ import annotations

import hmac

from app.platforma.chyby import AppError, chyba_vstupu
from app.platforma.db import Spojeni, cteni
from app.platforma.kontrakty import DuvodVstup, Seznam, Strana
from app.platforma.transakce import transakce
from app.platforma.typy import Kontext

from . import domena
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

NOVE_ID = 9001   # KOSTRA: ID nově založeného objektu ve vzorových odpovědích
ZPRAVA_NEPLATNE = "Neplatné osobní číslo nebo PIN."

# --- přihlášení ------------------------------------------------------------------------------------


@cteni
def over_prihlaseni(spoj: Spojeni, vstup: PrihlaseniVstup) -> PrihlasenyUzivatel:
    """Osobní číslo + PIN (+ kód terminálu z PDA) → přihlášený uživatel s aktuálními oprávněními role.

    Neznámé číslo, chybný PIN, uživatel bez PINu i neaktivní uživatel vrací stejnou chybu
    NOT_AUTHENTICATED (7.2 „Hotovo, když“). Fáze 1: domena.pin_sedi proti Uzivatel.PinHash
    (i pro neexistujícího uživatele, kvůli stejné době odpovědi) a zámek po chybných pokusech (TD-07).
    Chyby: NOT_AUTHENTICATED, VALIDATION_ERROR (neznámý nebo vyřazený terminál).
    """
    from . import ukazky  # KOSTRA (fáze 0)

    terminal = _terminal_pri_prihlaseni(vstup.kod_terminalu)
    try:
        cislo = domena.normalizuj_osobni_cislo(vstup.osobni_cislo)
    except AppError:
        raise AppError("NOT_AUTHENTICATED", ZPRAVA_NEPLATNE) from None
    uzivatel = next((u for u in ukazky.UZIVATELE.values() if u.osobni_cislo == cislo), None)
    ulozeny_pin = ukazky.PINY.get(cislo, "")
    pin_sedi = hmac.compare_digest(vstup.pin.get_secret_value().encode(), ulozeny_pin.encode()) and bool(ulozeny_pin)
    if uzivatel is None or not uzivatel.aktivni or not pin_sedi:
        raise AppError("NOT_AUTHENTICATED", ZPRAVA_NEPLATNE)
    role = _nacti_roli(uzivatel.role_id)
    return PrihlasenyUzivatel(
        uzivatel_id=uzivatel.uzivatel_id, osobni_cislo=uzivatel.osobni_cislo, cele_jmeno=uzivatel.cele_jmeno,
        kod_role=role.kod_role, nazev_role=role.nazev, opravneni=sorted(role.opravneni),
        terminal_id=terminal.terminal_id if terminal else None,
        kod_terminalu=terminal.kod_terminalu if terminal else None,
        pracoviste_id=terminal.pracoviste_id if terminal else None)


@cteni
def ja(spoj: Spojeni, kdo: Kontext) -> PrihlasenyUzivatel:
    """Přihlášený uživatel s aktuálními údaji. Chyby: NOT_AUTHENTICATED (mezitím smazaný uživatel)."""
    from . import ukazky  # KOSTRA (fáze 0)

    uzivatel = ukazky.UZIVATELE.get(kdo.uzivatel_id)
    if uzivatel is None:
        raise AppError("NOT_AUTHENTICATED", "Přihlášení už neplatí. Přihlaste se znovu.")
    role = _nacti_roli(uzivatel.role_id)
    terminal = next((t for t in ukazky.TERMINALY if t.terminal_id == kdo.terminal_id), None)
    return PrihlasenyUzivatel(
        uzivatel_id=uzivatel.uzivatel_id, osobni_cislo=uzivatel.osobni_cislo, cele_jmeno=uzivatel.cele_jmeno,
        kod_role=role.kod_role, nazev_role=role.nazev, opravneni=sorted(kdo.opravneni),
        terminal_id=kdo.terminal_id, kod_terminalu=terminal.kod_terminalu if terminal else None,
        pracoviste_id=terminal.pracoviste_id if terminal else None)


@cteni
def over_kontext(spoj: Spojeni, kdo: Kontext) -> Kontext | None:
    """Hák Platformy (docs/adr/0007): volá se při každém požadavku přihlášeného uživatele.

    None = uživatel neaktivní nebo smazaný → Platforma smaže session. Fáze 1: jeden dotaz podle PK
    (v_Uzivatel + RoleOpravneni) a vrátí Kontext s AKTUÁLNÍMI oprávněními role.
    KOSTRA: odmítne jen uživatele, kteří jsou ve vzorových datech neaktivní; ostatní propustí beze
    změny, aby fungovalo vývojové přihlášení s libovolným ID (/api/system/vyvojove-prihlaseni).
    """
    from . import ukazky  # KOSTRA (fáze 0)

    uzivatel = ukazky.UZIVATELE.get(kdo.uzivatel_id)
    if uzivatel is not None and not uzivatel.aktivni:
        return None
    return kdo


# --- uživatelé (UZIVATEL_EDIT) ---------------------------------------------------------------------


@cteni
def seznam_uzivatelu(spoj: Spojeni, filtr: UzivateleFiltr) -> Strana[UzivatelRadek]:
    from . import ukazky  # KOSTRA (fáze 0)

    hledat = (filtr.hledat or "").casefold()
    radky = [u for u in ukazky.UZIVATELE.values()
             if hledat in f"{u.osobni_cislo} {u.cele_jmeno}".casefold()
             and filtr.role_id in (None, u.role_id) and (filtr.aktivni is None or u.aktivni == filtr.aktivni)]
    return Strana[UzivatelRadek](polozky=radky, strana=filtr.strana, velikost=filtr.velikost, celkem=len(radky))


@transakce("UZIVATEL_ZALOZENI")
def zaloz_uzivatele(spoj: Spojeni, vstup: NovyUzivatelVstup, kdo: Kontext) -> UzivatelRadek:
    """Chyby: VALIDATION_ERROR (osobní číslo, PIN), ALREADY_EXISTS (osobní číslo nebo karta), NOT_FOUND (role)."""
    from . import ukazky  # KOSTRA (fáze 0)

    cislo = domena.normalizuj_osobni_cislo(vstup.osobni_cislo)
    if vstup.pin is not None:
        domena.over_pin(vstup.pin.get_secret_value())     # fáze 1: PinHash = domena.zahashuj_pin(...)
    role = _nacti_roli(vstup.role_id)
    if any(u.osobni_cislo == cislo for u in ukazky.UZIVATELE.values()):
        raise AppError("ALREADY_EXISTS", f"Uživatel s osobním číslem {cislo} už existuje.")
    return UzivatelRadek(uzivatel_id=NOVE_ID, osobni_cislo=cislo, jmeno=vstup.jmeno, prijmeni=vstup.prijmeni,
                         cele_jmeno=domena.cele_jmeno(vstup.jmeno, vstup.prijmeni), role_id=role.role_id,
                         kod_role=role.kod_role, ma_pin=vstup.pin is not None, ma_kartu=vstup.kod_karty is not None,
                         aktivni=True)


@transakce("UZIVATEL_ZMENA")
def zmen_uzivatele(spoj: Spojeni, uzivatel_id: int, vstup: ZmenaUzivateleVstup, kdo: Kontext) -> UzivatelRadek:
    """Audit u karty zapíše jen „změněno“, nikdy hodnotu. Chyby: NOT_FOUND (uživatel, role), ALREADY_EXISTS (karta)."""
    uzivatel = _nacti_uzivatele(uzivatel_id)
    zmena = vstup.zmenena_pole()
    if "role_id" in zmena:
        role = _nacti_roli(zmena["role_id"])
        zmena["kod_role"] = role.kod_role
    if "kod_karty" in zmena:
        zmena["ma_kartu"] = zmena.pop("kod_karty") is not None
    novy = uzivatel.model_copy(update=zmena)
    return novy.model_copy(update={"cele_jmeno": domena.cele_jmeno(novy.jmeno, novy.prijmeni)})


@transakce("UZIVATEL_DEAKTIVACE")
def deaktivuj_uzivatele(spoj: Spojeni, uzivatel_id: int, vstup: DuvodVstup, kdo: Kontext) -> UzivatelRadek:
    """Vyřazený uživatel se nepřihlásí a jeho běžící session přestane platit při dalším požadavku
    (hák over_kontext). Chyby: NOT_FOUND, VALIDATION_ERROR (sám sebe)."""
    uzivatel = _nacti_uzivatele(uzivatel_id)
    domena.over_deaktivaci(uzivatel_id, kdo.uzivatel_id)
    return uzivatel.model_copy(update={"aktivni": False})


@transakce("UZIVATEL_PIN")
def nastav_pin(spoj: Spojeni, uzivatel_id: int, vstup: ResetPinuVstup, kdo: Kontext) -> UzivatelRadek:
    """Správce nastaví nový PIN (sdělí ho uživateli osobně). Audit bez hodnoty. Chyby: NOT_FOUND, VALIDATION_ERROR."""
    uzivatel = _nacti_uzivatele(uzivatel_id)
    domena.over_pin(vstup.novy_pin.get_secret_value(), pole="novyPin")
    return uzivatel.model_copy(update={"ma_pin": True})


# --- role (UZIVATEL_EDIT) ------------------------------------------------------------------------


@cteni
def seznam_roli(spoj: Spojeni) -> Seznam[RoleRadek]:
    from . import ukazky  # KOSTRA (fáze 0)

    return Seznam[RoleRadek](polozky=ukazky.ROLE)


@transakce("ROLE_ZMENA")
def zmen_roli(spoj: Spojeni, role_id: int, vstup: ZmenaRoleVstup, kdo: Kontext) -> RoleRadek:
    """Nový seznam oprávnění platí hned pro všechny přihlášené s touto rolí (hák over_kontext).

    Chyby: NOT_FOUND, VALIDATION_ERROR (neznámý kód, ADMIN bez UZIVATEL_EDIT).
    """
    from . import ukazky  # KOSTRA (fáze 0)

    role = _nacti_roli(role_id)
    zmena = vstup.zmenena_pole()
    if "opravneni" in zmena:
        zmena["opravneni"] = domena.over_opravneni(zmena["opravneni"], ukazky.ZNAMA_OPRAVNENI)
        domena.over_zmenu_role(role.kod_role, zmena["opravneni"])
    return role.model_copy(update=zmena)


# --- terminály (UZIVATEL_EDIT) ---------------------------------------------------------------------


@cteni
def seznam_terminalu(spoj: Spojeni) -> Seznam[TerminalRadek]:
    from . import ukazky  # KOSTRA (fáze 0)

    return Seznam[TerminalRadek](polozky=ukazky.TERMINALY)


@transakce("TERMINAL_ZALOZENI")
def zaloz_terminal(spoj: Spojeni, vstup: NovyTerminalVstup, kdo: Kontext) -> TerminalRadek:
    """Chyby: VALIDATION_ERROR (kód), ALREADY_EXISTS. Pracoviště ověří FK (fáze 1: v_Misto / pohled C)."""
    from . import ukazky  # KOSTRA (fáze 0)

    kod = domena.normalizuj_kod_terminalu(vstup.kod_terminalu)
    if any(t.kod_terminalu == kod for t in ukazky.TERMINALY):
        raise AppError("ALREADY_EXISTS", f"Terminál {kod} už existuje.")
    return TerminalRadek(terminal_id=NOVE_ID, kod_terminalu=kod, nazev=vstup.nazev,
                         pracoviste_id=vstup.pracoviste_id, aktivni=True)


@transakce("TERMINAL_ZMENA")
def zmen_terminal(spoj: Spojeni, terminal_id: int, vstup: ZmenaTerminaluVstup, kdo: Kontext) -> TerminalRadek:
    return _nacti_terminal(terminal_id).model_copy(update=vstup.zmenena_pole())


# --- pomocné -------------------------------------------------------------------------------------


def _terminal_pri_prihlaseni(kod_terminalu: str | None) -> TerminalRadek | None:
    """Terminál z PDA: musí být evidovaný a aktivní. Kód terminálu není tajný, chyba ho smí pojmenovat."""
    if kod_terminalu is None:
        return None
    from . import ukazky  # KOSTRA (fáze 0)

    kod = domena.normalizuj_kod_terminalu(kod_terminalu)
    terminal = next((t for t in ukazky.TERMINALY if t.kod_terminalu == kod and t.aktivni), None)
    if terminal is None:
        raise chyba_vstupu(f"Terminál {kod} není evidovaný nebo je vyřazený. Kontaktujte správce.",
                           {"kodTerminalu": "Neznámý nebo vyřazený terminál."})
    return terminal


def _nacti_uzivatele(uzivatel_id: int) -> UzivatelRadek:
    from . import ukazky  # KOSTRA (fáze 0)

    uzivatel = ukazky.UZIVATELE.get(uzivatel_id)
    if uzivatel is None:
        raise AppError("NOT_FOUND", f"Uživatel {uzivatel_id} neexistuje.")
    return uzivatel


def _nacti_roli(role_id: int) -> RoleRadek:
    from . import ukazky  # KOSTRA (fáze 0)

    for role in ukazky.ROLE:
        if role.role_id == role_id:
            return role
    raise AppError("NOT_FOUND", f"Role {role_id} neexistuje.")


def _nacti_terminal(terminal_id: int) -> TerminalRadek:
    from . import ukazky  # KOSTRA (fáze 0)

    for terminal in ukazky.TERMINALY:
        if terminal.terminal_id == terminal_id:
            return terminal
    raise AppError("NOT_FOUND", f"Terminál {terminal_id} neexistuje.")
