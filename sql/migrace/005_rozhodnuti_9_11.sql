/* =============================================================================
   005 – Rozhodnutí vedoucího projektu z 9. 11. 2026: výchozí oprávnění rolí,
   způsob potvrzení cíle pohybu a inventura za provozu (D-18, D-23, D-26)
   Vlastník: Platforma (ostrov A).
   -----------------------------------------------------------------------------
   1) RoleOpravneni podle matice G4 (D-23) – všech 14 oprávnění, která už
      založily 001 a 002. Zápis přidává jen chybějící řádky, takže nevadí,
      když si role před ním nastavil někdo sám. Matice je i v
      docs/soulad-se-zadanim.md, sekce „Rozhodnutí vedoucího projektu“.
   2) SkladovyPohyb.ZpusobPotvrzeni (D-18, Q-15): SKEN = cíl ověřený skenem na
      terminálu, RUCNE = ruční potvrzení na PC s RUCNI_POTVRZENI (ověřuje
      server). NULL = pohyb bez potvrzení cíle (výdej, korekce, počáteční stav).
      Sloupec se plní jen při INSERT – role app_sklad má na SkladovyPohyb
      DENY UPDATE [Δ16].
   3) InventuraPolozka.PosledniPohybID (D-26, Q-16; TD-25, S-19): poslední
      pohyb pozice při fyzické kontrole položky. Při dokončení inventury se
      stav pozice i pohyby po tomto čísle ověří znovu ve stejné transakci.
   ============================================================================= */

SET XACT_ABORT ON;
GO

/* 1) Výchozí oprávnění rolí – matice G4 (D-23), přepsaná řádek za řádkem
      v pořadí, jak ji tabulka v dokumentaci uvádí. */
INSERT INTO dbo.RoleOpravneni (RoleID, OpravneniID)
SELECT r.RoleID, o.OpravneniID
FROM (VALUES
    ('OPER', 'DIL_CIST'), ('SKL', 'DIL_CIST'), ('MISTR', 'DIL_CIST'), ('TECH', 'DIL_CIST'), ('ADMIN', 'DIL_CIST'),
    ('OPER', 'SKLAD_PRIJEM'), ('SKL', 'SKLAD_PRIJEM'), ('MISTR', 'SKLAD_PRIJEM'), ('ADMIN', 'SKLAD_PRIJEM'),
    ('OPER', 'SKLAD_VYDEJ'), ('SKL', 'SKLAD_VYDEJ'), ('MISTR', 'SKLAD_VYDEJ'), ('ADMIN', 'SKLAD_VYDEJ'),
    ('SKL', 'SKLAD_PRESUN'), ('MISTR', 'SKLAD_PRESUN'), ('ADMIN', 'SKLAD_PRESUN'),
    ('SKL', 'INVENTURA'), ('MISTR', 'INVENTURA'), ('ADMIN', 'INVENTURA'),
    ('MISTR', 'KOREKCE'), ('ADMIN', 'KOREKCE'),
    ('ADMIN', 'BOX_EDIT'),
    ('ADMIN', 'UZIVATEL_EDIT'),
    ('SKL', 'BLOKACE'), ('MISTR', 'BLOKACE'), ('ADMIN', 'BLOKACE'),
    ('MISTR', 'RUCNI_POTVRZENI'), ('ADMIN', 'RUCNI_POTVRZENI'),
    ('MISTR', 'UPOZORNENI_UZAVRIT'), ('ADMIN', 'UPOZORNENI_UZAVRIT'),
    ('TECH', 'KMEN_EDIT'), ('ADMIN', 'KMEN_EDIT'),
    ('TECH', 'STAT_EDIT'), ('ADMIN', 'STAT_EDIT'),
    ('MISTR', 'AUDIT_CIST'), ('TECH', 'AUDIT_CIST'), ('ADMIN', 'AUDIT_CIST')
) AS m (KodRole, KodOpravneni)
JOIN dbo.Role      AS r ON r.KodRole      = m.KodRole
JOIN dbo.Opravneni AS o ON o.KodOpravneni = m.KodOpravneni
WHERE NOT EXISTS (SELECT 1 FROM dbo.RoleOpravneni AS ro
                  WHERE ro.RoleID = r.RoleID AND ro.OpravneniID = o.OpravneniID);
GO

/* 2) Jak byl ověřen cíl pohybu (D-18). NULL záměrně není porušení CHECK –
      výdej, korekce a počáteční stav cíl nepotvrzují. */
ALTER TABLE dbo.SkladovyPohyb
    ADD ZpusobPotvrzeni VARCHAR(10) NULL
        CONSTRAINT CK_SkladovyPohyb_ZpusobPotvrzeni CHECK (ZpusobPotvrzeni COLLATE Latin1_General_BIN IN ('SKEN', 'RUCNE'));   -- [Δ8]
GO

/* 3) Kontrola inventury za provozu (D-26): položka si při fyzické kontrole
      uloží poslední pohyb pozice, podle něj pozná změny do dokončení. */
ALTER TABLE dbo.InventuraPolozka
    ADD PosledniPohybID BIGINT NULL
        CONSTRAINT FK_InventuraPolozka_SkladovyPohyb FOREIGN KEY (PosledniPohybID) REFERENCES dbo.SkladovyPohyb (PohybID);
GO
