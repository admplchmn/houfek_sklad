# ADR-0008: Testovací UI – Jinja šablony a čistý JavaScript

**Stav:** Přijato (požadavek vedoucího projektu: „UI jen pro klikání a kontrolu logiky“)
**Datum:** 2026-10-26
**Rozhodují:** vedoucí projektu

## Kontext

Nejdřív vzniká backend. Frontend slouží jen k **ručnímu proklikání a kontrole logiky**: potřebné vstupy, výstupy a tlačítka, jednoduše a přehledně. Má fungovat:
- na PC;
- v prohlížeči PDA, kde čtečka kódů funguje jako klávesnice (kód + Enter).

Každý ostrov má své obrazovky a programuje je jeho vlastník.

## Rozhodnutí

- **Stránky.** Šablony Jinja vykresluje server. Každý ostrov má svůj blueprint `stranky/` pod `/ui/{prefix}`, společný základ je v `app/platforma/ui`.
- **Sdílený JavaScript:**
  - `api.js` volá API, vykresluje obálku do panelu „Odpověď API“ a dodržuje pravidlo `requestId` (ADR-0004);
  - `sken.js` řídí tok skenování: pole se skenem, Enter, další pole.
- **Bez sestavování.** Žádný build krok ani npm v provozu. Node.js je potřeba jen pro testy `api.js` při vývoji.
- **Žádné soukromé endpointy.** UI volá **stejné veřejné API** jako jakýkoli jiný klient. Co jde naklikat, jde i zavolat ze Swaggeru nebo z testu.
- **Vývojářský panel.** `/ui/vyvoj` nabízí přihlášení bez PINu (jen `HOUFEK_VYVOJ=1`) a libovolné volání API.

## Zvažované možnosti

### Možnost A: Jinja + čistý JavaScript (zvoleno)

| Hledisko | Hodnocení |
|---|---|
| Složitost | Nízká – HTML šablona + pár funkcí |
| Náklady | Žádné nástroje navíc |
| Škálovatelnost | Pro testovací UI dostatečná |
| Znalost týmu | Vysoká |

**Pro:** každý backendový programátor obrazovku napíše za hodinu. Funguje i ve starších prohlížečích PDA. Nic se nesestavuje.
**Proti:** složitější interakce (tabulky s řazením, drag & drop v rozložení úrovně) jsou pracnější. Na produkční UI to nestačí.

### Možnost B: SPA (React / Vue) se sestavováním

| Hledisko | Hodnocení |
|---|---|
| Složitost | Vysoká – build, závislosti npm, správa stavu |
| Náklady | Node.js v nasazení nebo build v CI |
| Škálovatelnost | Nejlepší pro bohaté UI |
| Znalost týmu | Nízká až střední |

**Pro:** bohaté UI, komponenty.
**Proti:** pro testovací UI výrazně přestřelené. Odvádí backendové programátory od backendu.

### Možnost C: HTMX (fragmenty HTML ze serveru)

| Hledisko | Hodnocení |
|---|---|
| Složitost | Nízká až střední |
| Náklady | Jedna knihovna |
| Škálovatelnost | Dobrá |
| Znalost týmu | Nízká |

**Pro:** interaktivita bez psaní JavaScriptu.
**Proti:** potřebuje endpointy vracející HTML, což je druhé API vedle JSON. Tím padá „UI = stejné API jako ostatní klienti“.

### Možnost D: Jen Swagger

| Hledisko | Hodnocení |
|---|---|
| Složitost | Nulová |
| Náklady | Žádné |
| Škálovatelnost | – |
| Znalost týmu | Vysoká |

**Pro:** hotové hned.
**Proti:**
- skladník tak tok výdeje se skenem na PDA neprojde;
- testuje jednotlivá volání, ne scénáře;
- v provozu je Swagger vypnutý (CR-08).

## Rozbor kompromisů

Testovací UI má ověřit backend, ne být produktem. A je nejlevnější cesta, jak dát obsluze skladu do ruky skutečné toky (sken → kontrola → potvrzení) nad skutečným API. B a C dávají lepší UI, které teď nepotřebujeme, za cenu, kterou bychom platili hned.

## Důsledky

- **Snazší:** obrazovka ostrova = šablona + pár volání `api.post(...)`. Panel odpovědi ukazuje přesně obálku, kterou dostane každý klient.
- **Těžší:** produkční UI bude pravděpodobně nový klient nad stejným API. To je záměr, kontrakty ho podrží (P10).
- **Bezpečnost:** text z API se vkládá přes `textContent`, ne `innerHTML` (`api.js`). Šablony Jinja escapují automaticky.
- **Přehodnotit:** po bráně G3 rozhodnout, zda produkční UI vznikne vylepšením tohoto, nebo jako nový klient (otázka pro vedoucího projektu).

## Úkoly

1. [x] Základ UI, `api.js` s pravidlem `requestId` a testy, `sken.js`, vývojářský panel.
2. [ ] Ověřit `sken.js` na skutečném PDA a čtečce (model zatím neznámý, analýza, sekce 15).
3. [ ] Obrazovky ostrovů ve fázi 1 podle `_sablona/stranky`.
