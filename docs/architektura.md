# Architektura – HOUFEK Sklad

**Stav k:** 2. 11. 2026 (fáze 0: kontrakty ostrovů B–G hotové, kandidát na bránu K1) · **Čte:** vedoucí projektu, programátoři ostrovů, DBA a IT provoz

Celá aplikace stojí na pěti volbách:
- **Jedno nasazení.** Jedna aplikace Flask, rozdělená na 8 ostrovů, běží za IIS nad jednou databází SQL Server.
- **Jedna transakce na příkaz.** Skladový příkaz běží synchronně v jedné transakci, se zámky pozic a ochranou `requestId` proti dvojímu zápisu.
- **Bez mezivrstev.** Žádná cache, fronty ani služby mezi ostrovy.
- **Výkon.** Pro odhadovanou zátěž (desítky terminálů, jednotky požadavků za sekundu) stačí jeden server s velkou rezervou.
- **Hlavní riziko.** Nejde o výkon, ale o **souběh na stejném místě** a **nespolehlivou Wi-Fi**. Na ty míří návrh.

Podrobnosti rozhodnutí jsou v [ADR](adr/README.md). Pravidla mezi ostrovy (P1–P11) a konvence API jsou v dokumentu „HOUFEK – Ostrovy aplikace a konvence API“. Doména, datový model a otázky Q-xx jsou v dokumentu „HOUFEK – Skladový systém: analýza zadání a osnova aplikace“. Zde se neopakují.

---

## 1. Kontext a cíle

**Co systém dělá:**
- eviduje strukturu skladu (pracoviště → regál → úroveň → pozice → box → vnitřní pozice boxu) a díly;
- vede, co kde leží, a provádí skladové operace: příjem DYN/STAT, výdej, přesun, blokace, korekce;
- podporuje inventury;
- ukazuje přehledy (sken, karta dílu, SVG rozložení úrovně, monitoring);
- jednorázově převezme data z dnešního souboru XLSM.

**Kdo ho používá:**
- skladníci na sdílených PDA se čtečkou kódů,
- mistři a kancelář na PC,
- správce.

**Cíle, podle kterých se rozhoduje (v tomto pořadí):**
1. **Zásoba je vždy správně:** žádný dvojí zápis, žádná ztracená změna, historie se nedá přepsat.
2. **Sken je rychlý a srozumitelný:** odpověď do zlomku sekundy, chyba jako věta pro skladníka.
3. **4–6 programátorů pracuje souběžně** bez vzájemného rozbíjení kódu.
4. **Provoz zvládne interní IT:** Windows Server, IIS, SQL Server, bez kontejnerů a orchestrace.

**Mimo rozsah fáze 0–1:**
- napojení na PowerKey: otevřená otázka, databáze PowerKey se nepoužívá;
- Vault: jen připravený sloupec `Dil.VaultVykresURL`;
- produkční UI: zatím jen testovací UI, ADR-0008.

## 2. Požadavky

### 2.1 Funkční – kdo co vlastní

| Ostrov | Odpovídá za | Klíčové operace |
|---|---|---|
| A Platforma | transakce, `requestId`, chyby, obálka, přihlášení, audit, migrace, UI základ | – |
| B Identita | uživatelé, role, oprávnění, terminály | přihlášení PINem, správa uživatelů |
| C Struktura | pracoviště až vnitřní pozice, rozměry, štítky, blokace | založení a přesun boxu, rekonfigurace, zámky míst (P8) |
| D Díly | kmen dílů a číselníky, velikost pozice dílu | založení, úprava, deaktivace dílu |
| E Sklad | obsah pozic, skladové pohyby, statická místa, upozornění zásoby | příjem, výdej, přesun, korekce |
| F Inventura | inventury a jejich položky | sčítání, dokončení s korekcemi |
| G Přehledy | jen čtení: sken, hledání, karta dílu, rozložení, monitoring | – |
| H Migrace | převod XLSM (CLI) | načtení, report, import |

### 2.2 Nefunkční

| Požadavek | Cíl | Jak ho návrh plní | Potvrdit |
|---|---|---|---|
| Konzistence zásob | 0 dvojích zápisů, 0 ztracených změn | `requestId` + hlavička v téže transakci (ADR-0004), zámky pozic (ADR-0005), `XACT_ABORT` | – |
| Neměnná historie | pohyb ani audit nejde přepsat ani smazat | `DENY UPDATE, DELETE` pro roli `app_sklad`, oprava = protipohyb | – |
| Odezva skenu | p95 < 300 ms na terminálu, < 100 ms na serveru | dotazy podle indexů, žádné volání mezi službami | změřit na Wi-Fi skladu |
| Dostupnost | během směn, cíl 99,5 % v pracovní době | jeden server, restart služby, monitoring `/zdravi` | časy směn, okno údržby |
| Ztráta dat (RPO) | ≤ 15 min | zálohy logu SQL Serveru (DBA) | DBA |
| Obnova (RTO) | ≤ 4 h | obnova DB + reinstalace aplikace ([provoz.md](provoz.md)) | DBA, IT |
| Bezpečnost | osobní přihlášení, oprávnění na akce, audit kmenových dat | sekce 4.6 | IT bezpečnost |
| Provozovatelnost | spravuje interní IT | Windows + IIS + waitress, jedna databáze, migrace jedním příkazem | IT |
| Souběžný vývoj | 4–6 lidí bez konfliktů | ostrovy, pravidla hlídaná testem, kontrakty jen přidáním (ADR-0001, ADR-0011) | – |

### 2.3 Omezení

- **Stack je daný:**
  - Python 3.12+, Flask 3, Microsoft SQL Server na **SRVACC01**;
  - šifrování spojení je povinné, server má interní certifikát (`TrustServerCertificate`, TD-13);
  - aplikace má **vlastní databázi**, databáze **PowerKey** se nepoužívá.
- **Prostředí:**
  - server aplikace Windows s IIS (předpoklad z analýzy 8.1, potvrdit);
  - PDA s prohlížečem, čtečka funguje jako klávesnice (model zatím neznámý, analýza sekce 15).
- **Tým:** 4–6 programátorů, vedoucí projektu, žádný samostatný DevOps.

### 2.4 Odhad zátěže (předpoklady k potvrzení)

| Veličina | Předpoklad | Odvození |
|---|---|---|
| Současně aktivní PDA | 10–20 | potvrdit s provozem skladu |
| Současně aktivní PC | 5–10 | |
| Skladové operace (zápisy) | 2 000–5 000 za den | 2 směny |
| Zápisy ve špičce | ~2 operace/s | průměr 5 000 / 16 h ≈ 0,09/s; začátek směny ~20× průměr |
| Čtení (sken, přehledy) | ~10 požadavků/s ve špičce | ~3–5 čtení na jednu operaci |
| Řádky `SkladovyPohyb` | 0,75–1,9 mil. za rok | ~1,5 řádku na operaci, 250 pracovních dní |
| Růst databáze | ~1–2 GB za rok | pohyby ~0,5 GB, `SkladovaTransakce` s výsledkem (~1 kB) 0,6–1,5 GB |

**Závěr:**
- Propustnost není problém. Waitress s 16 vlákny a dotazy po 20–50 ms zvládne stovky požadavků za sekundu, tedy desetinásobek špičky.
- Úzké místo je **souběh na oblíbeném boxu** (deset terminálů vydává ze stejného místa). To řeší pořadí zámků a srozumitelné `CONCURRENT_CHANGE` do 5 s.

## 3. Návrh na vysoké úrovni

### 3.1 Komponenty a nasazení

```
  PDA (prohlížeč, čtečka = klávesnice)         PC (prohlížeč)
              │ HTTPS, Wi-Fi skladu                │ HTTPS
              └─────────────────┬──────────────────┘
                                ▼
      IIS – TLS; HttpPlatformHandler spouští a hlídá proces waitress
                                │ http://127.0.0.1:<port od IIS>
                                ▼
         waitress (16 vláken) ─ Flask aplikace „HOUFEK Sklad“
  ┌────────────────────────────────────────────────────────────────┐
  │ A Platforma: http (obálka, chyby) · auth · transakce · db      │
  │              audit · openapi · migrace · ui (api.js, sken.js)  │
  ├────────────────────────────────────────────────────────────────┤
  │ B Identita · C Struktura · D Díly · E Sklad · F Inventura      │
  │ G Přehledy · H Migrace (jen CLI)                               │
  └────────────────────────────────────────────────────────────────┘
                                │ pyodbc, ODBC Driver 18, Encrypt=yes
                                ▼
          SQL Server SRVACC01 · databáze HoufekSklad (RCSI zapnuté)
          účty: aplikace (role app_sklad) · migrace (db_owner)
```

- **Jedna databáze, jedno schéma `dbo`:**
  - 30 tabulek: 28 ze schématu G1 + `SkladovaTransakce` + `MigraceSchema`;
  - každá patří právě jednomu ostrovu (`OSTROV.tabulky`, kontroluje to `flask platforma kontrola`);
  - ostrov H bude mít pracovní tabulky ve schématu `stg`.
- **Bez stavu v paměti (P9).** Session je v podepsané cookie. Lze pustit víc procesů nebo druhý server bez změny kódu.

### 3.2 Závislosti mezi ostrovy

```
 ┌─────────────────────────────────────────────────────────────────────────┐
 │ F Inventura → C, D, E    G Přehledy → B, C, D, E    H Migrace → C, D, E │
 └─────────────────────────────────────────────────────────────────────────┘
                                     │ volá jen vrstvy pod sebou
 ┌─────────────────────────────────────────────────────────────────────────┐
 │                            E Sklad → C, D                               │
 └─────────────────────────────────────────────────────────────────────────┘
                                     │
 ┌─────────────────────────────────────────────────────────────────────────┐
 │        B Identita            C Struktura              D Díly            │
 └─────────────────────────────────────────────────────────────────────────┘
                                     │
 ┌─────────────────────────────────────────────────────────────────────────┐
 │                  A Platforma (používají ji všichni)                     │
 └─────────────────────────────────────────────────────────────────────────┘
```

- „X → Y“ = X smí importovat `rozhrani` ostrova Y a číst jeho pohledy `v_*`.
- Jediný opačný směr: C a D **čtou** pohledy ostrova E (`v_ObsahPozice`, C i `v_StatickeMisto`) – prázdný box před strukturální změnou, díl bez zásoby před vyřazením –, bez importu Pythonu.
- Mapu hlídá `ZAVISLOSTI` v `tests/test_pravidla_ostrovu.py`.

### 3.3 Tok skladového příkazu (výdej)

```
PDA            api.js              Flask / Platforma              E Sklad (služba)         SQL Server
 │ sken+Enter    │                        │                              │                     │
 │──────────────►│ POST /api/sklad/vydej  │                              │                     │
 │               │  {requestId, …}        │                              │                     │
 │               │───────────────────────►│ auth: kontext() + ověření B  │                     │
 │               │                        │ nacti_vstup(VydejVstup)      │                     │
 │               │                        │ @transakce("VYDEJ", skladova=True)                 │
 │               │                        │──── BEGIN ─────────────────────────────────────────►│
 │               │                        │ SkladovaTransakce: hledá requestId ────────────────►│
 │               │                        │ (nalezen → uložený výsledek, konec)                │
 │               │                        │ INSERT hlavička (UNIQUE requestId) ────────────────►│
 │               │                        │─────────────────────────────►│ zamkni_mista (C, P8)►│ UPDLOCK, HOLDLOCK
 │               │                        │                              │ čte obsah ─────────►│
 │               │                        │                              │ kontroly (kusy, blokace)
 │               │                        │                              │ zapíše pohyb + obsah►│
 │               │                        │◄──────── výsledek ───────────│                     │
 │               │                        │ uloží výsledek + otisk do hlavičky ────────────────►│
 │               │                        │──── COMMIT ────────────────────────────────────────►│
 │               │◄── obálka OK, transakceId ─│                          │                     │
 │◄── panel ─────│                        │                              │                     │
```

**Chybové větve:**
- obchodní chyba (`INSUFFICIENT_STOCK`, `POSITION_BLOCKED`) → rollback, obálka 4xx, nic se nezapsalo;
- deadlock → Platforma zopakuje celý blok;
- čekání na zámek > 5 s → `CONCURRENT_CHANGE`;
- výpadek odpovědi → `api.js` pošle znovu se **stejným** `requestId` (ADR-0004).

### 3.4 Kontrakty API

- **Cesty:** REST nad JSON pod `/api/{prefix}/…`:
  - čtení `GET` s filtry v query (camelCase, model `Parametry`);
  - příkazy `POST` (akce jako podzdroj, např. `/boxy/{id}/presun`);
  - úpravy kmenových dat `PATCH`;
  - `DELETE` se nepoužívá, kmenová data se deaktivují.
- **Obálka každé odpovědi:** `{success, code, message, data, transakceId, varovani[]}`.
  - `code` je technický kód (ASCII, VELKÁ_PÍSMENA),
  - `message` je česká věta pro uživatele.
- **Stránkování:** `strana`, `velikost` ≤ 200 → `Strana[T] {polozky, strana, velikost, celkem}`.
- **Kontrakt je v kódu:**
  - `GET /api/openapi.json` (OpenAPI 3.1);
  - snímek `kontrakty/openapi.json` a `kontrakty/rozhrani.json`;
  - Swagger `/api/docs` jen ve vývoji.
- **Úplné konvence:** dokument Ostrovy, sekce 4.

## 4. Hlubší pohled

### 4.1 Datový model

- **Struktura (C):** `Firma` → `Pracoviste` → `Regal` → `Uroven` → `Pozice` → `Box` (1:1 s pozicí mezi aktivními) → `VnitrniPoziceBoxu` (podle `CleneniBoxu`, C1–C7).
  - Rozměry jsou v `DECIMAL(10,2)` mm.
  - `Box.FullBoxKlic` je uložená adresa (ADR-0010).
- **Díly (D):** `Dil` + číselníky `Material`, `TloustkaMaterialu`, `PrvniVyrobniOperace`. Velikost pozice dílu je `VelikostPozice` (C).
- **Zásoba (E):**
  - `ObsahPozice` = co a kolik leží na vnitřní pozici;
  - `SkladovyPohyb` = neměnná historie s `TransakceID` → `SkladovaTransakce`;
  - dále `StatickeUmisteniDilu` a `UpozorneniZasoby`.
- **Inventura (F):** `Inventura`, `InventuraPolozka`.
- **Platforma (A):** `AuditZmen` (změny kmenových dat), `SkladovaTransakce`, `MigraceSchema`.
- **Pravidla, která nejde vynutit omezením** (např. `FullBoxKlic` odpovídá adrese, počet vnitřních pozic odpovídá členění), hlídá pohled `v_KontrolaIntegrity`. Spouští se v noci, `GET /api/system/kontrola-integrity`.

Úplné schéma: `sql/migrace/001_schema_g1.sql` (Δ1–Δ16 proti zadání). Vysvětlení: analýza, sekce 9–10.

### 4.2 Čtení a zápis mezi ostrovy

| Potřeba | Cesta | Pravidlo |
|---|---|---|
| zapsat do cizích dat | funkce `rozhrani.py` vlastníka, v transakci volajícího (předá `spoj`) | P1, P3, P5 |
| přečíst jednotlivý záznam | funkce `rozhrani.py` (DTO, neměnné) | P3, P6 |
| přečíst množinu (přehledy) | `SELECT … FROM dbo.v_*` vlastníka | P2, ADR-0006 |
| zamknout místo | `struktura.rozhrani.zamkni_mista` | P8, ADR-0005 |

### 4.3 Cache

**Žádná, záměrně:**
- data skladu musí být čerstvá (co terminál vidí, to na místě leží);
- sdílená paměť mezi vlákny a procesy je zakázaná (P9);
- všechny odpovědi `/api` mají `Cache-Control: no-store`, aby je nedržel ani prohlížeč sdíleného PDA, ani proxy.

Statické soubory (CSS, JS) může cachovat IIS.

**Přehodnotit,** až by přehledy zatěžovaly databázi. Řešit v databázi (indexovaný pohled, předpočítaná tabulka), ne v paměti aplikace.

### 4.4 Fronty a události

**Žádné.**
- Každý příkaz je synchronní a jeho vedlejší účinky jsou ve **stejné transakci**: pohyb, obsah, upozornění zásoby, hlavička. Nic se nedoručuje později a nic nemůže „viset“.
- Dávkové úlohy jsou příkazy CLI, které spouští Plánovač úloh Windows:
  - noční kontrola integrity,
  - jednorázová migrace XLSM.

**Přehodnotit:** tisk štítků. Dnes PDF generuje synchronně `reportlab`. Kdyby tiskárny potřebovaly frontu, přidat tabulku úloh v DB a jednoho pracovníka (worker), ne broker zpráv.

### 4.5 Chyby, časové limity a opakování

| Kód | HTTP | Kdy | Zapsalo se? | Klient |
|---|---|---|---|---|
| `OK` | 200 | hotovo | ano | nový `requestId` pro další operaci |
| `VALIDATION_ERROR` | 400 | špatný vstup, `requestId` použitý pro jiný požadavek | ne | opravit vstup |
| `NOT_AUTHENTICATED` | 401 | nepřihlášen, přihlášení zrušeno (ADR-0007) | ne | přihlásit |
| `NO_PERMISSION` | 403 | chybí oprávnění | ne | – |
| `NOT_FOUND` | 404 | objekt neexistuje nebo není aktivní | ne | – |
| `ALREADY_EXISTS`, `POSITION_BLOCKED`, `NOT_EMPTY` + kódy ostrovů | 409 | obchodní pravidlo | ne | podle zprávy |
| `CONCURRENT_CHANGE` | 409 | zámek místa > 5 s, opakovaný deadlock, souběžná změna | ne | načíst znovu, zkusit znovu (nový `requestId`) |
| `REQUEST_IN_PROGRESS` | 409 | stejný `requestId` se právě zpracovává | zatím nevíme | **stejný** `requestId` po chvíli |
| `PAYLOAD_TOO_LARGE` | 413 | tělo > 1 MB | ne | – |
| `INTERNAL_ERROR` | 500 | chyba v kódu (zapsaná v logu s ID požadavku) | nevíme | **stejný** `requestId` |
| `DATABASE_UNAVAILABLE` | 503 | DB nedostupná nebo překročen limit dotazu | nevíme | **stejný** `requestId` po chvíli |

**Opakování na serveru:** jen deadlock (1205), nejvýše 2× s náhodným odstupem 50–150 ms × pokus. Nic jiného se samo neopakuje.

**Časové limity:**
- přihlášení k DB 15 s;
- dotaz 30 s;
- zámek 5 s;
- `requestTimeout` v IIS musí být **delší** než limit dotazu, aby aplikace stihla odpovědět sama. Nastaveno 60 s (`nastroje/iis/web.config.priklad`).

**Logy:** každý požadavek má `X-Pozadavek-Id`. Neočekávané chyby jsou v logu s tímto ID. Uživatel vidí jen obecnou zprávu.

### 4.6 Bezpečnost

| Oblast | Opatření |
|---|---|
| Přenos | HTTPS na IIS; DB spojení `Encrypt=yes` |
| Přihlášení | osobní číslo + PIN (argon2, ostrov B); cookie `HttpOnly`, `SameSite=Lax`, `Secure`; klíč ≥ 32 znaků (ADR-0007) |
| Odebrání práv | platí při dalším požadavku (`overeni_kontextu`) |
| Oprávnění | `@vyzaduje("KOD")` na endpointu; oprávnění v DB (`Opravneni`, `RoleOpravneni`) |
| CSRF | `SameSite=Lax` + těla jen JSON |
| Injekce SQL | jen parametry `?`; do textu SQL jen pevné části (ADR-0002) |
| Databáze | aplikace jako `app_sklad` (bez DDL, `DENY UPDATE/DELETE` na historii; `DELETE` jen na `ObsahPozice` a `RoleOpravneni`, `DENY DELETE` na `SkladovaTransakce` – migrace 004); migrace samostatným účtem (ADR-0003) |
| Prohlížeč | `nosniff`, `frame-ancestors 'self'`, `Referrer-Policy`, `no-store` na API; Swagger jen ve vývoji |
| Tajemství | jen v proměnných prostředí nebo `.env` mimo repozitář |
| Audit | změny kmenových dat v `AuditZmen`; skladové operace v `SkladovyPohyb` + `SkladovaTransakce` (kdo, kdy, terminál) |

## 5. Škálování a spolehlivost

### 5.1 Škálování

- **Teď:** jeden server a svislé škálování (víc vláken waitress, víc CPU). Při zátěži z 2.4 se nic jiného nečeká.
- **Druhý server aplikace** jde přidat bez změny kódu: aplikace je bez stavu (P9) a session je v cookie. Stačí stejný `HOUFEK_TAJNY_KLIC` a vyvažování v IIS ARR.
- **Databáze** je jediná a škáluje se svisle. Čtení přehledů jde případně převést na čtecí repliku, pohledy `v_*` jsou připravený šev.

### 5.2 Výpadky

| Výpadek | Dopad | Ochrana | Obnova |
|---|---|---|---|
| Wi-Fi na PDA | odpověď nedojde | `requestId` + pravidlo „nejistý výsledek = stejné ID“ | uživatel klikne znovu |
| Pád procesu aplikace | požadavky selžou | IIS (HttpPlatformHandler) proces znovu spustí | sekundy, terminály opakují se stejným ID |
| Server aplikace | systém nedostupný | monitoring `/zdravi`, záloha konfigurace | reinstalace podle [provoz.md](provoz.md) |
| Databáze | `DATABASE_UNAVAILABLE` 503 | zálohy (plná, rozdílová, log) – DBA | obnova DB, RPO ≤ 15 min |
| Deadlock / zámek | jedna operace | opakování, `CONCURRENT_CHANGE` | uživatel zkusí znovu |
| Chybná migrace | `upgrade` se zastaví | skript v jedné transakci; záloha před `upgrade` | obnova zálohy, oprava novým skriptem |
| Rozjetí dat mimo omezení | špatný přehled | `v_KontrolaIntegrity` v noci | oprava podle nálezu |

### 5.3 Monitoring a alerty (návrh pro IT)

| Co | Jak | Alert |
|---|---|---|
| Aplikace a DB žijí | `GET /api/system/zdravi` každou minutu | HTTP ≠ 200 dvakrát po sobě |
| Provozní režim | `rezim` v `/zdravi` | `VYVOJ` na provozním serveru = okamžitě |
| Chyby | log: `ERROR` (`INTERNAL_ERROR`, `DATABASE_UNAVAILABLE`) | > 5 za 5 min |
| Souběh | log: `Deadlock v …`, `Vypršelo čekání na zámek` | > 20 za hodinu (indikace horkého místa) |
| Integrita dat | noční `GET /api/system/kontrola-integrity` | jakýkoli nález se závažností `CHYBA` |
| SQL Server | blokování > 5 s, version store v tempdb, zálohy | podle standardu DBA |

## 6. Kompromisy

| Rozhodnutí | Získáváme | Vzdáváme se | ADR |
|---|---|---|---|
| Modulární monolit | jedna transakce, jedno nasazení, jednoduchý provoz | nezávislé nasazení ostrovů | [0001](adr/0001-modularni-monolit-a-ostrovy.md) |
| pyodbc + ruční T-SQL | viditelné zámky, kontrola P1/P2 nad SQL | pohodlí ORM, víc mapovacího kódu | [0002](adr/0002-pyodbc-a-rucni-tsql.md) |
| Číslované T-SQL migrace | DBA čte, co poběží; bez nástrojů navíc | automatický rozdíl, downgrade | [0003](adr/0003-ciselne-sql-migrace.md) |
| `requestId` v DB | atomická ochrana proti dvojímu zápisu | tabulka roste, pravidlo pro klienty | [0004](adr/0004-requestid-a-skladova-transakce.md) |
| Zámky pozic + RCSI | konflikt hned na začátku, přehledy neblokují | kázeň „zamknout první“, ruční krok DBA | [0005](adr/0005-zamky-pozic-a-rcsi.md) |
| Pohledy `v_*` | výkonné přehledy, vlastník smí měnit tabulky | údržba pohledů, pořadí v migraci | [0006](adr/0006-pohledy-jako-cteci-kontrakt.md) |
| Cookie + ověření | bez stavu, okamžité odebrání práv | nejde spravovat jednotlivé relace | [0007](adr/0007-session-cookie-a-overeni.md) |
| Jinja + čistý JS | testovací UI bez sestavování | bohaté UI | [0008](adr/0008-ui-jinja-a-cisty-js.md) |
| sqlite + SQL Server | rychlé testy, věrné T-SQL | dvě prostředí testů | [0009](adr/0009-strategie-testu.md) |
| Uložený `FullBoxKlic` | rychlý sken, unikátnost v DB | přepočet při přesunu | [0010](adr/0010-fullboxklic-ulozeny.md) |
| Vlastní OpenAPI | přesná obálka, spolehlivá kontrola P10 | údržba generátoru | [0011](adr/0011-pydantic-a-vlastni-openapi.md) |

## 7. Co přehodnotit s růstem

| Spouštěč (měřitelný) | Co udělat |
|---|---|
| `CONCURRENT_CHANGE` na stejném místě > 20× za směnu | rozdělit horký box, nebo zamykat po regálech u inventury |
| p95 přehledu > 1 s | indexovaný pohled nebo předpočítaná tabulka; čtecí replika |
| `SkladovaTransakce` > 10 mil. řádků | archivace spolu s `SkladovyPohyb` (TD-14) |
| > 50 současných terminálů | druhý server aplikace za IIS ARR |
| další klient (nativní PDA, ERP) | stejné API + pravidlo `requestId`; generovat klienta z OpenAPI |
| napojení na PowerKey | samostatný ostrov integrace se svým rozhraním, nikdy přímé čtení cizí DB z ostrovů |
| tisk štítků blokuje terminály | tabulka úloh v DB + jeden worker |

## 8. Předpoklady k potvrzení

| Předpoklad | Hodnota v návrhu | Kdo potvrdí |
|---|---|---|
| Počet současných PDA a PC | 10–20 a 5–10 | provoz skladu |
| Objem operací | 2 000–5 000 za den, 2 směny | provoz skladu |
| Časy směn a okno údržby | Po–Pá 6–22, údržba mimo | provoz skladu, IT |
| RPO / RTO | 15 min / 4 h | DBA, vedení |
| Server aplikace | Windows Server + IIS (HttpPlatformHandler) + waitress | IT |
| Edice a verze SQL Serveru | neznámé (`SELECT @@VERSION`) | DBA |
| Interní certifikační autorita pro DB a HTTPS | neznámé | IT |
| PDA, prohlížeč, čtečka (Enter po skenu) | neznámé | IT, provoz |
