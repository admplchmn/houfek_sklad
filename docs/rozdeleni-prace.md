# Rozdělení práce – fáze 1 a dál

**Stav k:** 2. 11. 2026 · **Pro:** vedoucího projektu, programátory a AI agenty · **Pravidla práce:** [AGENTS.md](../AGENTS.md)

Každý ostrov má jednoho vlastníka a vlastní složku. Kontrakty všech ostrovů jsou hotové a uložené ve snímku `kontrakty/`: endpointy, modely, chybové kódy a funkce rozhraní. Ostrovy jsou už zapojené do aplikace. Ve fázi 1 každý doplní za kontrakt svého ostrova skutečné SQL a ostatní tím nezdrží.

## 1. Základ z fáze 0 (hotový)

- **Platforma:** transakce, `requestId`, obálka, chyby, přihlášení, migrace, OpenAPI, základ UI a běh bez databáze.
- **Kontrakty ostrovů B–G.** Počty endpointů jsou v [README](../README.md).
- **Pravidla v `domena.py`** každého ostrova, otestovaná bez databáze.
- **Kostra:** služby a rozhraní vracejí vzorová data z `ukazky.py`, takže aplikace jde proklikat i bez SQL Serveru.
- **Migrace 001–004:** schéma, pohledy ostrovů a práva aplikace.

## 2. Krok 0: než začnou ostatní

| Co | Kdo | Proč |
|---|---|---|
| Společný git repozitář a CI, které na každý pull request spustí `python -m nastroje.over_vse` | vedoucí rozhodne kde, P1 nastaví | bez toho nejde pracovat souběžně a pravidla ostrovů chrání jen automatická kontrola |
| SQL Server pro testy: testovací server v Dockeru, `docker compose up -d` a `python -m nastroje.testovaci_db` ([vyvoj.md](vyvoj.md), sekce 1.1) | každý u sebe (Docker Desktop), připraveno 3. 11. | SQL ostrovů se testuje jen proti SQL Serveru ([ADR-0009](adr/0009-strategie-testu.md)); potřeba od prvního dne fáze 1 |
| Data pro integrační testy: do testovací databáze se nezakládá vzorový svět, řádky ostrovů C a D si každý test založí sám jejich funkcemi `zaloz_*` v transakci testu a na konci se vrátí zpět | P1 (harness), C a D (`zaloz_*`) | E, F a G potřebují řádky ostrovů C a D kvůli cizím klíčům; vlastní data dovolují testu běžet kdykoli a souběžně |
| Otázky pro Sklad a Inventuru (Q-07 až Q-11, Q-13 až Q-17, Q-26): rozhodnout, nebo potvrdit výchozí řešení z analýzy | vedoucí s vlastníkem procesu | mění tvar příkazů E a F; do té doby E a F dělají části, kterých se otázky netýkají |

B, C a D můžou začít hned, jakmile mají SQL Server: jejich SQL potřebuje jen vlastní tabulky.

## 3. Kdo co dělá

Vlastníci jsou podle varianty pro 6 lidí. Varianty pro 4 a 5 lidí jsou v dokumentu „HOUFEK – Ostrovy aplikace a konvence API“, sekce 8.

| Ostrov | Vlastník | Složka | API | Volá rozhraní |
|---|---|---|---|---|
| A Platforma | P1 | `app/platforma` | `/api/system` | – |
| B Identita | P1 | `app/ostrovy/identita` | `/api/identita` | – |
| C Struktura | P2 | `app/ostrovy/struktura` | `/api/struktura` | – |
| D Díly | P4 | `app/ostrovy/dily` | `/api/dily` | – |
| E Sklad | P3 | `app/ostrovy/sklad` | `/api/sklad` | C, D |
| F Inventura | P5 | `app/ostrovy/inventura` | `/api/inventura` | C, D, E |
| G Přehledy | P6 | `app/ostrovy/prehledy` | `/api/prehledy` | B, C, D, E |
| H Migrace | P4 | `app/ostrovy/migrace` | `flask migrace …` | C, D, E |

## 4. Jak pracovat nezávisle

1. Co je ještě kostra, ukáže `grep -n ukazky app/ostrovy/<ostrov>/*.py`. To nahrazuješ skutečným SQL.
2. SQL patří do `repozitar.py`: jen parametry `?`, zápis jen do vlastních tabulek, cizí data jen z `v_*`.
3. Vlastní služby (`sluzby.py`) napoj na repozitář hned. Endpointy se nemění.
4. Funkce v `rozhrani.py`, které volají ostatní ostrovy:
   - **Vracejí vzorová data?** Jakmile máš čtecí dotazy v `repozitar.py` hotové a otestované, zavolej je z `rozhrani.py` – podpis se nemění (rozhodnutí vedoucího 5. 11. 2026). Bez SQL Serveru, ať už je to sqlite kostra nebo `spoj` = `None`, ať funkce vrací dál vzorová data: ostatní tak mají stabilní vzorky i bez databáze a tvoje rozpracovaná verze je nerozbije.
   - **Vyvolají zatím `NotImplementedError`?** To jsou zápisy pro jiné ostrovy. Naprogramuj je ve fázi 1 jako první, protože na ně jiný ostrov čeká:
     - `zauctuj_korekci` (E → F);
     - `prirad_stat_misto` (E → H);
     - `zaloz_*` (C a D → H).
5. Testy:
   - pravidla v `domena.py` jednotkově, bez databáze, jako dosud;
   - SQL proti SQL Serveru: test dědí z `ZakladIntegrace` (`tests/integrace/zaklad.py`) a funkci repozitáře předá `self.spoj`. Na konci testu se vše vrátí zpět. Soubor patří do `testy/` tvého ostrova a bez `HOUFEK_TEST_DB_*` se přeskočí;
   - testy vlastních služeb, které dnes běží nad vzorovými daty, po napojení na SQL převeď na integrační.
6. Chybí ti něco v cizím rozhraní? Napiš vlastníkovi. Přidání funkce nebo pole nic nerozbije, takže ho vlastník udělá hned a nemusíš čekat na celou jeho práci. Do té doby pracuj se vzorovými daty, nikdy ne s cizími tabulkami.
7. Otevřená otázka Q-xx se neřeší odhadem. Udělej, co je jasné, a otázku pošli vedoucímu.

## 5. Zadání ostrovů pro fázi 1

### B – Identita (P1)

- **Z fáze 0:**
  - pravidla PINu a rolí;
  - hash argon2;
  - hák `overeni_kontextu`.
- **Fáze 1:**
  - uživatelé, role a terminály nad SQL;
  - přihlášení PINem nebo kartou se zámkem po chybných pokusech (TD-07). Přihlášení se tím stane `@transakce` (S-17);
  - `overeni_kontextu` nad `v_Uzivatel`.
- **Pro ostatní:** `nacti_uzivatele` (G), pohledy `v_Uzivatel` a `v_Terminal`.
- **Otevřené:**
  - Q-18, Q-24 a Q-32 (brána G4);
  - přiřazení oprávnění rolím.
- **Hotovo, když:** přihlášení a správa uživatelů běží proti SQL Serveru a vyřazený uživatel ztratí přístup hned.

### C – Struktura skladu a kódy (P2)

- **Z fáze 0:**
  - parser kódů;
  - kódy a řady boxů a pořadí boxů na úrovni;
  - šablona členění C1–C7;
  - rozměry pro SVG (17.1);
  - zámky pozic `zamkni_mista` (hotové T-SQL).
- **Fáze 1:** pracoviště, regály, úrovně, boxy a vnitřní pozice nad SQL:
  - založení boxu ze šablony;
  - výměna boxu;
  - přesun boxu s přepočtem `FullBoxKlic` ([ADR-0010](adr/0010-fullboxklic-ulozeny.md));
  - pořadí boxů a rekonfigurace;
  - rozměr C7;
  - blokace a deaktivace.

  Skutečné verze funkcí rozhraní, které dnes vracejí vzorová data, patří do repozitáře.
- **Pro ostatní:**
  - rozhraní pro E, F, G a H. Funkce `zaloz_*` pro H naprogramuj jako první;
  - pohledy `v_Misto` a `v_VelikostPozice`.
- **Kódy a štítky (kap. 11 zadání).** V kódu jsou hotové (`domena.py`, `rozhrani.rozloz_kod`), nepiš je znovu:
  - box je `B` + kód pracoviště + číslo 001–999 (`BPLE037`), statický box `BSTAT` + číslo (`BSTAT037`); kódy jsou v systému jedinečné;
  - vnitřní pozice DYN = kód boxu + `-` + písmeno A–R včetně CH (`BPLE037-D`), STAT = kód boxu + `-` + číslo 1…n (`BSTAT037-1`). Číslo dílu v barcode nikdy není;
  - regál `HOUFEK-PLE-R01`, celý box (FullBoxKlic) `HOUFEK-PLE-R01-U03-BPLE003`, pozice dlouze `HOUFEK-PLE-R01-U03-BPLE003-D`. Jen znaky A–Z, 0–9 a pomlčka;
  - díl nemá barcode, obsluha číslo dílu zadá nebo vyhledá;
  - štítek STAT pozice má nahoře číslo dílu velkým písmem, uprostřed barcode a dole kód pozice (`BSTAT037-1`); regál, úroveň ani pracoviště se netisknou. Hlavní štítek boxu nese `BSTAT037`;
  - STAT pozice se číslují po řadách zezadu dopředu, v řadě zleva doprava. U C4 to potvrzuje obrázek v kap. 11.1: 1 a 2 vzadu, 3 a 4 vpředu u hlavního štítku. Pro ostatní členění je to předpoklad;
  - tisk štítků (PDF) zatím v kontraktu není (S-20). Čeká na Q-19 a na bod 11.3 zadání (štítky DYN boxu).
- **Otevřené:**
  - Q-27;
  - ověřit mapování Q-06 na fyzickém boxu;
  - rozměry přihrádek (A-08);
  - S-21;
  - správa firem (kap. 20) zatím ne, přijde později (D-10). Tabulka `Firma` je připravená, adresy začínají pevně `HOUFEK`.
- **Scénáře:** T13, T22, T23 a T31. S ostrovem G T02, kód pro T27.

### D – Díly a číselníky (P4)

- **Z fáze 0:**
  - normalizace čísla dílu a číselníků;
  - potřeba místa (velikost V1–V6).
- **Fáze 1:**
  - díly a číselníky (materiál, tloušťka, první operace) nad SQL;
  - hledání dílu podle čísla;
  - změna velikosti dílu (Q-28).
- **Pro ostatní:**
  - `najdi_dil`, `nacti_dily`, `hledej_dily` a `nacti_ciselniky` pro E, F a G;
  - `zaloz_dil` pro H, naprogramuj ji jako první;
  - pohled `v_Dil`.
- **Otevřené:** Q-28. Vault má zatím jen připravené pole pro odkaz na výkres.
- **Scénáře:** T01 (s ostrovem G).

### E – Sklad: pohyby a zásoby (P3)

- **Z fáze 0:**
  - kontroly příjmu, výdeje a přesunu;
  - upozornění zásoby;
  - kandidáti DYN.
- **Fáze 1:** obsah pozic a pohyby nad SQL. Příjem DYN a STAT, výdej i přesun je každý jedna `@transakce(…, skladova=True)` v tomto pořadí:
  1. zamknout pozice (`struktura.zamkni_mista`);
  2. načíst stav;
  3. pravidla z `domena.py`;
  4. zapsat obsah i pohyb se stejným `TransakceID`;
  5. upozornění zásoby.

  Patří sem i statická místa a upozornění.
- **Stavíš na:**
  - C: `najdi_vnitrni_pozici`, `najdi_objekt`, `zamkni_mista`, `nacti_mista`, `kandidatni_mista_dyn`, `pozice_v_rozsahu`, `stav_boxu`;
  - D: `nacti_dily`.
- **Pro ostatní:**
  - `obsah_mist`, `posledni_pohyby`, `stat_mista` a `nacti_ciselniky` pro F a G;
  - `zauctuj_korekci` pro F a `prirad_stat_misto` pro H. Obě naprogramuj jako první;
  - pohledy `v_ObsahPozice`, `v_StatickeMisto`, `v_ZasobaDilu` a `v_PohybDetail`.
- **Otevřené:** Q-07 až Q-11, Q-13 až Q-15 a Q-26 (brána G2).
- **Scénáře:** T03–T08, T10, T12, T14–T21, T27, T30 a T32. T10 a T30 jsou souběhové.

### F – Inventura (P5)

- **Z fáze 0:**
  - vyhodnocení položek;
  - přepočet;
  - plán korekcí.
- **Fáze 1:** inventura a položky nad SQL:
  - založení: kontrola překryvu až po `zamkni_mista` (S-16);
  - slepý zápis: očekávaný stav se před zápisem neukáže;
  - dokončení s korekcemi přes `sklad.zauctuj_korekci`. Tu dodá E. Do té doby vrací dokončení jen plán korekcí, jako teď;
  - stav PREPOCITAT podle posledního pohybu. Sloupec přidá P1 migrací po rozhodnutí Q-16 (TD-25).
- **Stavíš na:**
  - C: `pozice_v_rozsahu`, `zamkni_mista`, `najdi_vnitrni_pozici`, `nacti_mista`, `vejde_se`;
  - E: `obsah_mist`, `posledni_pohyby`, `stat_mista`, `zauctuj_korekci`;
  - D: `nacti_dily`.
- **Otevřené:** Q-16, Q-17 a S-22.
- **Scénáře:** T11, T24, T25 a T26.

### G – Přehledy a navigace (P6)

- **Z fáze 0:**
  - barvy boxu;
  - souhrn zásob;
  - laser (Q-22);
  - kostra přes rozhraní B–E.
- **Fáze 1:** každý přehled jedním SQL dotazem nad pohledy `v_*` místo skládání přes rozhraní (S-18). Jde o sken, hledání, kartu dílu, zásoby, laser, pohyby, transakce a rozložení úrovně. Geometrie rozložení zůstává z rozhraní C.
- **Rozhodnuto 3. 11.:** DYN box s obsahem je modrý (Q-31, kód `MODRA`). Monitoring má filtr „pouze díly s aktivním STAT umístěním“, ve výchozím stavu zapnutý ([soulad-se-zadanim.md](soulad-se-zadanim.md), V-01).
- **Otevřené:** Q-22.
- **Scénáře:** T01, T02, T09 a T33.

### H – Migrace XLSM (P4)

- **Fáze 1:**
  - staging, seznam importu a výchozí hodnoty podle [migrace-xlsm.md](migrace-xlsm.md), sekce 4 (vzorek od firmy je u vedoucího projektu). Doplňovací tabulka nebude, chybějící údaje se doplní v aplikaci (rozhodnutí 3. 11.);
  - import přes rozhraní C, D a E;
  - opakovatelný běh.
- **Otevřené:** Q-20.
- **Scénáře:** T29.

### A – Platforma (P1)

- **Krok 0** (sekce 2).
- **Revize:** pull requesty, které mění `rozhrani.py`, `kontrakty.py`, pohledy a migrace.
- **Migrace podle rozhodnutí:** TD-25 po Q-16, S-15.
- **Zapojení ve fázi 2.**
- **Scénáře:** T14 (s ostrovem E) a T28.

## 6. Fáze 2 a dál

1. **Brána K2:** každý ostrov má integrační testy svých operací a projde samostatně.
2. **Fáze 2, zapojení** (koordinuje P1):
   - rozhraní už repozitář volá – vlastník ho napojil hned za svými čtecími dotazy ve fázi 1 (sekce 4, bod 4);
   - testy přes více ostrovů běží proti SQL Serveru;
   - scénáře T01–T33 se projdou přes Swagger.
3. **Brána K3:** backend je hotový, scénáře i souběhové testy jsou zelené.
4. **Fáze 3:** každý vlastník udělá obrazovky svého ostrova ve `stranky/`.
5. **Brána K4.**
6. **Fáze 4:** migrace nanečisto a pilot.

## Příloha: akceptační scénáře

Převzato z analýzy, sekce 14. Ostrov = kdo scénář dodává a testuje.

| ID | Scénář | Očekávaný výsledek | Typ | Ostrov |
|---|---|---|---|---|
| T01 | Vyhledat AAR10044 | karta dílu, všechna umístění, Vault, klikací výsledky | akceptační | G, D |
| T02 | Kliknout na umístění | vykreslí se správná úroveň, zvýrazní se box i pozice | akceptační | G, C |
| T03 | Příjem do DYN | jen kompatibilní volná pozice; stav i historie zapsány | akceptační | E |
| T04 | Výdej z DYN na 0 | pozice volná, historie zůstává | akceptační | E |
| T05 | Přesun | jen celá dávka, OUT + IN se stejným TransakceID | akceptační | E |
| T06 | Příjem do STAT | jen přiřazený díl, množství se přičte | akceptační | E |
| T07 | Výdej ze STAT na 0 | pozice zůstává dílu vyhrazena | akceptační | E |
| T08 | Pokles pod minimum | vznikne 1 otevřené upozornění | akceptační | E |
| T09 | Laser S235 / 3 mm | jen díly LASER odpovídající filtru a pod maximem | akceptační | G |
| T10 | Souběžný příjem do stejného cíle | uspěje 1, druhý dostane POSITION_OCCUPIED | souběhový | E |
| T11 | Inventurní rozdíl | korekční pohyb, žádný tichý přepis | akceptační | F |
| T12 | Admin chce přepsat počet | funkce ani endpoint neexistuje | akceptační | E |
| T13 | Parser kódů | všechny tvary z 5.1, CH, neplatné vstupy; BPLE037-K na boxu C2 → NOT_FOUND | jednotkový | C |
| T14 | Stejný requestId 2× | 1 pohyb, stejná odpověď | integrační | A, E |
| T15 | Výdej nad stav | INSUFFICIENT_STOCK, nic se nezmění | integrační | E |
| T16 | Přesun s množstvím | WHOLE_BATCH_ONLY | integrační | E |
| T17 | Příjem do DYN jiné velikosti | SIZE_MISMATCH | integrační | E |
| T18 | Příjem jiného dílu do STAT | WRONG_PART | integrační | E |
| T19 | Operace na blokované pozici | POSITION_BLOCKED podle Q-09 | integrační | E |
| T20 | Opakované výdeje pod minimem, pak doplnění | stále 1 otevřené upozornění, po doplnění uzavřené | integrační | E |
| T21 | Minimum 0 a stav 0 | VYCERPANO | jednotkový | E |
| T22 | Výměna boxu na stejné Pozici | PoziceID zachováno, historie starého boxu dohledatelná | integrační | C |
| T23 | Vložení boxu doprostřed úrovně | pořadí přečíslováno, SVG ve správném pořadí | integrační | C |
| T24 | Slepá inventura | očekávaný stav není v odpovědi před zápisem | integrační | F |
| T25 | JINY_DIL v DYN a ve STAT | korekce podle Q-17, žádné porušení pravidel pozice | integrační | F |
| T26 | Pohyb během inventury | položka PREPOCITAT, dokončení bez přepočtu odmítnuto | integrační | F |
| T27 | Sken celého boxu v operaci | WRONG_SCAN_LEVEL | integrační | E (kód z C) |
| T28 | UPDATE SkladovyPohyb aplikačním účtem | databáze odmítne | integrační | A |
| T29 | Import XLSM | počty staging = cíl, žádné osiřelé záznamy, každá Pozice má 1 Box | migrační | H |
| T30 | Přesun A → B a B → A současně | oba skončí bezpečně, bez neošetřeného deadlocku | souběhový | E |
| T31 | Rozložení SVG | šířka a výška podle vzorců 17.1; změna rozměru boxu posune následující | jednotkový | C |
| T32 | Součet pohybů | pro každou pozici součet Mnozstvi = aktuální PocetKs | integrační | E |
| T33 | Odezva skenu | cílová hodnota k potvrzení, návrh do 0,5 s na terminálu | výkonnostní | G |
