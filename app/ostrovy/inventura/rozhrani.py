"""Ostrov F – Inventura je koncový ostrov: nic nepublikuje ostatním (sekce 7.6).

Používá: struktura (pozice_v_rozsahu, nacti_mista, zamkni_mista, vejde_se),
dily (nacti_dily), sklad (obsah_mist, posledni_pohyby, stat_mista, zauctuj_korekci).
Rozhodnuto: Q-16 = D-26, Q-17 se S-22 = D-27. InventuraPolozka.PosledniPohybID je v migraci 005,
stav položky se jen počítá (do tabulky se nikam neukládá) a dokončení zaúčtuje korekce a zavře ji.
"""
