"""Ostrov A – Platforma: vlastní endpointy /api/system a příkazy CLI.

Tabulky: AuditZmen, SkladovaTransakce, MigraceSchema. Pohled: v_KontrolaIntegrity.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import click
from flask import Blueprint, current_app
from flask.cli import AppGroup
from pydantic import Field

from .auth import prihlas, verejne, vyzaduje
from .chyby import ZAKLADNI_CHYBY, AppError
from .db import Spojeni, cteni, otevri_spojeni, spojeni_pro_skript
from .http import dokumentuj, nacti_parametry, nacti_vstup, odpoved, odpoved_chyby
from .kontrakty import Cas, Strana, Strankovani, Vstup, Vystup
from .migrace_db import db_cli
from .openapi import vytvor_openapi
from .ostrov import Ostrov, over_ostrovy_proti_db
from .typy import Kontext

VERZE = "0.1.0"
log = logging.getLogger("houfek.system")

api = Blueprint("system_api", __name__)


# --- kontrakty -------------------------------------------------------------------------

class ZdraviVystup(Vystup):
    stav: str
    verze: str
    rezim: str           # "PROVOZ" | "VYVOJ" – monitoring má hlásit VYVOJ na provozním serveru
    databaze: str        # "OK" | "NEDOSTUPNA" | "KOSTRA" (vývoj bez SQL Serveru, dočasná sqlite)


class AuditFiltr(Strankovani):
    typ_objektu: str | None = None
    objekt_id: int | None = None
    od: date | None = None
    do: date | None = None


class AuditZaznam(Vystup):
    audit_id: int
    datum_cas: Cas
    uzivatel_id: int
    typ_objektu: str
    objekt_id: int
    pole: str
    stara_hodnota: str | None
    nova_hodnota: str | None
    poznamka: str | None


class NalezIntegrity(Vystup):
    kontrola: str
    zavaznost: str
    objekt_id: int
    popis: str


class KontrolaIntegrityVystup(Vystup):
    nalezy: list[NalezIntegrity]


class VyvojovePrihlaseniVstup(Vstup):
    uzivatel_id: int = Field(..., ge=1)
    terminal_id: int | None = None
    kod_role: str = "ADMIN"
    opravneni: list[str] | None = None   # None = všechna oprávnění deklarovaná ostrovy


class PrihlasenyVystup(Vystup):
    uzivatel_id: int
    terminal_id: int | None
    kod_role: str
    opravneni: list[str]


# --- endpointy -------------------------------------------------------------------------------

@api.get("/zdravi")
@verejne
@dokumentuj(vystup=ZdraviVystup,
            popis="Stav aplikace a dostupnost databáze. Pro monitoring: HTTP 200 = v pořádku, 503 = DB nedostupná.")
def zdravi():
    rezim = "VYVOJ" if current_app.config.get("HOUFEK_VYVOJ") else "PROVOZ"
    try:
        spoj = otevri_spojeni()
        try:
            spoj.hodnota("SELECT 1 AS Ok")
        finally:
            spoj._rollback()
            spoj._zavri()
    except Exception as chyba:
        log.warning("Kontrola zdraví: databáze nedostupná: %s", chyba)
        vysledek = ZdraviVystup(stav="CHYBA", verze=VERZE, rezim=rezim, databaze="NEDOSTUPNA")
        return odpoved_chyby("DATABASE_UNAVAILABLE", data=vysledek.model_dump(mode="json", by_alias=True))
    databaze = "KOSTRA" if "houfek_kostra_db" in current_app.extensions else "OK"   # vývoj bez SQL Serveru
    return odpoved(ZdraviVystup(stav="OK", verze=VERZE, rezim=rezim, databaze=databaze))


@cteni
def _nacti_audit(spoj: Spojeni, filtr: AuditFiltr) -> Strana[AuditZaznam]:
    # Do SQL se skládají jen pevné podmínky; hodnoty jdou vždy jako parametry `?`.
    podminky: list[tuple[str, object]] = []
    if filtr.typ_objektu:
        podminky.append(("TypObjektu = ?", filtr.typ_objektu))
    if filtr.objekt_id is not None:
        podminky.append(("ObjektID = ?", filtr.objekt_id))
    if filtr.od:
        podminky.append(("DatumCas >= ?", filtr.od))
    if filtr.do:
        podminky.append(("DatumCas < ?", filtr.do + timedelta(days=1)))
    kde = " AND ".join(["1 = 1", *(podminka for podminka, _ in podminky)])
    parametry = [hodnota for _, hodnota in podminky]
    celkem = spoj.hodnota(f"SELECT COUNT(*) AS Pocet FROM dbo.AuditZmen WHERE {kde}", *parametry)
    radky = spoj.dotaz(
        "SELECT AuditID, DatumCas, UzivatelID, TypObjektu, ObjektID, Pole, StaraHodnota, NovaHodnota, Poznamka"
        f" FROM dbo.AuditZmen WHERE {kde} ORDER BY AuditID DESC"
        " OFFSET ? ROWS FETCH NEXT ? ROWS ONLY",
        *parametry, (filtr.strana - 1) * filtr.velikost, filtr.velikost)
    polozky = [AuditZaznam(audit_id=r["AuditID"], datum_cas=r["DatumCas"], uzivatel_id=r["UzivatelID"],
                           typ_objektu=r["TypObjektu"], objekt_id=r["ObjektID"], pole=r["Pole"],
                           stara_hodnota=r["StaraHodnota"], nova_hodnota=r["NovaHodnota"],
                           poznamka=r["Poznamka"]) for r in radky]
    return Strana[AuditZaznam](polozky=polozky, strana=filtr.strana, velikost=filtr.velikost, celkem=celkem or 0)


@api.get("/audit")
@vyzaduje("AUDIT_CIST")
@dokumentuj(parametry=AuditFiltr, vystup=Strana[AuditZaznam], popis="Historie změn kmenových dat.")
def audit():
    return odpoved(_nacti_audit(nacti_parametry(AuditFiltr)))


@cteni
def _nacti_integritu(spoj: Spojeni) -> KontrolaIntegrityVystup:
    radky = spoj.dotaz("SELECT Kontrola, Zavaznost, ObjektID, Popis FROM dbo.v_KontrolaIntegrity"
                       " ORDER BY Zavaznost, Kontrola, ObjektID")
    return KontrolaIntegrityVystup(nalezy=[
        NalezIntegrity(kontrola=r["Kontrola"], zavaznost=r["Zavaznost"], objekt_id=r["ObjektID"], popis=r["Popis"])
        for r in radky])


@api.get("/kontrola-integrity")
@vyzaduje("AUDIT_CIST")
@dokumentuj(vystup=KontrolaIntegrityVystup, popis="Pravidla, která nejde vynutit omezením (prázdné = v pořádku).")
def kontrola_integrity():
    vysledek = _nacti_integritu()
    zprava = "Bez nálezů." if not vysledek.nalezy else f"Nálezů: {len(vysledek.nalezy)}."
    return odpoved(vysledek, zprava)


@api.post("/vyvojove-prihlaseni")
@verejne
@dokumentuj(vstup=VyvojovePrihlaseniVstup, vystup=PrihlasenyVystup,
            popis="JEN VÝVOJ (HOUFEK_VYVOJ=1): přihlásí bez PINu, než bude hotový ostrov Identita.")
def vyvojove_prihlaseni():
    if not current_app.config.get("HOUFEK_VYVOJ"):
        raise AppError("NOT_FOUND", "Taková adresa API neexistuje.")
    vstup = nacti_vstup(VyvojovePrihlaseniVstup)
    vsechna = {k for o in current_app.extensions["houfek_ostrovy"].ostrovy for k in o.opravneni}
    opravneni = frozenset(vstup.opravneni if vstup.opravneni is not None else vsechna)
    prihlas(Kontext(vstup.uzivatel_id, vstup.terminal_id, vstup.kod_role, opravneni))
    return odpoved(PrihlasenyVystup(uzivatel_id=vstup.uzivatel_id, terminal_id=vstup.terminal_id,
                                    kod_role=vstup.kod_role, opravneni=sorted(opravneni)),
                   "Přihlášeno (vývojový režim).")


# --- příkazy CLI ------------------------------------------------------------------------------

platforma_cli = AppGroup("platforma", help="Kontroly a kontrakty Platformy.")


@platforma_cli.command("kontrola")
def kontrola() -> None:
    """Ověří ostrovy proti databázi: vlastníci tabulek, pohledy, oprávnění."""
    with spojeni_pro_skript() as spoj:
        nalezy = over_ostrovy_proti_db(current_app.extensions["houfek_ostrovy"].ostrovy, spoj)
    for nalez in nalezy:
        click.echo(f"- {nalez}")
    if nalezy:
        raise click.ClickException(f"Nálezů: {len(nalezy)}")
    click.echo("Ostrovy odpovídají databázi.")


@platforma_cli.command("integrita")
def integrita() -> None:
    """Kontrola integrity dat (v_KontrolaIntegrity) pro noční úlohu.

    Nález se závažností CHYBA = návratový kód 1, takže Plánovač úloh Windows pošle upozornění.
    """
    vysledek = _nacti_integritu()
    for nalez in vysledek.nalezy:
        click.echo(f"{nalez.zavaznost:<9} {nalez.kontrola:<28} {nalez.objekt_id:>9}  {nalez.popis}")
    chyb = sum(1 for nalez in vysledek.nalezy if nalez.zavaznost == "CHYBA")
    if chyb:
        raise click.ClickException(f"Nálezů se závažností CHYBA: {chyb} (všech nálezů {len(vysledek.nalezy)}).")
    click.echo(f"Bez chyb, ostatních nálezů: {len(vysledek.nalezy)}." if vysledek.nalezy else "Bez nálezů.")


@platforma_cli.command("openapi")
def openapi() -> None:
    """Vypíše openapi.json (kontrakt HTTP API)."""
    import json
    click.echo(json.dumps(vytvor_openapi(current_app), ensure_ascii=False, indent=2))


PLATFORMA = Ostrov(
    nazev="Platforma",
    prefix="system",
    api=api,
    prikazy=[db_cli, platforma_cli],
    tabulky=["AuditZmen", "SkladovaTransakce", "MigraceSchema"],
    pohledy=["v_KontrolaIntegrity", "v_SkladovaTransakce"],
    chyby=ZAKLADNI_CHYBY,
    opravneni=["AUDIT_CIST"],
)
