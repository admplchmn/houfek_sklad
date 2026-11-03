# Architektonická rozhodnutí (ADR)

Každé rozhodnutí, které by nový programátor nedokázal odvodit z kódu, má jeden krátký záznam. Záznam říká:
- proč to tak je,
- jaké byly možnosti,
- co z toho plyne.

Kód na záznamy odkazuje v docstringu (`Rozhodnutí: docs/adr/0004`).

| ADR | Rozhodnutí | Stav | Kdo potvrzuje |
|---|---|---|---|
| [0001](0001-modularni-monolit-a-ostrovy.md) | Modulární monolit rozdělený na 8 ostrovů | Přijato | vedoucí projektu |
| [0002](0002-pyodbc-a-rucni-tsql.md) | Databáze přes pyodbc a ruční T-SQL, bez ORM | Přijato | vedoucí projektu |
| [0003](0003-ciselne-sql-migrace.md) | Migrace jako číslované T-SQL skripty, samostatný účet | Přijato | vedoucí projektu, DBA |
| [0004](0004-requestid-a-skladova-transakce.md) | Ochrana proti dvojímu zápisu: `requestId` + `SkladovaTransakce` | Přijato | vedoucí projektu (brána G2) |
| [0005](0005-zamky-pozic-a-rcsi.md) | Souběh: protokol zámků pozic + READ_COMMITTED_SNAPSHOT | Přijato | vedoucí projektu, DBA |
| [0006](0006-pohledy-jako-cteci-kontrakt.md) | Pohledy `v_*` jako čtecí kontrakt mezi ostrovy | Přijato | vedoucí projektu |
| [0007](0007-session-cookie-a-overeni.md) | Přihlášení: podepsaná cookie + ověření při každém požadavku | Přijato | vedoucí projektu, IT bezpečnost |
| [0008](0008-ui-jinja-a-cisty-js.md) | Testovací UI: Jinja + čistý JavaScript | Přijato | vedoucí projektu |
| [0009](0009-strategie-testu.md) | Testy: sqlite pro Platformu, SQL Server pro T-SQL | Přijato | vedoucí projektu |
| [0010](0010-fullboxklic-ulozeny.md) | `FullBoxKlic` jako uložený sloupec (Q-03) | Přijato | vlastník procesu skladu |
| [0011](0011-pydantic-a-vlastni-openapi.md) | Kontrakty: Pydantic + vlastní generátor OpenAPI | Přijato | vedoucí projektu |
| [0012](0012-casove-udaje-v-utc.md) | Časové údaje v databázi v UTC, najevo pražský čas | Navrženo | vedoucí projektu, vlastník procesu, IT |

**Stavy:**
- **Navrženo:** implementováno ve fázi 0, čeká na potvrzení.
- **Přijato:** potvrzeno.
- **Nahrazeno:** platí novější ADR, na který záznam odkazuje.
- **Zastaralé:** už neplatí.

ADR 0002, 0003, 0007, 0009 a 0011 se odchylují od tabulky v sekci 8.1 analýzy, která navrhovala SQLAlchemy, Alembic a flask-smorest. Analýza na ně odkazuje.

## Nový záznam

1. Zkopírujte [`sablona.md`](sablona.md) jako `NNNN-kratky-nazev.md`. Číslo je o jedno vyšší než poslední a nikdy se nepoužije znovu.
2. Stav **Navrženo**. Záznam jde do pull requestu spolu s kódem, který rozhodnutí zavádí.
3. Přijatý záznam se už nepřepisuje. Změna rozhodnutí = nový záznam a starý dostane stav „Nahrazeno ADR-NNNN“.

Psát krátce: kontext, rozhodnutí, 2–4 možnosti s tabulkou, důsledky. Co je v kódu nebo v jiném dokumentu, se odkazuje, neopisuje.
