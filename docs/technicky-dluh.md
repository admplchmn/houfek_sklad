# Technický dluh – registr

**Stav k:** 9. 11. 2026 · **Vlastní:** vedoucí projektu, položky Platformy P1 · **Aktualizace:** při každé revizi a na každé bráně (K1–K4)

**Co je potřeba nejdřív:**
- **Spustit integrační testy T-SQL** na testovacím SQL Serveru v Dockeru (TD-01).
- **Dovést CI do zelené** (TD-02): repozitář je na GitHubu, běh #1 padl za 0 s na validaci workflowu (kontext `env` v `jobs.<id>.env`), opraveno. Chybí zelený běh #2.
- **Rozhodnout, zda má být repozitář veřejný** (TD-26): `github.com/admplchmn/houfek_sklad` je public, tedy i rozbor firemního XLSM a zadání. Hesla v něm nejsou, ale obsah je firemní.

Splaceno: TD-18, TD-19 (revize 26. 10.), TD-08, TD-09, TD-12, TD-15 (revize 1. 11.), TD-04 (3. 11., Docker), TD-11 (3. 11., UTC), TD-25 a S-19 (9. 11., migrace 005). TD-01 má hotový harness i testovací server, zbývá ho spustit.

## Jak se hodnotí

- **Dopad** (1–5): jak moc nás položka dnes zdržuje.
- **Riziko** (1–5): co se stane, když ji nevyřešíme.
- **Pracnost** (1–5):
  - 1 = do půl dne,
  - 2 = ~1 den,
  - 3 = 2–5 dní,
  - 4 = 1–2 týdny,
  - 5 = déle.
- **Priorita** = (Dopad + Riziko) × (6 − Pracnost). Vyšší číslo = dřív.

## Registr (podle priority)

| ID | Položka | Kategorie | D | R | P | **Priorita** | Odhad | Proč na tom záleží (provoz skladu) | Kdy |
|---|---|---|---|---|---|---|---|---|---|
| TD-04 | Chyběla testovací DB. Teď je testovací SQL Server v Dockeru: `docker-compose.yml`, `python -m nastroje.testovaci_db` založí `HoufekSklad_TEST` s RCSI a provede migrace. Provozní účty aplikace a migrace popisuje [provoz.md](provoz.md). | Infrastruktura | 5 | 4 | 1 | 45 | 0,5 d | Bez DB nejde spustit migrace ani T-SQL. | **splaceno 3. 11.** |
| TD-01 | Integrační testy T-SQL proti SQL Serveru. Harness `tests/integrace` a 7 testů Platformy jsou hotové (migrace, pohledy, `v_KontrolaIntegrity`, chyba 1222, `requestId`). Zbývá je spustit na testovacím serveru v Dockeru (`docker compose up -d`, `python -m nastroje.over_vse`) a doplnit testy repozitářů C a E (`zamkni_mista` se souběhem, `vloz`, přesun A→B / B→A) (S-01) | Testy | 5 | 5 | 2 | **40** | 2–3 d (průběžně s repozitáři) | Zámky a migrace jsou dnes ověřené jen strukturálně. Chyba v nich = špatná zásoba nebo napůl provedená změna schématu. | teď; testy C a E s jejich fází 1 |
| TD-03 | RCSI na provozní DB je ruční krok DBA (ADR-0005). Testovací DB v Dockeru ho má zapnutý od založení (3. 11.). | Infrastruktura | 3 | 4 | 1 | **35** | 0,1 d + okno údržby | Bez RCSI přehledy blokují terminály a obráceně. Skladník čeká na zámek kvůli obrazovce v kanceláři. | při zakládání provozní DB |
| TD-02 | CI: workflow `.github/workflows/ci.yml` je na GitHubu a poprvé se spustil. Běh #1 (`f1ce877`) padl před startem jobů – `${{ env.X }}` nesmí v `jobs.<id>.env` (kontejnery služeb startují dřív, než se vyhodnotí proměnné jobu). Opraveno, čeká se na běh #2; `CODEOWNERS` pořád jen jako příklad | Infrastruktura | 3 | 4 | 2 | **28** | 0,5 d na doladění do zelené | Pravidla P1–P4, P6 a P10 chrání jen tehdy, když běží automaticky na každý pull request. | teď; `Testy api.js` se v CI běží poprvé (lokalně bez Node.js se vynechávají) |
| TD-26 | Repozitář `admplchmn/houfek_sklad` je na GitHubu **veřejný** (GitHub API odpoví i bez přihlášení). V tree nic citlivého není – `.env`, `ssh_to_git_push.txt` a soukromé klíče `git ls-files` neukazují – ale veřejné je zadání, rozbor firemního XLSM (`migrace-xlsm.md`) a kompletní kód | Infrastruktura | 4 | 5 | 1 | **60** | 0,1 d (přepnout na private, nebo to potvrdit) | Firemní data a postup skladu jsou čitelné komukoli. Hesla jsme nevyndali, ale i tohle je důsledek pushu, který je potřeba vědomě schválit. | rozhodne vedoucí + firma, než do toho začnou psát ostatní ostrovy |
| TD-18 | Dokumenty „Analýza“ a „Ostrovy“ neodpovídaly kódu (8.1 SQLAlchemy/Alembic, chybějící kódy chyb, počty tabulek, pohledy) | Dokumentace | 3 | 3 | 1 | 30 | 0,5 d | Programátor podle dokumentu napíše jiný kód, než Platforma umí. | **splaceno 26. 10.** |
| TD-19 | Kostry rozhraní vracejí vzorová data i v provozu | Kód | 2 | 4 | 1 | 30 | 0,25 d | Terminál by ukázal vymyšlenou zásobu jako skutečnou. Teď v provozním režimu selže (`app/platforma/kostra.py`). | **splaceno 26. 10.** |
| TD-05 | Závislosti bez zámku verzí, jen spodní meze (S-03) | Závislosti | 2 | 3 | 1 | **25** | 0,5 d | Nová verze knihovny může rozbít build nebo provoz bez změny v našem kódu. | teď (`pip freeze` na první vývojové stanici) |
| TD-24 | Zakládací POST bez přirozeného klíče nejsou idempotentní: `POST /api/struktura/urovne/{id}/boxy` bez `cisloBoxu` a `POST /api/inventura` (S-15) | Kód | 2 | 3 | 1 | **25** | 0,25 d (`skladova=True` u dvou operací) | Dvojklik na „Přidat box“ založí dva boxy s dalšími čísly řady. | fáze obrazovek, povinné před pilotem (D-22) |
| TD-06 | Sdílené PDA: bez limitu nečinnosti (S-05). PDA už po 15 min nečinnosti končí, PC stále 12 h | Kód (bezpečnost) | 2 | 4 | 2 | **24** | 0,1 d (rozhodnout a nastavit limit na PC) | Další člověk u PDA zapisuje pohyby pod cizím jménem. Audit by ukazoval špatnou osobu. | PDA splaceno 9. 11. (`app/platforma/auth.py`, test `tests/test_platforma_necinnost.py`); limit na PC otevřený (D-34) |
| TD-07 | PIN: hash argon2 + zámek po opakovaných chybných pokusech (S-06) | Kód (bezpečnost) | 2 | 4 | 2 | **24** | 1 d v přihlášení (argon2, počítadlo, audit) | Krátký číselný PIN (4–6 číslic) jde bez zámku vyzkoušet během minut až hodin. | schéma hotové 9. 11. (migrace 006: `Uzivatel.ChybnePokusy`, `Uzivatel.ZamcenoDo`, tabulka `PrihlaseniPokus`); přihlášení dodá ostrov B, rozhodnuto D-33 (5 pokusů → zámek na 15 min) |
| TD-20 | Monitoring a alerty nejsou nastavené (`/zdravi`, logy, souběh) | Infrastruktura | 1 | 4 | 2 | **20** | 1 d (IT) | Výpadek DB nebo vývojový režim na provozu si nikdo nevšimne, dokud nezavolá sklad. | před pilotem |
| TD-23 | `sken.js` a `api.js` neověřené na skutečném PDA a čtečce (PDA Chainway s vestavěnou čtečkou, 2. 11.) | Testy | 2 | 3 | 2 | **20** | 1 d | Čtečka může posílat jiný konec řádku (Tab, CR), takže tok skenu nebude fungovat. | na kusu Chainway, nejpozději ve fázi 3 (UI) |
| TD-10 | Noční kontrola integrity: úloha, alert, doba běhu (`v_KontrolaIntegrity` prochází historii) (S-09) | Infrastruktura | 2 | 2 | 2 | **16** | 1 d | Rozjetí dat se zjistí až při inventuře. | před pilotem |
| TD-13 | `TrustServerCertificate=yes` k SRVACC01 (S-11) | Infrastruktura (bezpečnost) | 1 | 3 | 2 | **16** | 1 d (IT: interní CA na server aplikace) | Spojení je šifrované, ale bez ověření serveru. Útočník ve vnitřní síti by se mohl vydávat za databázi. | před provozem |
| TD-21 | Nasazení (služba Windows, IIS ARR, HTTPS) popsané, ale nevyzkoušené | Infrastruktura | 1 | 4 | 3 | **15** | 2 d (IT + P1) | První nasazení na provoz nesmí být první zkouškou postupu. | před pilotem |
| TD-22 | `SkladovyPohyb.TransakceID` je NULL-able kvůli importu počátečního stavu | Architektura | 1 | 2 | 1 | **15** | 0,25 d | Pohyb bez hlavičky nejde dohledat k operaci. | po migraci dat (H) |
| TD-16 | `/api/system/zdravi` je veřejné a vrací verzi a režim (S-13) | Infrastruktura (bezpečnost) | 1 | 1 | 1 | **10** | 0,1 d | Jen při publikaci mimo vnitřní síť. | před případnou publikací |
| TD-17 | Swagger ve vývoji z CDN (S-14) | Závislosti | 1 | 1 | 1 | **10** | 0,25 d | Vývoj bez internetu nemá Swagger (kontrakt `/api/openapi.json` funguje). | kdykoli |
| TD-14 | Archivace `SkladovyPohyb` a `SkladovaTransakce` | Architektura | 1 | 1 | 3 | **6** | 2 d | Při odhadu 0,75–1,9 mil. řádků/rok aktuální až za roky. | až > 10 mil. řádků |

D = dopad, R = riziko, P = pracnost. S-xx = doporučení z code review fáze 0 (26. 10. a 1. 11.). S-01 až S-14 jsou položky TD v registru, ostatní otevřená jsou v tabulce níže. Uzavřené záznamy obou revizí jsou ve složce `jiz_nepotrebne/revize/`.

## Otevřená doporučení z revizí

| ID | Doporučení | Kdo, kdy |
|---|---|---|
| S-15 | Zakládací POST bez přirozeného klíče na `skladova=True` (= TD-24) | fáze 1, P1 + vlastníci C a F |
| S-16 | Kontrolu „pozice nejvýš v jedné rozpracované inventuře“ dělat až po `zamkni_mista(ids)`, jinak dvě souběžná založení překryv neuvidí | fáze 1, vlastník F |
| S-17 | Zámek po chybných pokusech PINu potřebuje zápis: přihlášení bude `@transakce("PRIHLASENI")` (pojistka CR-29) | fáze 1, vlastník B |
| S-18 | Přehledy G jedním dotazem nad pohledy `v_*` místo skládání přes rozhraní (indexy jsou v 001) | fáze 1, vlastník G |
| S-20 | `GET /stitky` (PDF) čeká na vzhled štítku (Q-19); test „co se vytiskne, jde přečíst“ už je | pilot, vlastník C |
| S-21 | Kódy pracoviště, regálu a úrovně jsou v barcode, PATCH je nemění; přejmenování = přetisk štítků a přepočet `FullBoxKlic`. Rozhodne vlastník procesu. | otevřený bod |
| S-22 | JINY_DIL v DYN pozici zaúčtuje nalezený díl na stejnou pozici i při jiné velikosti; povinný cíl platí i pro DYN, bez cíle nejde inventuru dokončit | rozhodnuto D-27, vlastník F |

## Plán splácení (souběžně s vývojem funkcí)

Pravidlo: **~15 % kapacity každého sprintu** jde na dluh. Položky Platformy nese P1, položky ostrova jeho vlastník. Dluh se nesplácí zvlášť, ale u funkce, které se týká.

| Kdy | Položky | Podmínka splnění |
|---|---|---|
| **Teď (fáze 0 → 1)** | TD-26 (veřejný repozitář), TD-01 (spustit), TD-05, TD-02 (doladit CI do zelené) | `python -m nastroje.testovaci_db` a `over_vse` projdou na testovacím serveru v Dockeru; CI zelené na prvním pull requestu |
| **Fáze 1, před 1. zápisem pohybu (E)** | TD-01 (testy C a E proti `HoufekSklad_TEST`), TD-24 | integrační vrstva běží v CI nebo ručně proti `HoufekSklad_TEST` v Dockeru; dvojklik nezaloží dva boxy |
| **Fáze 1, s ostrovem B** | TD-07 (schéma hotové 006, zbývá přihlášení), TD-06 (PDA hotové, limit na PC otevřený) | přihlášení PINem počítá pokusy a zamkne účet na 15 min; PDA se po 15 min nečinnosti odhlásí, limit na PC rozhodnutý |
| **Brána K3 (backend hotový, souběhové testy G3)** | TD-01 (testy E: souběh, `requestId`) | souběžné testy přesunů A→B / B→A bez deadlocku |
| **Před pilotem (fáze 4)** | TD-20, TD-10, TD-21, TD-13, TD-23, TD-03 (provozní DB) | zkušební nasazení podle [provoz.md](provoz.md); alert z `/zdravi` dorazí; PDA projde tok skenu |
| **Po migraci dat (H)** | TD-22 | `TransakceID` NOT NULL |
| **Později** | TD-14, TD-16, TD-17 | podle spouštěčů v [architektuře, sekce 7](architektura.md) |

## Splaceno

| ID | Kdy | Jak |
|---|---|---|
| CR-01 … CR-21 | 26. 10. 2026 | opravy z code review fáze 0 (záznam `jiz_nepotrebne/revize/2026-10-26-code-review.md`), každá s testem (kromě CR-12, CR-13 a CR-19, viz tam) |
| TD-18 | 26. 10. 2026 | dokumenty „Analýza“ (8.1, 8.3) a „Ostrovy“ (4.4, 5.2, 6.3, 6.4, 7.1, 7.3, 7.5) srovnány s kódem a ADR |
| TD-19 | 26. 10. 2026 | `app/platforma/kostra.py`; `ukazky.py` v provozním režimu selže; test `TestKostraVProvozu` |
| TD-08 | 1. 11. 2026 | migrace `004_prava_app_sklad.sql`: `DELETE` jen na `ObsahPozice` a `RoleOpravneni`, `DENY DELETE` na `SkladovaTransakce`; platí po `flask db upgrade` |
| TD-09 | 1. 11. 2026 | `Spojeni.jen_cteni`: `proved()`/`vloz()` v `@cteni` skončí chybou; AST pravidlo `TestCteni` v `tests/test_pravidla_ostrovu.py` |
| TD-12 | 1. 11. 2026 | aplikace nastavuje jen logger `houfek`, handler jednou (`TestLogovani`) |
| TD-15 | 1. 11. 2026 | `migrace_db.zamek_upgrade()`: `sp_getapplock` na relaci (`TestZamekUpgradu`) |
| CR-22 … CR-33 | 1.–2. 11. 2026 | opravy z code review 1. 11. včetně doplňku (záznam `jiz_nepotrebne/revize/2026-11-01-code-review.md`), každá s testem |
| TD-04 | 3. 11. 2026 | testovací SQL Server v Dockeru (`docker-compose.yml`), `nastroje/testovaci_db.py`, harness zakládá `HoufekSklad_TEST` s RCSI (`tests/test_integrace_harness.py`) |
| TD-11 | 3. 11. 2026 | **UTC jako jediná časová báze** (rozhodnutí vedoucího, před prvním spuštěním 001): v `DATETIME2` se ukládá UTC, DEFAULT `SYSUTCDATETIME()` (migrace 001, 002, `migrace_db.py`), aplikace bere čas `platforma.kontrakty.teď()` a najevo serializuje `Cas` pražským časem s posunem. Testy `TestCasovaKonvence` + `test_casove_defaulty_jsou_utc` |
| TD-25 | 9. 11. 2026 | migrace `005_rozhodnuti_9_11.sql`: `InventuraPolozka.PosledniPohybID` s cizím klíčem na `SkladovyPohyb` (rozhodnutí D-26, uzavírá i S-19); test `tests/integrace/test_migrace_005.py` |
