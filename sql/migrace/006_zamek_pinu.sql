/* =============================================================================
   006 – Zámek PINu a nečinnost na terminálu: rozhodnutí D-33 (TD-07) a D-34 (TD-06)
   Vlastník: Platforma (ostrov A). Logiku přihlášení dopisuje ostrov B.
   -----------------------------------------------------------------------------
   1) Uzivatel.ChybnePokusy a Uzivatel.ZamcenoDo (D-33): pět chybných PINů po sobě
      zamkne účet na 15 minut. Počítadlo sbírá chyby jdoucí za sebou a úspěšné
      přihlášení ho vynuluje; ZamcenoDo je čas v UTC (TD-11), NULL = nezamčený účet.
      Odemyká ADMIN, samotné pokusy se zapisují bez PINu (oddíl 2).
   2) dbo.PrihlaseniPokus: historie pokusů o přihlášení. Hledané osobní číslo se
      ukládá vždy, UzivatelID a TerminalID se vyplní jen tehdy, když ten který
      řádek existoval. Otevřený PIN se nikde neuchovává.
   3) app_sklad do PrihlaseniPokus jen přidává – DENY UPDATE a DELETE jako u
      SkladovyPohyb a AuditZmen [Δ16], aby pokus zůstal dohledat i po chybě v kódu.
   ============================================================================= */

SET XACT_ABORT ON;
GO

/* 1) Počítadlo chybných PINů a zámek účtu. Obě hodnoty mají výchozí stav, proto
      existující uživatelé končí s nulovým počtem pokusů a bez zámku. */
ALTER TABLE dbo.Uzivatel
    ADD ChybnePokusy INT NOT NULL CONSTRAINT DF_Uzivatel_ChybnePokusy DEFAULT (0)
            CONSTRAINT CK_Uzivatel_ChybnePokusy CHECK (ChybnePokusy >= 0),
        ZamcenoDo    DATETIME2 NULL;
GO

/* 2) Pokusy o přihlášení (D-33: „pokusy se auditují bez PINu"). Vysledek je jeden
      z pěti kódů: USPECH, CHYBNY_PIN, ZAMCENO (zámek už trval), NEZNAMY (osobní
      číslo nikoho nenalezlo), NEAKTIVNI (nalezený, ale deaktivovaný uživatel). */
CREATE TABLE dbo.PrihlaseniPokus (
    PokusID         BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_PrihlaseniPokus PRIMARY KEY,
    DatumCas        DATETIME2 NOT NULL CONSTRAINT DF_PrihlaseniPokus_DatumCas DEFAULT (SYSUTCDATETIME()),
    OsobniCislo     VARCHAR(30) NOT NULL,        -- hledané číslo, i když uživatel neexistuje
    UzivatelID      INT NULL CONSTRAINT FK_PrihlaseniPokus_Uzivatel REFERENCES dbo.Uzivatel (UzivatelID),
    TerminalID      INT NULL CONSTRAINT FK_PrihlaseniPokus_Terminal REFERENCES dbo.Terminal (TerminalID),
    Vysledek        VARCHAR(20) NOT NULL,
    CONSTRAINT CK_PrihlaseniPokus_Vysledek CHECK (Vysledek COLLATE Latin1_General_BIN IN ('USPECH', 'CHYBNY_PIN', 'ZAMCENO', 'NEZNAMY', 'NEAKTIVNI'))   -- [Δ8]
);
GO

/* 3) Historie pokusů se jen zapisuje, proto stejné právo jako u SkladovyPohyb a AuditZmen. */
DENY   UPDATE, DELETE ON OBJECT::dbo.PrihlaseniPokus TO app_sklad;
GO
