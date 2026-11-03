# Migrace z XLSM – rozbor vzorku a pravidla pro ostrov H

**Stav k:** 3. 11. 2026 · **Pro:** vlastníka ostrova H (P4), vedoucího projektu · **Zdroj:** `skladova_databaze_v01_prvni_generace.xlsm` (vzorek od firmy, uložený u vedoucího projektu) · **Zadání:** kap. 5 a 6.1

Soubor je provizorní databáze, ze které nový systém vychází. Obsahuje jeden regál (PLE-R01) a 29 boxů. Neobsahuje počty kusů, členění boxů ani typ DYN/STAT. Doplňovací tabulku firma nemá, proto import vezme jen to, co v souboru je, a zbytek se doplní v aplikaci (sekce 4, rozhodnutí 3. 11.).

## 1. Co soubor obsahuje

| List | Obsah | Kam v SQL |
|---|---|---|
| `Databáze` | Tabulka `DatabazeTabulka`. Jeden řádek = jeden díl v jednom boxu; box s více díly má víc řádků. Vyplněných řádků je 67 z 338, prázdné řádky jen oddělují úrovně. | struktura, boxy, díly, STAT přiřazení |
| `Půdorys_regálu` | Plocha úrovní PLE-R01: U01–U05 2352 × 665 mm, U00 2000 × 980 mm. U05 nemá žádný box. | `Uroven.DelkaPlochyMM`, `HloubkaPlochyMM` (jen informace, SVG se počítá z boxů) |
| `Nápověda` | 8 pracovišť a význam kódů STAV_BOXU | pracoviště jsou už v migraci 001 a shodují se se souborem |
| makro (VBA) | Při změně sloupce I připíše novou hodnotu za starou, oddělenou znakem „ › “. Je to ruční historie. | nepřevádí se, historii vede `SkladovyPohyb` a `AuditZmen` |

**Data:**
- pracoviště PLE, regál R01, úrovně U00–U04;
- 29 boxů BPLE01–BPLE29:
  - 11 s jedním dílem, 7 se dvěma, 4 se třemi, 6 se čtyřmi, 1 se šesti;
  - rozměry 26× 300 × 500 mm, 1× 460 × 500, 1× 600 × 800, 1× 1200 × 800;
- 65 dílů, každý právě v jednom boxu.

**STAV_BOXU (list Nápověda):**

| Kód | Význam | Barva v XLSM |
|---|---|---|
| 0 | prázdná skladová pozice | světle šedá |
| OPER | operační díl | zelená |
| MEOP | mezioperační díl | oranžová |
| POL | polotovar | modrá |
| BLOK | blokovaný box (vadné / kontrola) | červená |
| MULTI | multi-box | fialová |

## 2. Mapování sloupců

Rozhodnutí vedoucího projektu z 2. a 3. 11. 2026 jsou označená ✔.

| Sloupec XLSM | Cíl v SQL | Převod |
|---|---|---|
| PRACOVIŠTĚ | `Pracoviste` (seed 001) | ověřit kód, nic nepřevádět (SV1, MO1 … neexistují) |
| REGÁL | `Regal.KodRegalu` | R01 |
| ÚROVEŇ | `Uroven.KodUrovne`, `Poradi` | U00–U04; plocha z listu `Půdorys_regálu` |
| POZICE | `Pozice.Poradi` (P01…) | jedna Pozice = právě jeden box (kap. 6) |
| BOX_ID | `Box.KodBoxu`, `TypBoxuID` | ✔ Převést na tři číslice: BPLE01 → BPLE001. ✔ Typ určí sklad po boxech v aplikaci (sekce 4): STAT dostane nový kód BSTAT001…, DYN zůstane BPLE…. Všechny boxy dostanou nové štítky. |
| IDENTIFIKAČNÍ_ČÍSLO | `Dil.IdentifikacniCislo` | Ořez a velká písmena. „Volný box.“ = box bez dílu, „Volný slot.“ = prázdná přihrádka; ani jedno není díl. |
| STAV_BOXU | `Box.Blokovany` | Zadání (kap. 5): legacy údaj, cílový stav se počítá z typu, obsahu a blokace. ✔ (Q-21, 3. 11.): BLOK → 1. MULTI = box s více přihrádkami, členění nastaví sklad v aplikaci. 0, OPER, MEOP a POL se nepřevádí, barvu počítá systém (kap. 7.2). |
| VAULT PDF | `Dil.VaultVykresURL` | beze změny |
| INFORMACE, WORKFLOW | – | sloupce jsou prázdné |
| MINIMÁLNÍ POČET KUSŮ V BOXU | `StatickeUmisteniDilu.MinimalniPocetKs` | Jen u STAT boxů. Hodnota = první číslo („50 kusů (1 kus na stroj)“ → 50). Import ho uvede v seznamu importu, STAT místo s ním založí sklad v aplikaci. ✔ Text v závorce jde do `Dil.Poznamka`. |
| JINÉ INFORMACE | `Dil.Poznamka` | ✔ Pokyny se převedou („díl musí být ohnutý dle výkresu“, „Používat jen na servis“, „Musí být 1 mm“). Samotná barva boxu („Zelený box.“) se nepřevádí. |
| DÉLKA_BOXU_(mm), HLOUBKA_BOXU_(mm) | `Box.DelkaMM`, `HloubkaMM` | beze změny |
| FULL_BOX_KLÍČ | `Box.FullBoxKlic` | Spočítá se znovu z převedeného kódu: HOUFEK-PLE-R01-U01-BPLE01 → HOUFEK-PLE-R01-U01-BPLE001. Vzorec v XLSM je stejný jako v systému. |

## 3. Nálezy v datech (validační report importu je musí hlásit)

1. **Dva boxy na jedné Pozici.** U00/P01 má BPLE28 (1200 mm) i BPLE29 (600 mm), což kap. 6 zakazuje. Vedle sebe se vejdou (1800 mm z 2000 mm). Import dá BPLE29 další volnou Pozici (P02), sklad pořadí případně změní v aplikaci.
2. **Boxy s více díly nemají členění ani přihrádky.** Pro každý box s více díly je potřeba členění C1–C7 a u každého dílu přihrádka (DYN A–R, STAT 1–n). Import založí C1, sklad členění nastaví v aplikaci. Vodítko podle počtu řádků: 2 → C2 (u dlouhého boxu C5), 3 → C3, 4 → C4, 6 → C6 (BPLE28, „Volný slot.“ = prázdná přihrádka).
3. **Volný box s minimem.** BPLE27 je „Volný box.“, ale má minimum 20 ks. Minimum bez dílu se nepřevádí.
4. **Čísla dílů s příponou nebo v jiném tvaru** (ABR31036_1, ABR31036_2, PN1005) se převádí beze změny, pravidlo identifikačního čísla je volné. Zda jsou ABR31036, _1 a _2 opravdu tři různé díly, potvrdí technolog.
5. **Jeden odkaz do Vaultu** má plný název serveru (srvvault2401.houfek.local), ostatní krátký. Převádí se beze změny.
6. **XLSM nemá:** počty kusů (doplní je inventura při spuštění, pohyby POCAT-STAV, Q-20), velikost pozice a standardní dávku dílu, materiál, tloušťku, první operaci, maximum a názvy dílů. Doplní je technolog.
7. **Barvy se změní.** V XLSM znamená zelená operační díl, v novém systému úplně prázdný box (kap. 7.2). Při zaškolení na to obsluhu upozornit.

## 4. Import bez doplňovací tabulky (rozhodnutí 3. 11. 2026)

Firma doplňovací tabulku nemá. Import proto vezme z XLSM jen to, co v něm je. Ostatní údaje se doplní a mění v aplikaci přes administraci, kterou mají ostrovy C, D a E už v kontraktu.

| Co | Po importu | Kde se změní v aplikaci |
|---|---|---|
| regál, úrovně | R01, U00–U04, plocha z listu `Půdorys_regálu` | `PATCH /api/struktura/regaly/{id}`, `PATCH /api/struktura/urovne/{id}` |
| box | kód BPLE001… (D-02), typ DYN, členění C1, rozměry z XLSM, Pozice podle pořadí v souboru (nález 1) | typ DYN → STAT výměnou boxu `POST /api/struktura/boxy/{id}/vymena` (nový kód BSTAT…, nový štítek); členění `POST /api/struktura/boxy/{id}/rekonfigurace`; pořadí `POST /api/struktura/boxy/{id}/poradi` |
| blokace | STAV_BOXU BLOK → `Box.Blokovany = 1` | `POST /api/struktura/blokace` |
| díl | identifikační číslo, odkaz do Vaultu, poznámka; ostatní údaje prázdné (nález 6) | `PATCH /api/dily/{id}`, velikost `PATCH /api/dily/{id}/velikost` |
| STAT místo a minimum | nezakládá se, typ boxu ještě není známý | `POST /api/sklad/stat-mista` |
| počty kusů | žádné | počáteční inventura, pohyby POCAT-STAV (Q-20) |

- Boxy jsou po importu prázdné. Změna typu i členění proto projde, protože rekonfigurace smí jen u prázdného boxu bez STAT přiřazení (Q-27).
- **Seznam importu** je výstup pro sklad. Pro každý box uvádí:
  - díly z XLSM;
  - minimum;
  - STAV_BOXU (MULTI = box s více přihrádkami);
  - nálezy ze sekce 3.

  Podle seznamu sklad v aplikaci nastaví typ, členění a STAT místa.
- **Chyby a upozornění:** co by porušilo pravidla databáze (duplicitní kód, neplatné číslo dílu), import zastaví a vypíše. Ostatní nálezy jsou jen upozornění v seznamu (analýza 11.1, krok 3–5).
- **Pořadí:** import, úpravy v aplikaci, tisk štítků, počáteční inventura.
- Import jde do prázdné databáze opakovat. Testovací databázi v Dockeru vyprázdní `docker compose down -v` ([vyvoj.md](vyvoj.md), sekce 1.1).
