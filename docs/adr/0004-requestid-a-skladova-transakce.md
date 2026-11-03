# ADR-0004: Ochrana proti dvojímu zápisu – `requestId` a tabulka `SkladovaTransakce`

**Stav:** Přijato (vedoucí projektu, 2. 11. 2026; implementováno ve fázi 0, migrace 002)
**Datum:** 2026-10-26
**Rozhodují:** vedoucí projektu (brána G2)
**Souvisí:** analýza N-14 a doplněk D2 (sekce 10.3); code review CR-04, CR-06, CR-18

## Kontext

Terminály PDA ve skladu běží na Wi-Fi. Výpadky, dvojí klepnutí a timeouty proxy jsou běžné. HTTP nezaručuje doručení právě jednou:
- když požadavek dojde, ale odpověď ne, terminál neví, jestli se výdej zapsal;
- další pokus bez ochrany zapíše výdej podruhé, takže zásoba bude špatně a nikdo si toho nevšimne.

Zadání tuto situaci neřeší (analýza, nález N-14).

## Rozhodnutí

1. **Vstup.** Každý skladový příkaz má vstup `SkladovyVstup` s povinným `requestId` (UUID v4). Generuje ho klient pro jednu **zamýšlenou operaci**.
2. **Hlavička v transakci.** `@transakce("VYDEJ", skladova=True)` v **téže transakci** jako pohyby:
   - založí hlavičku v `dbo.SkladovaTransakce` (`KlientRequestID` UNIQUE);
   - předá `transakceId` operaci a ta ho zapíše do `SkladovyPohyb.TransakceID`;
   - uloží výsledek (`Vysledek`, JSON) spolu s **otiskem** obsahu požadavku (SHA-256 těla bez `requestId`).
3. **Opakovaný požadavek** se stejným `requestId`:

   | Situace | Odpověď |
   |---|---|
   | stejný uživatel, operace i obsah | uložený výsledek se stejným `transakceId`, nic se nezapíše |
   | jiný obsah, uživatel nebo operace | `VALIDATION_ERROR` „Tento requestId už byl použit pro jiný požadavek.“ |
   | první požadavek ještě běží (čekání na zámek hlavičky vypršelo) | `REQUEST_IN_PROGRESS` (409) |
   | první požadavek skončil chybou | nic se nezapsalo (rollback i hlavičky), další pokus proběhne normálně |

4. **Pravidlo pro každého klienta** (web, PDA, budoucí nativní aplikace). Nový `requestId` jen po **jistém** výsledku:

   | Výsledek | Jistý? | Další pokus |
   |---|---|---|
   | obálka s HTTP 200 | ano | nová operace = nový `requestId` |
   | obálka s HTTP 4xx kromě `REQUEST_IN_PROGRESS` | ano (nic se nezapsalo) | nový `requestId` |
   | výpadek sítě, HTTP 500, 502, 503, 504, odpověď bez obálky | **ne** | **stejný** `requestId` |
   | `REQUEST_IN_PROGRESS` | **ne** | **stejný** `requestId` po chvíli |

   HTTP 500 je mezi nejistými, protože chyba mohla nastat až po potvrzení transakce (např. při sestavení odpovědi). Opakování se stejným `requestId` je vždy bezpečné: server buď vrátí uložený výsledek, nebo operaci provede poprvé.

   Implementace pro web je `app/platforma/ui/static/api.js` a testy `tests/js/api.test.mjs`.

## Zvažované možnosti

### Možnost A: `requestId` + hlavička v téže transakci SQL (zvoleno)

| Hledisko | Hodnocení |
|---|---|
| Složitost | Nízká pro ostrovy (jeden parametr dekorátoru), střední v Platformě |
| Náklady | Jedna tabulka, ~1 řádek na skladovou operaci |
| Škálovatelnost | Index na `KlientRequestID`; desítky milionů řádků bez problému |
| Znalost týmu | Vysoká – běžné SQL |

**Pro:** atomické s pohyby: buď je hlavička i pohyb, nebo nic. Funguje přes restart aplikace i víc procesů (P9). `transakceId` spojí všechny pohyby jedné operace.
**Proti:** tabulka roste. Každý klient musí dodržet pravidlo výše.

### Možnost B: hlavička `Idempotency-Key` + oddělené úložiště (Redis, paměť procesu)

| Hledisko | Hodnocení |
|---|---|
| Složitost | Střední – dvě úložiště, konzistence mezi nimi |
| Náklady | Redis = nová infrastruktura pro interní IT |
| Škálovatelnost | Dobrá |
| Znalost týmu | Nízká |

**Pro:** standardní vzor z veřejných API.
**Proti:** zápis klíče a pohybu nejsou atomické: pád mezi nimi zanechá klíč bez pohybu, nebo pohyb bez klíče. Paměť procesu porušuje P9 a nepřežije restart.

### Možnost C: Rozpoznání duplicity podle obsahu („stejný díl, počet a místo do 10 s“)

| Hledisko | Hodnocení |
|---|---|
| Složitost | Střední – pravidla po typech operací |
| Náklady | Žádná infrastruktura |
| Škálovatelnost | Dobrá |
| Znalost týmu | Vysoká |

**Pro:** klient nemusí nic posílat.
**Proti:** dva stejné výdeje po sobě jsou ve skladu běžné, takže pravidlo by odmítalo oprávněné operace. Výpadek delší než okno projde dvakrát.

### Možnost D: Jen zakázat tlačítko během odesílání

| Hledisko | Hodnocení |
|---|---|
| Složitost | Nejnižší |
| Náklady | Žádné |
| Škálovatelnost | – |
| Znalost týmu | Vysoká |

**Pro:** zabrání dvojímu klepnutí.
**Proti:** neřeší výpadek sítě ani timeout, tedy hlavní příčinu. UI ho dělá navíc (`api.js` vypíná tlačítko).

## Rozbor kompromisů

Jen A dává atomičnost se zápisem pohybu bez nové infrastruktury. Cena je tabulka navíc a pravidlo pro klienty. To je napsané jednou v `api.js` a ostrovy ho dostanou zadarmo. Pro ostrovy je mechanismus neviditelný. Stačí dědit vstup ze `SkladovyVstup` a použít `skladova=True`.

## Důsledky

- **Snazší:**
  - terminál smí bezpečně opakovat;
  - podpora dohledá operaci podle `transakceId` (je v obálce i v `SkladovyPohyb`);
  - přehledy můžou seskupit pohyby jedné operace.
- **Těžší:**
  - každý nový klient musí implementovat pravidlo „nový `requestId` jen po jistém výsledku“;
  - nejde poslat dvě různé operace se stejným `requestId` (to je správně).
- **Retence:** řádky se zatím nemažou (`IX_SkladovaTransakce_DatumCas` je připravený pro archivaci). Unikátnost `requestId` tedy platí navždy. Archivaci rozhodnout spolu s archivací `SkladovyPohyb` (TD-14).
- **Přehodnotit:** `SkladovyPohyb.TransakceID` je zatím NULL-able kvůli importu počátečního stavu. Po migraci dat (ostrov H) přepnout na NOT NULL.

## Úkoly

1. [x] `@transakce(skladova=True)`, `SkladovyVstup`, migrace 002, otisk obsahu (CR-06), `REQUEST_IN_PROGRESS` (CR-18), pravidlo v `api.js` (CR-04).
2. [ ] Ostrov E: všechny příkazy (příjem, výdej, přesun, blokace, korekce) přes `skladova=True`.
3. [ ] Integrační test proti SQL Serveru: dva souběžné požadavky se stejným `requestId` (TD-01).
4. [ ] `SkladovyPohyb.TransakceID` NOT NULL po migraci dat (ostrov H).
5. [x] Role `app_sklad`: `DENY DELETE` i na `SkladovaTransakce` (TD-08, migrace 004, 1. 11. 2026).
