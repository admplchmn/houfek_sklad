"""Testovací databáze jedním příkazem: založí ji, když chybí, a provede migrace (docs/vyvoj.md 1.1).

    docker compose up -d
    python -m nastroje.testovaci_db

Konfigurace jsou HOUFEK_TEST_DB_* v .env. Pojistky (jen databáze s TEST v názvu, nikdy PowerKey) hlídá
harness integračních testů tests/integrace/zaklad.py, který tento příkaz používá.
"""
from __future__ import annotations

import sys

from tests.integrace import zaklad


def main() -> int:
    konf = zaklad.KONFIGURACE
    if konf is None:
        print("V .env chybí HOUFEK_TEST_DB_SERVER nebo HOUFEK_TEST_DB_NAZEV (docs/vyvoj.md 1.1).")
        return 1
    zaklad.aplikace()
    print(f"Testovací databáze {konf.db_nazev} na {konf.db_server} je připravená.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
