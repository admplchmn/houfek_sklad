# ADR-0006: Pohledy `v_*` jako čtecí kontrakt mezi ostrovy

**Stav:** Přijato (součást dokumentu Ostrovy, pravidla P1, P2 a P10)
**Datum:** 2026-10-26
**Rozhodují:** vedoucí projektu

## Kontext

Ostrovy potřebují číst data ostatních:
- G Přehledy čtou všechno;
- E Sklad potřebuje místa ze C a díly z D;
- C a D se před deaktivací ptají, jestli místo nebo díl nemá zásobu v E.

Možnosti, jak číst cizí data, mají každá svou cenu:
- čtení cizích tabulek přímo váže ostrov na vnitřní schéma jiného;
- čtení výhradně přes Python funkce rozhraní (`rozhrani.py`) vede u přehledů k N+1 dotazům a k duplicitnímu SQL.

## Rozhodnutí

- **Publikace pohledů.** Vlastník publikuje pohledy `v_*` ve svém `pohledy.sql` a deklaruje je v `OSTROV.pohledy`:
  - B: `v_Uzivatel`, `v_Terminal`;
  - C: `v_Misto`, `v_VelikostPozice`;
  - D: `v_Dil`;
  - E: `v_ObsahPozice`, `v_ZasobaDilu`, `v_PohybDetail`.
- **Čtení (P2).** Cizí ostrov smí z dat jiného číst **jen** `SELECT … FROM dbo.v_*`, nikdy tabulku.
- **Zápis (P1).** Zápis jde vždy jen přes `rozhrani.py` vlastníka.
- **Sloupce jsou kontrakt (P10).** Po zmrazení se jen přidávají. Přejmenování nebo odebrání = nový pohled a přechodné období.
- **Výjimka ze směru závislostí.** C a D čtou pohled `v_ObsahPozice` ostrova E. Jde jen o čtení SQL, bez importu Pythonu, a test pravidel ji zná.
- **Kontrola.** `tests/test_pravidla_ostrovu.py` kontroluje text SQL. `JOIN/FROM dbo.X` z cizího ostrova je chyba, pokud `X` nezačíná `v_`.

## Zvažované možnosti

### Možnost A: Pohledy `v_*` vlastníka (zvoleno)

| Hledisko | Hodnocení |
|---|---|
| Složitost | Nízká – SQL pohled + deklarace |
| Náklady | Pohledy je potřeba udržovat v migracích |
| Škálovatelnost | Množinové dotazy a spojení v SQL, optimalizátor vidí celý dotaz |
| Znalost týmu | Vysoká |

**Pro:** přehledy jsou jeden dotaz se spojeními. Vlastník může měnit tabulky, pokud drží sloupce pohledu. Hranice je strojově kontrolovatelná.
**Proti:** pohledy závisí na pohledech jiných ostrovů (`v_ZasobaDilu` čte `v_Misto`), takže pořadí v migraci 003 musí odpovídat závislostem. Změna pohledu potřebuje schválení P1.

### Možnost B: Jen funkce `rozhrani.py`

| Hledisko | Hodnocení |
|---|---|
| Složitost | Střední – DTO pro každé čtení |
| Náklady | Hodně kódu pro přehledy |
| Škálovatelnost | Špatná pro přehledy (N+1 nebo velké dávky do paměti) |
| Znalost týmu | Vysoká |

**Pro:** vše v Pythonu, typované.
**Proti:** monitoring regálu by volal desítky funkcí nebo tahal tisíce řádků do paměti a spojoval je v Pythonu.

### Možnost C: Oddělený čtecí model (CQRS, replika, sklad dat)

| Hledisko | Hodnocení |
|---|---|
| Složitost | Vysoká |
| Náklady | Druhé úložiště, synchronizace |
| Škálovatelnost | Nejlepší |
| Znalost týmu | Nízká |

**Pro:** čtení zcela oddělené od zápisu.
**Proti:** pro tuto zátěž zbytečné. Zpoždění dat by mátlo obsluhu u terminálu.

### Možnost D: Přímé čtení cizích tabulek

| Hledisko | Hodnocení |
|---|---|
| Složitost | Nejnižší dnes |
| Náklady | Nejvyšší později |
| Škálovatelnost | Stejná jako A |
| Znalost týmu | Vysoká |

**Pro:** nic se nepíše navíc.
**Proti:** každá změna tabulky rozbije cizí ostrovy bez varování. Vlastnictví dat se rozpadne.

## Rozbor kompromisů

A má výkon, který B nemá, a bezpečnost změn, kterou D nemá. Cena (údržba pohledů, pořadí v migraci) je malá a nese ji vlastník za svá data. C odkládáme. Pohledy jsou přesně místo, kde by se čtecí model později napojil.

## Důsledky

- **Snazší:** přehledy, karty dílů a monitoring jako jeden dotaz. Vlastník smí refaktorovat své tabulky.
- **Těžší:**
  - změna sloupce pohledu = koordinace s čtenáři (seznam v docstringu `rozhrani.py` čtenáře, např. `prehledy/rozhrani.py`);
  - dynamické SQL s názvem tabulky v proměnné by obešlo kontrolu, proto je zakázané (ADR-0002).
- **Přehodnotit:** pokud přehledy začnou zpomalovat terminály i s RCSI, převést nejtěžší pohledy na indexované pohledy nebo čtecí repliku.

## Úkoly

1. [x] Návrhy pohledů v `pohledy.sql` ostrovů B, C, D, E; test pravidla P2.
2. [x] `003_pohledy_ostrovu.sql` v pořadí závislostí C → D → B → E (1. 11. 2026; pořadí a sloupce hlídá `tests/test_migrace.py`).
3. [ ] Ověřit pohledy proti SQL Serveru a plánům dotazů (TD-01).
4. [ ] Zmrazení sloupců pohledů na bráně K1 (P10); potom změna pohledu = nová migrace s `CREATE OR ALTER VIEW`.
