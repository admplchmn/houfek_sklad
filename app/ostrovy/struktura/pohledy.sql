/* NÁVRH pohledu ostrova C – vlastník doladí ve fázi 0, Platforma zařadí do migrace 003 (P11).
   v_Misto musí vzniknout dřív než v_ZasobaDilu (ostrov E), v_VelikostPozice dřív než v_Dil (ostrov D).
   Sloupce jsou kontrakt: po zmrazení se jen přidávají (P10). */

CREATE VIEW dbo.v_VelikostPozice
AS
SELECT VelikostPoziceID, KodVelikosti, Nazev, Poradi, PlochaMM2
FROM dbo.VelikostPozice;
GO

CREATE VIEW dbo.v_Misto
AS
SELECT v.VnitrniPoziceID,
       v.KodPozice,
       CONCAT(b.KodBoxu, '-', v.KodPozice)                     AS KodMista,       -- BPLE037-A
       b.BoxID,
       b.KodBoxu,
       t.KodTypu                                               AS TypBoxu,        -- DYN | STAT
       c.KodCleneni,
       vp.KodVelikosti                                         AS Velikost,       -- V1..V6
       vp.Poradi                                               AS PoradiVelikosti,
       v.DelkaMM                                               AS RozmerC7DelkaMM,
       v.HloubkaMM                                             AS RozmerC7HloubkaMM,
       CAST(CASE WHEN b.Blokovany = 1 OR v.Blokovany = 1 THEN 1 ELSE 0 END AS BIT) AS Blokovano,
       s.Poradi                                                AS PoradiVBoxu,
       p.PoziceID,
       p.Poradi                                                AS PoradiBoxu,
       u.UrovenID,
       u.KodUrovne,
       r.RegalID,
       r.KodRegalu,
       pr.PracovisteID,
       pr.KodPracoviste,
       CONCAT(b.FullBoxKlic, '-', v.KodPozice)                 AS Adresa          -- HOUFEK-PLE-R01-U03-BPLE037-A
FROM dbo.VnitrniPoziceBoxu AS v
JOIN dbo.Box            AS b  ON b.BoxID             = v.BoxID
JOIN dbo.TypBoxu        AS t  ON t.TypBoxuID         = b.TypBoxuID
JOIN dbo.CleneniBoxu    AS c  ON c.CleneniBoxuID     = b.CleneniBoxuID
JOIN dbo.VelikostPozice AS vp ON vp.VelikostPoziceID = v.VelikostPoziceID
JOIN dbo.SablonaCleneni AS s  ON s.SablonaCleneniID  = v.SablonaCleneniID
JOIN dbo.Pozice         AS p  ON p.PoziceID          = b.PoziceID
JOIN dbo.Uroven         AS u  ON u.UrovenID          = p.UrovenID
JOIN dbo.Regal          AS r  ON r.RegalID           = u.RegalID
JOIN dbo.Pracoviste     AS pr ON pr.PracovisteID     = r.PracovisteID
WHERE v.Aktivni = 1 AND b.Aktivni = 1;
GO
