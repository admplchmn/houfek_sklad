/* =============================================================================
   007 – Staging importu z XLSM pro ostrov H (kap. 5, docs/migrace-xlsm.md)
   Vlastník: Platforma (ostrov A). Zapisuje ostrov H (`flask migrace nacti`).
   -----------------------------------------------------------------------------
   1) Schéma stg patří ostrovu H: do dbo se z importu zapisuje jen přes rozhraní
      vlastníků. Skutečný XLSM v repozitáři není a nebude, proto staging nezná
      sloupce souboru – drží buňky 1:1, jedna neprázdná buňka = jeden řádek
      s hodnotou jako textem.
   2) stg.Davka: každé načtení je nová dávka, nic se nepřepisuje (proto ani
      žádná unikátnost nad názvem souboru). NactenoKdy je UTC (TD-11).
   3) stg.Bunka: souřadnice buňky (list, řádek, sloupec) jsou primární klíč,
      dvakrát tatáž buňka nedává smysl.
   4) app_sklad ze stg jen čte a zapisuje – žádné UPDATE ani DELETE, dávka musí
      zůstat tak, jak byla načtená.
   ============================================================================= */

SET XACT_ABORT ON;
GO

/* 1) Vlastní schéma – CREATE SCHEMA musí stát samo v dávce. */
CREATE SCHEMA stg;
GO

/* 2) Dávka = jedno načtení souboru. NacetlUzivatelID je NULL, když načítal
      skript bez přihlášeného obsluhujícího (CLI). */
CREATE TABLE stg.Davka (
    DavkaID          INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Davka PRIMARY KEY,
    Soubor           NVARCHAR(260) NOT NULL,
    NactenoKdy       DATETIME2 NOT NULL CONSTRAINT DF_Davka_NactenoKdy DEFAULT (SYSUTCDATETIME()),
    NacetlUzivatelID INT NULL CONSTRAINT FK_Davka_Uzivatel REFERENCES dbo.Uzivatel (UzivatelID)
);
GO

/* 3) Buňky 1:1 ze všech listů; List je název listu v sešitě. */
CREATE TABLE stg.Bunka (
    DavkaID INT NOT NULL CONSTRAINT FK_Bunka_Davka REFERENCES stg.Davka (DavkaID),
    List    NVARCHAR(100) NOT NULL,
    Radek   INT NOT NULL,
    Sloupec INT NOT NULL,
    Hodnota NVARCHAR(4000) NULL,
    CONSTRAINT PK_Bunka PRIMARY KEY (DavkaID, List, Radek, Sloupec)
);
GO

/* 4) Import jen přidává dávku a její buňky. */
GRANT  SELECT, INSERT ON SCHEMA::stg TO app_sklad;
GO
