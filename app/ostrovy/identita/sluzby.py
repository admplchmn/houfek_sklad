"""Služby ostrova B – Identita. Jedna operace = @transakce, čtení = @cteni.

Fáze 1: data jsou z databáze (`repozitar`), PIN se ověřuje argon2 hashem (`domena.pin_sedi`) a
každá změna kmenových dat se píše do auditu (`app.platforma.audit`). Důvod změny jde do
`AuditZmen.Poznamka`; PIN ani kód karty se nikdy jako hodnota neaudituje – jen slovo „změněno“.

Session nečte ani nezapisuje žádná služba – to dělá endpoint přes app.platforma.auth.
"""
from __future__ import annotations

from typing import Any

from pydantic import SecretStr

from app.platforma import audit
from app.platforma.chyby import AppError, chyba_vstupu
from app.platforma.db import Spojeni, cteni
from app.platforma.kontrakty import DuvodVstup, Seznam, Strana, teď
from app.platforma.transakce import transakce
from app.platforma.typy import Kontext

from . import domena, repozitar
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

ZPRAVA_NEPLATNE = "Neplatné osobní číslo nebo PIN."
ZPRAVA_NEPLATI = "Přihlášení už neplatí. Přihlaste se znovu."
ZMENENO = "změněno"      # hodnota PINu a karty se do auditu nikdy nedostane

# --- přihlášení ------------------------------------------------------------------------------------


@transakce("PRIHLASENI")
def over_prihlaseni(spoj: Spojeni, vstup: PrihlaseniVstup) -> PrihlasenyUzivatel | None:
    """Osobní číslo + PIN (+ kód terminálu z PDA) → přihlášený uživatel s aktuálními oprávněními role.

    Neúspěch se vrací jako `None`, nikoli jako AppError: @transakce by při chybě vrátil zpět i
    počítadlo, zámek a řádek pokusu, které potvrzené zůstat mají. Chybu NOT_AUTHENTICATED vyvolá
    až endpoint, takže neznámé číslo, chybný PIN, uživatel bez PINu, vyřazený i zamčený účet
    odpoví vždy stejně (7.2 „Hotovo, když“). Hash se ověřuje vždy, i když se jeho výsledek
    nepoužije – odpověď nesmí nic prozradit (kontrakt B).

    Každý pokus je jeden řádek `PrihlaseniPokus` bez PINu; pět chybných PINů po sobě zamkne účet
    na 15 minut a úspěch počítadlo vynuluje (D-33, pravidlo `domena.vyhodnot_pokus`).
    Chyby: VALIDATION_ERROR (neznámý nebo vyřazený terminál).
    """
    terminal = _terminal_pri_prihlaseni(spoj, vstup.kod_terminalu)
    try:
        cislo = domena.normalizuj_osobni_cislo(vstup.osobni_cislo)
    except AppError:
        raise AppError("NOT_AUTHENTICATED", ZPRAVA_NEPLATNE) from None
    radek = repozitar.uzivatel_podle_cisla(spoj, cislo) or {}
    platny_pin = domena.pin_sedi(vstup.pin.get_secret_value(), radek.get("PinHash"))
    vysledek, chybne_pokusy, zamceno_do = domena.vyhodnot_pokus(
        existuje=bool(radek), aktivni=bool(radek.get("Aktivni")), zamceno_do=radek.get("ZamcenoDo"),
        pin_plati=platny_pin, chybne_pokusy=int(radek.get("ChybnePokusy", 0)), ted=teď())
    if radek:
        repozitar.nastav_zamek(spoj, int(radek["UzivatelID"]), chybne_pokusy=chybne_pokusy,
                               zamceno_do=zamceno_do)
    repozitar.zapis_pokus(spoj, osobni_cislo=cislo, uzivatel_id=radek.get("UzivatelID"),
                          terminal_id=terminal.terminal_id if terminal else None, vysledek=vysledek)
    if vysledek != domena.POKUS_USPECH:
        return None
    return PrihlasenyUzivatel(
        uzivatel_id=int(radek["UzivatelID"]), osobni_cislo=radek["OsobniCislo"],
        cele_jmeno=domena.cele_jmeno(radek["Jmeno"], radek["Prijmeni"]),
        kod_role=radek["KodRole"], nazev_role=radek["NazevRole"],
        opravneni=repozitar.opravneni_role(spoj, int(radek["RoleID"])),
        terminal_id=terminal.terminal_id if terminal else None,
        kod_terminalu=terminal.kod_terminalu if terminal else None,
        pracoviste_id=terminal.pracoviste_id if terminal else None)


@cteni
def ja(spoj: Spojeni, kdo: Kontext) -> PrihlasenyUzivatel:
    """Přihlášený uživatel s aktuálními údaji. Chyby: NOT_AUTHENTICATED (mezitím smazaný uživatel)."""
    radky = repozitar.prihlaseny_uzivatel(spoj, kdo.uzivatel_id, kdo.terminal_id)
    if not radky:
        raise AppError("NOT_AUTHENTICATED", ZPRAVA_NEPLATI)
    prvni = radky[0]
    return PrihlasenyUzivatel(
        uzivatel_id=int(prvni["UzivatelID"]), osobni_cislo=prvni["OsobniCislo"],
        cele_jmeno=domena.cele_jmeno(prvni["Jmeno"], prvni["Prijmeni"]),
        kod_role=prvni["KodRole"], nazev_role=prvni["NazevRole"],
        opravneni=sorted({radek["KodOpravneni"] for radek in radky if radek["KodOpravneni"]}),
        terminal_id=prvni["TerminalID"], kod_terminalu=prvni["KodTerminalu"],
        pracoviste_id=prvni["PracovisteID"])


@cteni
def over_kontext(spoj: Spojeni, kdo: Kontext) -> Kontext | None:
    """Hák Platformy (docs/adr/0007): volá se při každém požadavku přihlášeného uživatele.

    None = uživatel neaktivní nebo smazaný → Platforma smaže session, vyřazení tedy platí už
    příštím požadavkem. Vrací AKTUÁLNÍ oprávnění role, takže i odebrané právo přestane platit
    příštím požadavkem (jeden dotaz podle PK).
    Bez SQL Serveru (vývoj a testy bez DB) tabulky ostrova neexistují – tam se vrací kostra.
    """
    if spoj.dialekt != "mssql":
        from . import ukazky  # KOSTRA (fáze 0): vývoj a testy bez SQL Serveru

        uzivatel = ukazky.UZIVATELE.get(kdo.uzivatel_id)
        return None if (uzivatel is not None and not uzivatel.aktivni) else kdo
    radky = repozitar.kontext_uzivatele(spoj, kdo.uzivatel_id)
    if not radky or not radky[0]["Aktivni"]:
        return None
    return Kontext(kdo.uzivatel_id, kdo.terminal_id, radky[0]["KodRole"],
                   frozenset(radek["KodOpravneni"] for radek in radky if radek["KodOpravneni"]))


# --- uživatelé (UZIVATEL_EDIT) ---------------------------------------------------------------------


@cteni
def seznam_uzivatelu(spoj: Spojeni, filtr: UzivateleFiltr) -> Strana[UzivatelRadek]:
    """Jménem, příjmením ani osobním číslem se nedá zjistit cokoliv citlivého – PIN a karta se nečtou."""
    radky, celkem = repozitar.seznam_uzivatelu(spoj, hledat=filtr.hledat, role_id=filtr.role_id,
                                               aktivni=filtr.aktivni, strana=filtr.strana,
                                               velikost=filtr.velikost)
    return Strana[UzivatelRadek](polozky=[_uzivatel(radek) for radek in radky], strana=filtr.strana,
                                 velikost=filtr.velikost, celkem=celkem)


@transakce("UZIVATEL_ZALOZENI")
def zaloz_uzivatele(spoj: Spojeni, vstup: NovyUzivatelVstup, kdo: Kontext) -> UzivatelRadek:
    """PIN se ukládá jen jako hash. Chyby: VALIDATION_ERROR (osobní číslo, PIN),
    ALREADY_EXISTS (osobní číslo nebo karta), NOT_FOUND (role)."""
    cislo = domena.normalizuj_osobni_cislo(vstup.osobni_cislo)
    if vstup.pin is not None:
        domena.over_pin(vstup.pin.get_secret_value())
    role = _nacti_roli(spoj, vstup.role_id)
    if repozitar.existuje_osobni_cislo(spoj, cislo):
        raise AppError("ALREADY_EXISTS", f"Uživatel s osobním číslem {cislo} už existuje.")
    karta = _kod_karty(vstup.kod_karty)
    if karta is not None and repozitar.existuje_karta(spoj, karta):
        raise AppError("ALREADY_EXISTS", "Kartu s tímto kódem už má jiný uživatel.")
    uzivatel_id = repozitar.vloz_uzivatele(
        spoj, osobni_cislo=cislo, jmeno=vstup.jmeno, prijmeni=vstup.prijmeni, role_id=role.role_id,
        pin_hash=domena.zahashuj_pin(vstup.pin.get_secret_value()) if vstup.pin is not None else None,
        kod_karty=karta)
    zmeny = [("Jmeno", None, vstup.jmeno), ("Prijmeni", None, vstup.prijmeni), ("RoleID", None, role.kod_role)]
    if vstup.pin is not None:
        zmeny.append(("PinHash", None, ZMENENO))
    if karta is not None:
        zmeny.append(("KodKarty", None, ZMENENO))
    _zaloguj(spoj, kdo, "UZIVATEL", uzivatel_id, zmeny, duvod=None)
    return _nacti_uzivatele(spoj, uzivatel_id)


@transakce("UZIVATEL_ZMENA")
def zmen_uzivatele(spoj: Spojeni, uzivatel_id: int, vstup: ZmenaUzivateleVstup, kdo: Kontext) -> UzivatelRadek:
    """Audit u karty zapíše jen „změněno“, nikdy hodnotu. Chyby: NOT_FOUND (uživatel, role), ALREADY_EXISTS (karta)."""
    puvodni = _nacti_uzivatele(spoj, uzivatel_id)
    zmena = vstup.zmenena_pole()
    role = _nacti_roli(spoj, zmena["role_id"]) if "role_id" in zmena else None
    karta = _kod_karty(zmena["kod_karty"]) if "kod_karty" in zmena else None
    if karta is not None and repozitar.existuje_karta(spoj, karta, krome_id=uzivatel_id):
        raise AppError("ALREADY_EXISTS", "Kartu s tímto kódem už má jiný uživatel.")
    jmeno = zmena.get("jmeno", puvodni.jmeno)
    prijmeni = zmena.get("prijmeni", puvodni.prijmeni)
    zmeny: list[tuple[str, Any, Any]] = []
    if "jmeno" in zmena:
        zmeny.append(("Jmeno", puvodni.jmeno, jmeno))
    if "prijmeni" in zmena:
        zmeny.append(("Prijmeni", puvodni.prijmeni, prijmeni))
    if role is not None:
        zmeny.append(("RoleID", puvodni.kod_role, role.kod_role))
    if "kod_karty" in zmena:
        zmeny.append(("KodKarty", ZMENENO if puvodni.ma_kartu else None, ZMENENO if karta is not None else None))
    repozitar.zmen_kmenova_data(spoj, uzivatel_id, jmeno=jmeno, prijmeni=prijmeni,
                                role_id=role.role_id if role is not None else puvodni.role_id)
    if "kod_karty" in zmena:
        repozitar.nastav_kartu(spoj, uzivatel_id, karta)
    _zaloguj(spoj, kdo, "UZIVATEL", uzivatel_id, zmeny, vstup.duvod)
    return _nacti_uzivatele(spoj, uzivatel_id)


@transakce("UZIVATEL_DEAKTIVACE")
def deaktivuj_uzivatele(spoj: Spojeni, uzivatel_id: int, vstup: DuvodVstup, kdo: Kontext) -> UzivatelRadek:
    """Vyřazený uživatel se nepřihlásí a jeho běžící session přestane platit při dalším požadavku
    (hák over_kontext). Chyby: NOT_FOUND, VALIDATION_ERROR (sám sebe, poslední aktivní správce)."""
    uzivatel = _nacti_uzivatele(spoj, uzivatel_id)
    domena.over_deaktivaci(uzivatel_id, kdo.uzivatel_id)
    if uzivatel.aktivni:
        if uzivatel.kod_role == domena.ROLE_SPRAVCE:
            domena.over_posledniho_spravce(repozitar.pocet_activnich_spravcu(spoj, domena.ROLE_SPRAVCE))
        repozitar.deaktivuj_uzivatele(spoj, uzivatel_id)
        _zaloguj(spoj, kdo, "UZIVATEL", uzivatel_id, [("Aktivni", True, False)], vstup.duvod)
    return _nacti_uzivatele(spoj, uzivatel_id)


@transakce("UZIVATEL_PIN")
def nastav_pin(spoj: Spojeni, uzivatel_id: int, vstup: ResetPinuVstup, kdo: Kontext) -> UzivatelRadek:
    """Správce nastaví nový PIN (sdělí ho uživateli osobně). Audit bez hodnoty. Chyby: NOT_FOUND, VALIDATION_ERROR."""
    uzivatel = _nacti_uzivatele(spoj, uzivatel_id)
    domena.over_pin(vstup.novy_pin.get_secret_value(), pole="novyPin")
    repozitar.nastav_pin_hash(spoj, uzivatel_id, domena.zahashuj_pin(vstup.novy_pin.get_secret_value()))
    _zaloguj(spoj, kdo, "UZIVATEL", uzivatel_id, [("PinHash", ZMENENO if uzivatel.ma_pin else None, ZMENENO)],
             vstup.duvod)
    return _nacti_uzivatele(spoj, uzivatel_id)


@transakce("UZIVATEL_ODEMKNUTI")
def odemknout_uzivatele(spoj: Spojeni, uzivatel_id: int, vstup: DuvodVstup, kdo: Kontext) -> UzivatelRadek:
    """Správce uvolní účet zamčený chybnými PINy (D-33): počítadlo i zámek jdou na nulu.

    Účet bez zámku a bez pokusů se nepřepisuje ani neaudituje – jako u deaktivace.
    Chyby: NOT_FOUND (uživatel).
    """
    zamek = repozitar.stav_zamku(spoj, uzivatel_id)
    if zamek is None:
        raise AppError("NOT_FOUND", f"Uživatel {uzivatel_id} neexistuje.")
    zmeny: list[tuple[str, Any, Any]] = []
    if zamek["ChybnePokusy"]:
        zmeny.append(("ChybnePokusy", zamek["ChybnePokusy"], 0))
    if zamek["ZamcenoDo"] is not None:
        zmeny.append(("ZamcenoDo", zamek["ZamcenoDo"], None))
    if zmeny:
        repozitar.nastav_zamek(spoj, uzivatel_id, chybne_pokusy=0, zamceno_do=None)
        _zaloguj(spoj, kdo, "UZIVATEL", uzivatel_id, zmeny, vstup.duvod)
    return _nacti_uzivatele(spoj, uzivatel_id)


# --- role (UZIVATEL_EDIT) ------------------------------------------------------------------------


@cteni
def seznam_roli(spoj: Spojeni) -> Seznam[RoleRadek]:
    return Seznam[RoleRadek](polozky=_role_s_opravnenimi(repozitar.seznam_roli(spoj)))


@transakce("ROLE_ZMENA")
def zmen_roli(spoj: Spojeni, role_id: int, vstup: ZmenaRoleVstup, kdo: Kontext) -> RoleRadek:
    """Nový seznam oprávnění platí hned pro všechny přihlášené s touto rolí (hák over_kontext).

    Chyby: NOT_FOUND, VALIDATION_ERROR (neznámý kód, ADMIN bez UZIVATEL_EDIT).
    """
    role = _nacti_roli(spoj, role_id)
    zmena = vstup.zmenena_pole()
    zmeny: list[tuple[str, Any, Any]] = []
    if "nazev" in zmena:
        zmeny.append(("NazevRole", role.nazev, zmena["nazev"]))
    if "popis" in zmena:
        zmeny.append(("Popis", role.popis, zmena["popis"]))
    kodu: list[str] | None = None
    if "opravneni" in zmena:
        kodu = domena.over_opravneni(zmena["opravneni"], repozitar.znama_opravneni(spoj))
        domena.over_zmenu_role(role.kod_role, kodu)
        zmeny += [("RoleOpravneni", None, kod) for kod in sorted(set(kodu) - set(role.opravneni))]
        zmeny += [("RoleOpravneni", kod, None) for kod in sorted(set(role.opravneni) - set(kodu))]
    if "nazev" in zmena or "popis" in zmena:
        repozitar.zmen_roli(spoj, role_id, nazev=zmena.get("nazev", role.nazev), popis=zmena.get("popis", role.popis))
    if kodu is not None and kodu != role.opravneni:
        repozitar.nastav_opravneni_role(spoj, role_id, kodu)
    _zaloguj(spoj, kdo, "ROLE", role_id, zmeny, vstup.duvod)
    return _nacti_roli(spoj, role_id)


# --- terminály (UZIVATEL_EDIT) ---------------------------------------------------------------------


@cteni
def seznam_terminalu(spoj: Spojeni) -> Seznam[TerminalRadek]:
    return Seznam[TerminalRadek](polozky=[_terminal(radek) for radek in repozitar.seznam_terminalu(spoj)])


@transakce("TERMINAL_ZALOZENI")
def zaloz_terminal(spoj: Spojeni, vstup: NovyTerminalVstup, kdo: Kontext) -> TerminalRadek:
    """Chyby: VALIDATION_ERROR (kód, neexistující pracoviště), ALREADY_EXISTS (kód terminálu)."""
    kod = domena.normalizuj_kod_terminalu(vstup.kod_terminalu)
    if repozitar.existuje_terminal(spoj, kod):
        raise AppError("ALREADY_EXISTS", f"Terminál {kod} už existuje.")
    with repozitar.cizi_id("pracovisteId", "Pracoviště"):
        terminal_id = repozitar.vloz_terminal(spoj, kod_terminalu=kod, nazev=vstup.nazev,
                                              pracoviste_id=vstup.pracoviste_id)
    _zaloguj(spoj, kdo, "TERMINAL", terminal_id,
             [("KodTerminalu", None, kod), ("NazevTerminalu", None, vstup.nazev),
              ("PracovisteID", None, vstup.pracoviste_id)], duvod=None)
    return _nacti_terminal(spoj, terminal_id)


@transakce("TERMINAL_ZMENA")
def zmen_terminal(spoj: Spojeni, terminal_id: int, vstup: ZmenaTerminaluVstup, kdo: Kontext) -> TerminalRadek:
    """Chyby: NOT_FOUND, VALIDATION_ERROR (neexistující pracoviště)."""
    terminal = _nacti_terminal(spoj, terminal_id)
    zmena = vstup.zmenena_pole()
    zmeny: list[tuple[str, Any, Any]] = []
    for pole, sloupec in (("nazev", "NazevTerminalu"), ("pracoviste_id", "PracovisteID"), ("aktivni", "Aktivni")):
        if pole in zmena:
            zmeny.append((sloupec, getattr(terminal, pole), zmena[pole]))
    with repozitar.cizi_id("pracovisteId", "Pracoviště"):
        repozitar.zmen_terminalu(spoj, terminal_id, nazev=zmena.get("nazev", terminal.nazev),
                                 pracoviste_id=zmena.get("pracoviste_id", terminal.pracoviste_id),
                                 aktivni=bool(zmena.get("aktivni", terminal.aktivni)))
    _zaloguj(spoj, kdo, "TERMINAL", terminal_id, zmeny, vstup.duvod)
    return _nacti_terminal(spoj, terminal_id)


# --- pomocné -------------------------------------------------------------------------------------


def _terminal_pri_prihlaseni(spoj: Spojeni, kod_terminalu: str | None) -> TerminalRadek | None:
    """Terminál z PDA: musí být evidovaný a aktivní. Kód terminálu není tajný, chyba ho smí pojmenovat."""
    if kod_terminalu is None:
        return None
    kod = domena.normalizuj_kod_terminalu(kod_terminalu)
    radek = repozitar.terminal_podle_kodu(spoj, kod)
    if radek is None or not radek["Aktivni"]:
        raise chyba_vstupu(f"Terminál {kod} není evidovaný nebo je vyřazený. Kontaktujte správce.",
                           {"kodTerminalu": "Neznámý nebo vyřazený terminál."})
    return _terminal(radek)


def _nacti_uzivatele(spoj: Spojeni, uzivatel_id: int) -> UzivatelRadek:
    radek = repozitar.uzivatel_podle_id(spoj, uzivatel_id)
    if radek is None:
        raise AppError("NOT_FOUND", f"Uživatel {uzivatel_id} neexistuje.")
    return _uzivatel(radek)


def _nacti_roli(spoj: Spojeni, role_id: int) -> RoleRadek:
    radky = repozitar.role_podle_id(spoj, role_id)
    if not radky:
        raise AppError("NOT_FOUND", f"Role {role_id} neexistuje.")
    return _role_s_opravnenimi(radky)[0]


def _nacti_terminal(spoj: Spojeni, terminal_id: int) -> TerminalRadek:
    radek = repozitar.terminal_podle_id(spoj, terminal_id)
    if radek is None:
        raise AppError("NOT_FOUND", f"Terminál {terminal_id} neexistuje.")
    return _terminal(radek)


def _kod_karty(karta: SecretStr | None) -> str | None:
    """Karta se mění jen jako celek (nastavit/vymazat); její kód se nikam nevypisuje ani neaudituje."""
    return karta.get_secret_value() if karta is not None else None


def _zaloguj(spoj: Spojeni, kdo: Kontext, typ_objektu: str, objekt_id: int,
             zmeny: list[tuple[str, Any, Any]], duvod: str | None) -> None:
    """Do auditu jeden řádek na každou změněnou vlastnost; důvod změny jde do poznámky (kap. 25)."""
    for pole, stara, nova in zmeny:
        audit.zapis(spoj, kdo, typ_objektu, objekt_id, pole, stara, nova, duvod)


def _uzivatel(radek: dict) -> UzivatelRadek:
    """`zamcenoDo` se ukazuje jen dokud zámek trvá (D-33): po 15 minutách přestal platit, takže už
    nemá koho odemknout a správce by mátl. Ve sloupci zůstává – přihlašování i odemknutí čtou skutečnou
    hodnotu, ne to, co viděl správce."""
    zamek = radek["ZamcenoDo"]
    return UzivatelRadek(uzivatel_id=int(radek["UzivatelID"]), osobni_cislo=radek["OsobniCislo"],
                         jmeno=radek["Jmeno"], prijmeni=radek["Prijmeni"],
                         cele_jmeno=domena.cele_jmeno(radek["Jmeno"], radek["Prijmeni"]),
                         role_id=int(radek["RoleID"]), kod_role=radek["KodRole"],
                         ma_pin=bool(radek["MaPin"]), ma_kartu=bool(radek["MaKartu"]),
                         aktivni=bool(radek["Aktivni"]),
                         zamceno_do=zamek if zamek is not None and zamek > teď() else None)


def _role_s_opravnenimi(radky: list[dict]) -> list[RoleRadek]:
    """Řádky role × oprávnění seskupené na jeden řádek kontraktu pro každou roli."""
    zaklady: dict[int, dict] = {}
    opravneni: dict[int, list[str]] = {}
    for radek in radky:
        role_id = int(radek["RoleID"])
        zaklady.setdefault(role_id, radek)
        if radek["KodOpravneni"]:
            opravneni.setdefault(role_id, []).append(radek["KodOpravneni"])
    return [RoleRadek(role_id=role_id, kod_role=radek["KodRole"], nazev=radek["NazevRole"],
                      popis=radek["Popis"], opravneni=sorted(opravneni.get(role_id, [])),
                      aktivni=bool(radek["Aktivni"]))
            for role_id, radek in zaklady.items()]


def _terminal(radek: dict) -> TerminalRadek:
    return TerminalRadek(terminal_id=int(radek["TerminalID"]), kod_terminalu=radek["KodTerminalu"],
                         nazev=radek["NazevTerminalu"], pracoviste_id=radek["PracovisteID"],
                         aktivni=bool(radek["Aktivni"]))
