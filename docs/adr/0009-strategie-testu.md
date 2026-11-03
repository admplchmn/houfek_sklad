# ADR-0009: Strategie testů – sqlite pro Platformu, SQL Server pro T-SQL ostrovů

**Stav:** Přijato (vedoucí projektu, 2. 11. 2026)
**Datum:** 2026-10-26
**Rozhodují:** vedoucí projektu
**Upřesňuje:** analýzu, sekce 8.1, řádek „Testy“ (pytest + SQL Server v Dockeru)

## Kontext

- Analýza správně říká, že zámky, souběh a filtrované indexy nejde věrně testovat na SQLite.
- Šest programátorů potřebuje testy, které proběhnou za sekundy před každým odevzdáním.
- Pravidla ostrovů (P1–P4, P6) a kontrakty (P10) musí hlídat stroj, ne lidé.
- SQL Server pro vývoj a testy je zatím na PC vedoucího projektu nebo lokálně u programátora (rozhodnutí 2. 11. 2026). Kontejner SQL Serveru zatím není k dispozici.

## Rozhodnutí

Pět vrstev, všechny za jedním příkazem `python -m nastroje.over_vse`:

| Vrstva | Co testuje | Databáze | Kde |
|---|---|---|---|
| 1. Jednotkové | čisté funkce: `domena.py` a čisté části `rozhrani.py` (`rozloz_kod`, `vejde_se`, `stav_zasoby`, `barva_boxu`…) | žádná | `app/ostrovy/*/testy` |
| 2. Platforma | transakce, `requestId`, převod chyb, obálka, přihlášení, OpenAPI | sqlite (`ATTACH … AS dbo`) | `tests/test_platforma*.py` |
| 3. Integrační | T-SQL ostrovů, migrace, `zamkni_mista`, pohledy, souběh, akceptační scénáře T01–T32 z analýzy | **SQL Server** (`HOUFEK_TEST_DB_*`), bez konfigurace se přeskočí | `tests/integrace` (harness + testy Platformy, TD-01) |
| 4. Pravidla a kontrakty | P1–P4 a P6 z AST a textu SQL, snímek kontraktů jen přidáním | žádná | `tests/test_pravidla_ostrovu.py`, `tests/test_kontrakty.py` |
| 5. JavaScript | pravidlo `requestId` v `api.js` | žádná | `tests/js` (`node --test`) |

- **Testovací framework.** Testy jsou psané v `unittest`, pytest je spouští také (je v `requirements-vyvoj.txt`).
- **Sqlite jen pro dialektově neutrální kód Platformy.** Větve `dialekt == "sqlite"` v Platformě jsou výjimka a každá má komentář. Žádný test ostrova nesmí na sqlite spoléhat u T-SQL.

## Zvažované možnosti

### Možnost A: Kombinace sqlite (Platforma) + SQL Server (T-SQL) (zvoleno)

| Hledisko | Hodnocení |
|---|---|
| Složitost | Střední – dvě prostředí testů |
| Náklady | Testovací databáze na SRVACC01 nebo kontejner v CI |
| Škálovatelnost | Rychlé vrstvy 1, 2, 4 a 5 pro každé odevzdání, vrstva 3 v CI |
| Znalost týmu | Vysoká |

**Pro:** rychlá zpětná vazba (~1,3 s). T-SQL se testuje tam, kde poběží.
**Proti:** riziko, že test projde na sqlite a T-SQL se chová jinak. Proto vrstva 3 hlídá všechno T-SQL a sqlite zůstává jen pro Platformu.

### Možnost B: Všechno proti SQL Serveru (kontejner pro každého vývojáře i CI)

| Hledisko | Hodnocení |
|---|---|
| Složitost | Střední – Docker na každém PC |
| Náklady | Docker Desktop (licence ve firmách nad 250 lidí), výkon PC |
| Škálovatelnost | Pomalejší testy (start kontejneru, migrace) |
| Znalost týmu | Závisí na týmu |

**Pro:** nejvěrnější prostředí.
**Proti:** pomalé pro každé odevzdání. Závislost na Dockeru na stanicích s Windows.

### Možnost C: Náhrada databáze maketami (mock)

| Hledisko | Hodnocení |
|---|---|
| Složitost | Nízká na začátku |
| Náklady | Žádné |
| Škálovatelnost | – |
| Znalost týmu | Vysoká |

**Pro:** rychlé.
**Proti:** netestuje SQL, tedy přesně to, kde vznikají skladové chyby.

## Rozbor kompromisů

A dává rychlé testy pro to, co je v Pythonu, a věrné testy pro to, co je v T-SQL. Cena je disciplína „T-SQL testovat jen proti SQL Serveru“. Až bude k dispozici kontejner SQL Serveru v CI, vrstva 3 poběží automaticky na každý pull request (TD-01, TD-02). Do té doby proti testovací databázi na PC vedoucího projektu nebo lokálně u programátora.

## Důsledky

- **Snazší:** `python -m nastroje.over_vse` před každým odevzdáním. Pravidla ostrovů hlídá test, ne revize.
- **Těžší:** vrstva 3 potřebuje vlastní testovací databázi (`HoufekSklad_TEST`), kterou testy můžou mazat. Nikdy ne vývojovou ani provozní, nikdy ne PowerKey.
- **Přehodnotit:**
  - po zprovoznění CI s kontejnerem SQL Serveru zvážit, zda Platformu netestovat také proti němu a sqlite vypustit;
  - při růstu sady testů zvážit pytest s paralelním během.

## Úkoly

1. [x] Vrstvy 1, 2, 4 a 5; `nastroje/over_vse.py`.
2. [x] Vrstva 3: harness s `HOUFEK_TEST_DB_*` (`tests/integrace/zaklad.py`): pojistka názvu (TEST, nikdy PowerKey), dorovnání schématu migracemi, rollback po každém testu (1. 11. 2026). Testy ostrovů C a E přibudou s jejich repozitáři (TD-01).
2a. [x] Statická kontrola migrací bez SQL Serveru (`tests/test_migrace.py`): shoda `pohledy.sql` s migrací, pořadí pohledů, existence sloupců.
3. [ ] Testovací databáze `HoufekSklad_TEST` na PC vedoucího projektu nebo lokálně (SQL Server Express nebo Developer).
3a. [ ] Vzorová data a izolace pro integrační testy služeb: v testovací databázi stejný svět jako v `ukazky.py`, každý test začíná z čistých dat (P1, krok 0 v [rozdělení práce](../rozdeleni-prace.md)).
4. [ ] CI: vrstvy 1, 2, 4 a 5 na každý pull request, vrstva 3 po zprovoznění databáze (TD-02).
