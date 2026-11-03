"""Konfigurace z proměnných prostředí. Přehled proměnných: docs/provoz.md.

Odkud se proměnné berou (skutečná proměnná prostředí má vždy přednost):
- vývoj: soubor `.env` v kořeni repozitáře, načte ho `flask …` (python-dotenv),
- provoz: soubor, na který ukazuje HOUFEK_KONFIGURACE_SOUBOR (mimo složku aplikace, chráněný
  právy NTFS). Čte ho stejně web (waitress), noční úloha i příkazy správce.

Hesla a klíče nikdy nepatří do kódu ani do repozitáře.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

SOUBOR_KONFIGURACE = "HOUFEK_KONFIGURACE_SOUBOR"


def nacti_soubor_konfigurace() -> None:
    """Načte soubor z HOUFEK_KONFIGURACE_SOUBOR do prostředí; existující proměnné nepřepíše."""
    cesta = os.environ.get(SOUBOR_KONFIGURACE, "").strip()
    if not cesta:
        return
    if not Path(cesta).is_file():
        raise RuntimeError(f"{SOUBOR_KONFIGURACE} ukazuje na {cesta}, ale soubor neexistuje nebo není čitelný.")
    from dotenv import load_dotenv

    load_dotenv(cesta, override=False, encoding="utf-8")


def _bool(hodnota: str | None, vychozi: bool) -> bool:
    if hodnota is None or hodnota.strip() == "":
        return vychozi
    return hodnota.strip().lower() in {"1", "true", "ano", "yes", "on"}


def _cislo(hodnota: str | None, vychozi: int) -> int:
    if hodnota is None or not hodnota.strip():
        return vychozi
    try:
        return int(hodnota)
    except ValueError:
        raise RuntimeError(f"Hodnota {hodnota!r} v konfiguraci musí být celé číslo.") from None


def _odbc(hodnota: str, *, vzdy: bool = False) -> str:
    """Hodnota ODBC atributu; se zvláštními znaky ve složených závorkách, aby středník
    nebo '}' v hodnotě nepřidal do řetězce další atribut."""
    if vzdy or any(znak in hodnota for znak in ";{}=") or hodnota != hodnota.strip():
        return "{" + hodnota.replace("}", "}}") + "}"
    return hodnota


@dataclass(frozen=True)
class Konfigurace:
    db_server: str = ""
    db_nazev: str = ""
    db_uzivatel: str = ""
    db_heslo: str = ""
    db_uzivatel_migrace: str = ""            # prázdné = stejný účet jako aplikace (vývoj)
    db_heslo_migrace: str = ""
    db_ovladac: str = "ODBC Driver 18 for SQL Server"
    db_sifrovat: bool = True                 # Encrypt=yes (na SRVACC01 je šifrování povinné)
    db_duverovat_certifikatu: bool = False   # TrustServerCertificate=yes jen pro interní certifikát
    db_limit_prihlaseni_s: int = 15
    db_limit_dotazu_s: int = 30              # zaseknutý dotaz nezablokuje terminál natrvalo
    db_limit_zamku_ms: int = 5000            # čekání na zámek pozice (chyba 1222 → CONCURRENT_CHANGE)
    tajny_klic: str = ""                     # podpis session cookie; ve vývoji se vygeneruje náhodně
    vyvoj: bool = False                      # vývojový režim: vývojové přihlášení, Swagger, cookie bez HTTPS
    kontrola_db_pri_startu: bool = False     # startovní kontroly proti DB (tabulky, pohledy, oprávnění)
    log_soubor: str = ""                     # prázdné = jen standardní výstup
    max_velikost_pozadavku: int = 1_048_576  # 1 MB; větší JSON je chyba

    @classmethod
    def z_prostredi(cls, prostredi: Mapping[str, str] | None = None) -> "Konfigurace":
        if prostredi is None:
            nacti_soubor_konfigurace()
        p = os.environ if prostredi is None else prostredi
        return cls(
            db_server=p.get("HOUFEK_DB_SERVER", ""),
            db_nazev=p.get("HOUFEK_DB_NAZEV", ""),
            db_uzivatel=p.get("HOUFEK_DB_UZIVATEL", ""),
            db_heslo=p.get("HOUFEK_DB_HESLO", ""),
            db_uzivatel_migrace=p.get("HOUFEK_DB_UZIVATEL_MIGRACE", ""),
            db_heslo_migrace=p.get("HOUFEK_DB_HESLO_MIGRACE", ""),
            db_ovladac=p.get("HOUFEK_DB_OVLADAC", cls.db_ovladac),
            db_sifrovat=_bool(p.get("HOUFEK_DB_SIFROVAT"), True),
            db_duverovat_certifikatu=_bool(p.get("HOUFEK_DB_DUVEROVAT_CERTIFIKATU"), False),
            db_limit_prihlaseni_s=_cislo(p.get("HOUFEK_DB_LIMIT_PRIHLASENI_S"), cls.db_limit_prihlaseni_s),
            db_limit_dotazu_s=_cislo(p.get("HOUFEK_DB_LIMIT_DOTAZU_S"), cls.db_limit_dotazu_s),
            db_limit_zamku_ms=_cislo(p.get("HOUFEK_DB_LIMIT_ZAMKU_MS"), cls.db_limit_zamku_ms),
            tajny_klic=p.get("HOUFEK_TAJNY_KLIC", ""),
            vyvoj=_bool(p.get("HOUFEK_VYVOJ"), False),
            kontrola_db_pri_startu=_bool(p.get("HOUFEK_KONTROLA_DB_PRI_STARTU"), False),
            log_soubor=p.get("HOUFEK_LOG_SOUBOR", ""),
        )

    def over(self) -> None:
        if not self.vyvoj and len(self.tajny_klic) < 32:
            raise RuntimeError("HOUFEK_TAJNY_KLIC musí mít v provozu aspoň 32 znaků.")

    def _retezec(self, uzivatel: str, heslo: str) -> str:
        chybi = [n for n, h in (("HOUFEK_DB_SERVER", self.db_server), ("HOUFEK_DB_NAZEV", self.db_nazev),
                                ("HOUFEK_DB_UZIVATEL", uzivatel)) if not h]
        if chybi:
            raise RuntimeError("Chybí konfigurace databáze: " + ", ".join(chybi))
        casti = [
            f"DRIVER={_odbc(self.db_ovladac, vzdy=True)}",
            f"SERVER={_odbc(self.db_server)}",
            f"DATABASE={_odbc(self.db_nazev)}",
            f"UID={_odbc(uzivatel)}",
            f"PWD={_odbc(heslo, vzdy=True)}",
            f"Encrypt={'yes' if self.db_sifrovat else 'no'}",
            f"TrustServerCertificate={'yes' if self.db_duverovat_certifikatu else 'no'}",
            "APP=HOUFEK Sklad",
        ]
        return ";".join(casti) + ";"

    def pripojovaci_retezec(self) -> str:
        """ODBC připojovací řetězec aplikace (účet v roli app_sklad)."""
        return self._retezec(self.db_uzivatel, self.db_heslo)

    def pripojovaci_retezec_migrace(self) -> str:
        """Připojovací řetězec pro `flask db …` (účet s právy měnit schéma)."""
        if self.db_uzivatel_migrace:
            return self._retezec(self.db_uzivatel_migrace, self.db_heslo_migrace)
        return self.pripojovaci_retezec()
