# ADR-0011: Kontrakty – Pydantic modely a vlastní generátor OpenAPI

**Stav:** Přijato (vedoucí projektu, 2. 11. 2026)
**Datum:** 2026-10-26
**Rozhodují:** vedoucí projektu
**Mění:** analýzu, sekce 8.1, řádek „Dokumentace API“ (flask-smorest); code review CR-11, CR-14, CR-16

## Kontext

Konvence API z dokumentu Ostrovy:
- JSON v camelCase, Python v snake_case;
- jednotná obálka `{success, code, message, data, transakceId, varovani[]}`;
- časy ISO 8601 s posunem Europe/Prague;
- milimetry jako čísla;
- neznámé pole = chyba.

Kontrakty ostrovů musí být vidět **dřív**, než je implementace hotová, protože kostry vracejí vzorová data. Po zmrazení se smí jen přidávat (P10) a hlídat to má CI. Flask je daný stack.

## Rozhodnutí

- **Modely.** Vstupy, výstupy a parametry jsou modely Pydantic 2 se společnými základy v `app/platforma/kontrakty.py`:
  - `Vstup`, `SkladovyVstup`, `Parametry` (GET filtry, bez `requestId`) a `Vystup`;
  - typy `Cas`, `Mm` a `Ks`.
- **Dokumentace endpointu.** `@dokumentuj(vstup=…, vystup=…, parametry=…)` připojí modely k endpointu.
- **Generátor.** Vlastní generátor (`app/platforma/openapi.py`, ~110 řádků) sestaví OpenAPI 3.1 včetně obálky. Při kolizi jmen modelů selže (CR-11). Query parametry mají skutečné typy (CR-16).
- **Snímek kontraktů.** `kontrakty/openapi.json` a `kontrakty/rozhrani.json` jsou v repozitáři. `python -m nastroje.kontrakty over` hlásí nekompatibilní změny:
  - odebranou cestu, parametr nebo pole;
  - nový povinný parametr nebo nové povinné pole vstupu;
  - změnu podpisu funkce rozhraní.
- **DTO rozhraní.** Mezi ostrovy jdou neměnné dataclassy (P6), ne modely Pydantic.

## Zvažované možnosti

### Možnost A: Pydantic + vlastní generátor (zvoleno)

| Hledisko | Hodnocení |
|---|---|
| Složitost | Nízká až střední – generátor je malý a testovaný |
| Náklady | Údržba generátoru vlastníkem Platformy |
| Škálovatelnost | Stovky endpointů bez problému |
| Znalost týmu | Vysoká – Pydantic je běžný |

**Pro:**
- validace a schéma z jednoho modelu, camelCase přes `alias_generator`;
- obálka přesně podle konvence;
- kontrola P10 nad vlastním výstupem.

**Proti:** vlastní kód místo knihovny. Pokrývá jen to, co používáme (žádné callbacks ani security schemes).

### Možnost B: flask-smorest + marshmallow (původní návrh analýzy)

| Hledisko | Hodnocení |
|---|---|
| Složitost | Střední – marshmallow schémata vedle Pydantic DTO |
| Náklady | Dvě knihovny pro totéž |
| Škálovatelnost | Dobrá |
| Znalost týmu | Střední |

**Pro:** hotová integrace Swaggeru, stránkování, ETag.
**Proti:**
- marshmallow a Pydantic znamenají dvě definice téhož;
- obálku `{success, code, …}` a camelCase je nutné ohýbat;
- vlastní chybové kódy jdou proti jeho chybovým odpovědím.

### Možnost C: APIFlask

| Hledisko | Hodnocení |
|---|---|
| Složitost | Střední |
| Náklady | Jiná třída aplikace (`APIFlask`) |
| Škálovatelnost | Dobrá |
| Znalost týmu | Nízká |

**Pro:** OpenAPI z dekorátorů.
**Proti:** výchozí je marshmallow, Pydantic přes adaptér. Mění základ aplikace, který sdílí všechny ostrovy.

### Možnost D: FastAPI místo Flasku

| Hledisko | Hodnocení |
|---|---|
| Složitost | Střední – jiný framework, async model |
| Náklady | Změna daného stacku |
| Škálovatelnost | Dobrá |
| Znalost týmu | Nízká až střední |

**Pro:** Pydantic a OpenAPI vestavěné.
**Proti:** Flask je daný. pyodbc je synchronní, takže async nic nepřinese. Šablony a session by se řešily znovu.

## Rozbor kompromisů

Generátor o ~110 řádcích je menší závazek než druhá knihovna schémat, která by bojovala s naší obálkou. Rozhodlo, že kontrakt je pro šest souběžně pracujících lidí hlavní spojovací prvek. Musí přesně odpovídat konvenci a jeho kontrola musí být spolehlivá. Obojí máme pod kontrolou jen s vlastním výstupem.

## Důsledky

- **Snazší:** endpoint = model vstupu + model výstupu + `@dokumentuj`. Kontrakt je hned v `/api/openapi.json` i se vzorovými daty kostry.
- **Těžší:**
  - jména modelů musí být jedinečná v celé aplikaci; při kolizi dejte modelu předponu ostrova, např. `SkladPohybDetail`;
  - generátor udržuje vlastník Platformy.
- **Přehodnotit:** kdyby bylo potřeba generovat klienty (např. nativní aplikaci pro PDA), ověřit výstup generátorem klientů. OpenAPI 3.1 podporují všechny běžné.

## Úkoly

1. [x] Základy kontraktů, generátor, snímek a kontrola P10 včetně parametrů a povinných polí (CR-16).
2. [ ] Zmrazení kontraktů ostrovů na bráně K1 (P10). Snímek všech ostrovů je uložený jako kandidát (2. 11. 2026); `kontrakty uloz` jen se souhlasem P1, po K1 už jen přidání.
