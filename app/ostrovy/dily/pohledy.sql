/* NÁVRH pohledu ostrova D – vlastník doladí ve fázi 0, Platforma zařadí do migrace 003 (P11).
   Kód velikosti čte z pohledu v_VelikostPozice ostrova C (P2), proto vzniká až po něm.
   Sloupce jsou kontrakt: po zmrazení se jen přidávají (P10). */

CREATE VIEW dbo.v_Dil
AS
SELECT d.DilID,
       d.IdentifikacniCislo,
       d.NazevDilu,
       d.MaterialID,                         -- ID pro filtry ostrova Přehledy (filtry jsou ID, 4.2)
       m.KodMaterialu,
       d.TloustkaID,
       t.TloustkaMM,
       d.PrvniOperaceID,
       o.KodOperace        AS KodPrvniOperace,
       d.StandardniDavkaKs,
       d.VelikostPoziceID,
       vp.KodVelikosti     AS Velikost,
       d.PotrebnaDelkaMM,
       d.PotrebnaHloubkaMM,
       d.VaultVykresURL,
       d.Aktivni
FROM dbo.Dil AS d
LEFT JOIN dbo.Material            AS m  ON m.MaterialID        = d.MaterialID
LEFT JOIN dbo.TloustkaMaterialu   AS t  ON t.TloustkaID        = d.TloustkaID
LEFT JOIN dbo.PrvniVyrobniOperace AS o  ON o.PrvniOperaceID    = d.PrvniOperaceID
LEFT JOIN dbo.v_VelikostPozice    AS vp ON vp.VelikostPoziceID = d.VelikostPoziceID;
GO
