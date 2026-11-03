# ADR-0007: Přihlášení – podepsaná session cookie a ověření uživatele při každém požadavku

**Stav:** Přijato (vedoucí projektu, 2. 11. 2026)
**Datum:** 2026-10-26
**Rozhodují:** vedoucí projektu, IT bezpečnost HOUFEK
**Mění:** analýzu, sekce 8.1, řádek „Přihlášení“ (upřesnění); code review CR-03, CR-10

## Kontext

- Skladníci se přihlašují na **sdílených** PDA osobním číslem a PINem. Kancelář používá prohlížeč na PC.
- Zadání nepožaduje přihlášení přes AD. PDA se navíc sdílí mezi lidmi, takže přihlášení Windows nepomůže.
- Aplikace běží ve víc vláknech nebo procesech (waitress) a nesmí držet sdílený stav v paměti (P9).
- Odebrání práva nebo deaktivace uživatele musí platit **hned**, ne až po vypršení session (CR-10).

## Rozhodnutí

- **Cookie.** Kontext přihlášeného uživatele je v **podepsané cookie Flasku**:
  - obsah: `uzivatelId`, `terminalId`, `kodRole`, `opravneni`;
  - nastavení: název `houfek_sklad`, `HttpOnly`, `SameSite=Lax`, `Secure` mimo vývoj, platnost 12 h;
  - podpis klíčem `HOUFEK_TAJNY_KLIC`, v provozu povinně ≥ 32 znaků. Ve vývoji se klíč generuje náhodně při startu (CR-03).
- **Ověření při každém požadavku.** Ostrov Identita dodá `Ostrov(overeni_kontextu=…)`. Platforma ji volá při každém požadavku v `auth.kontext()`:
  - `None` (uživatel neaktivní nebo smazaný) → session se smaže, odpověď `NOT_AUTHENTICATED` „Přihlášení už neplatí.“;
  - jinak se použijí **aktuální** oprávnění z databáze, ne ta z cookie.
  - Hák smí dodat jen jeden ostrov (startovní kontrola).
- **Kde se přihlášení vynucuje.** Každý endpoint pod `/api` vyžaduje přihlášení, pokud nemá `@verejne`. `@vyzaduje("KOD")` navíc ověří oprávnění.
- **Ochrana proti CSRF ve dvou vrstvách:**
  - `SameSite=Lax`: prohlížeč nepošle cookie s cizím POST;
  - těla příkazů jsou jen JSON (`nacti_vstup` odmítne jiný `Content-Type`). Cizí HTML formulář JSON poslat neumí a cizí `fetch` s JSON neprojde CORS (aplikace žádné CORS hlavičky nevrací).
- **PIN** jako hash argon2 (`argon2-cffi`) a ochrana proti zkoušení patří ostrovu B (TD-07).

## Zvažované možnosti

### Možnost A: Podepsaná cookie + ověření při každém požadavku (zvoleno)

| Hledisko | Hodnocení |
|---|---|
| Složitost | Nízká – vestavěná session Flasku + jedna funkce ostrova B |
| Náklady | Jeden dotaz podle primárního klíče na požadavek |
| Škálovatelnost | Bez stavu na serveru, víc procesů bez sdíleného úložiště |
| Znalost týmu | Vysoká |

**Pro:** žádná tabulka relací ani úklid. Odebrání práv platí okamžitě díky háku.
**Proti:**
- nejde vypsat ani ukončit konkrétní relaci; ukončit jdou jen všechny (změnou klíče) nebo deaktivací uživatele;
- cookie má limit ~4 kB, což oprávnění jedné role pohodlně splní.

### Možnost B: Relace uložené na serveru (tabulka `Relace`)

| Hledisko | Hodnocení |
|---|---|
| Složitost | Střední – tabulka, úklid, čtení při každém požadavku |
| Náklady | Jeden dotaz na požadavek (stejně jako A) + úklidová úloha |
| Škálovatelnost | Dobrá |
| Znalost týmu | Vysoká |

**Pro:** přehled přihlášených, odhlášení konkrétního terminálu, časový limit nečinnosti přímo v datech.
**Proti:** další tabulka a úloha k provozu. Hlavní přínos (okamžité odebrání práv) dává už hák v A.

### Možnost C: JWT tokeny v hlavičce `Authorization`

| Hledisko | Hodnocení |
|---|---|
| Složitost | Střední – vydávání, obnova, úložiště v prohlížeči |
| Náklady | Žádná infrastruktura |
| Škálovatelnost | Dobrá |
| Znalost týmu | Střední |

**Pro:** hodí se pro API třetích stran a mobilní aplikace.
**Proti:** token v úložišti JavaScriptu je přístupný případnému XSS, cookie `HttpOnly` není. Odvolání tokenu je stejně potřeba řešit dotazem do DB. Pro web se stejným původem nepřináší nic.

### Možnost D: Integrované přihlášení Windows (AD, Kerberos přes IIS)

| Hledisko | Hodnocení |
|---|---|
| Složitost | Střední – nastavení IIS, mapování účtů |
| Náklady | Žádné licence navíc |
| Škálovatelnost | Dobrá |
| Znalost týmu | Závisí na IT HOUFEK |

**Pro:** jednotné přihlášení na kancelářských PC.
**Proti:** sdílené PDA nemají osobní účet Windows a zadání chce osobní číslo + PIN. Pro kancelář je to možné rozšíření později (otázka z analýzy, sekce 15).

## Rozbor kompromisů

Rozhodlo sdílené PDA a požadavek na okamžité odebrání práv. A a B potřebují stejně jeden dotaz na požadavek. B navíc umí spravovat jednotlivé relace, ale za cenu tabulky a úklidu. Funkce, které B přidává (přehled a ukončení relací), zadání nevyžaduje. Pokud je provoz bude chtít, přechod z A na B je vnitřní změna Platformy a ostrovů se nedotkne (`kontext()` zůstává).

## Důsledky

- **Snazší:** ostrovy znají jen `kontext()` a `@vyzaduje`. Přihlášení funguje na PC i PDA stejně.
- **Těžší:**
  - výměna `HOUFEK_TAJNY_KLIC` odhlásí všechny (plánovat mimo směnu);
  - nové endpointy nesmí přijímat formuláře (`application/x-www-form-urlencoded`), jinak padá druhá vrstva ochrany proti CSRF.
- **Přehodnotit:**
  - časový limit nečinnosti na sdílených PDA (TD-06), dnes platí 12 h od přihlášení;
  - pokud chce provoz vidět přihlášené terminály, přejít na B.

## Úkoly

1. [x] `auth.py`: cookie, `@verejne`, `@vyzaduje`, hák `overeni_kontextu` (CR-10), náhodný vývojový klíč (CR-03).
2. [ ] Ostrov B: `POST /prihlaseni`, argon2, zámek po opakovaných chybných PINech (TD-07), `overeni_kontextu` nad `v_Uzivatel`.
3. [ ] Rozhodnout limit nečinnosti pro role terminálů (TD-06).
