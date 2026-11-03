// HOUFEK Sklad – volání API z obrazovek (sekce 6.5 dokumentu Ostrovy).
// api.get(cesta, parametry) · api.post(cesta, telo, tlacitko) · api.patch(cesta, telo, tlacitko)
// Každá odpověď se vykreslí do panelu „Odpověď API“ a funkce vrátí celou obálku.
"use strict";

const api = (() => {
  // Odpovědi, u kterých nevíme, jestli server operaci provedl (proxy timeout, výpadek, ne-JSON,
  // 500 – chyba mohla nastat až po potvrzení transakce). Stejný požadavek pak musí jít znovu
  // se STEJNÝM requestId – server ho nezapíše dvakrát, jen vrátí uložený výsledek.
  const NEZNAMY_VYSLEDEK = new Set([0, 500, 502, 503, 504]);
  // Stejný requestId právě zpracovává server – výsledek ještě neznáme (docs/adr/0004).
  const PROBIHA = "REQUEST_IN_PROGRESS";

  function uuid4() {
    const c = globalThis.crypto;
    if (c && c.randomUUID) return c.randomUUID();
    const b = c.getRandomValues(new Uint8Array(16));   // i na http:// bez HTTPS
    b[6] = (b[6] & 0x0f) | 0x40;
    b[8] = (b[8] & 0x3f) | 0x80;
    const h = [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
    return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
  }

  let nedokonceny = null;   // { klic, requestId } – poslední POST s neznámým výsledkem

  function vykresli(obalka, status) {
    const panel = typeof document !== "undefined" ? document.getElementById("odpoved-api") : null;
    if (!panel) return;
    panel.className = "odpoved " + (obalka.success ? "ok" : "chyba");
    panel.querySelector(".kod").textContent = `${obalka.code}${status ? " · HTTP " + status : ""}`;
    panel.querySelector(".zprava").textContent = obalka.message || "";
    const varovani = panel.querySelector(".varovani");
    varovani.innerHTML = "";
    for (const v of obalka.varovani || []) {
      const li = document.createElement("li");
      li.textContent = `${v.code}: ${v.message}`;
      varovani.appendChild(li);
    }
    panel.querySelector(".transakce").textContent = obalka.transakceId ? `Transakce ${obalka.transakceId}` : "";
    panel.querySelector("pre").textContent = JSON.stringify(obalka, null, 2);
  }

  function chybovaObalka(code, message) {
    return { success: false, code, message, data: null, transakceId: null, varovani: [] };
  }

  // Vrací { obalka, status, jisty }: jisty = server prokazatelně odpověděl obálkou (operace
  // buď proběhla, nebo byla odmítnuta); jinak výsledek neznáme.
  async function zavolej(metoda, cesta, telo, tlacitko) {
    if (tlacitko) tlacitko.disabled = true;
    try {
      const moznosti = { method: metoda, credentials: "same-origin", headers: { Accept: "application/json" } };
      if (telo !== undefined) {
        moznosti.headers["Content-Type"] = "application/json";
        moznosti.body = JSON.stringify(telo);
      }
      let odpoved;
      try {
        odpoved = await fetch(cesta, moznosti);
      } catch (chyba) {
        const obalka = chybovaObalka("NETWORK_ERROR", "Server není dostupný: " + chyba.message);
        vykresli(obalka, 0);
        return { obalka, status: 0, jisty: false };
      }
      let obalka = null;
      try {
        obalka = await odpoved.json();
      } catch {
        obalka = null;
      }
      const platna = obalka && typeof obalka === "object" && "success" in obalka && "code" in obalka;
      if (!platna) {
        obalka = chybovaObalka("UNKNOWN_RESULT", `Server odpověděl HTTP ${odpoved.status} bez obálky – výsledek není jistý, zkuste to znovu.`);
      }
      vykresli(obalka, odpoved.status);
      const jisty = platna && !NEZNAMY_VYSLEDEK.has(odpoved.status) && obalka.code !== PROBIHA;
      return { obalka, status: odpoved.status, jisty };
    } finally {
      if (tlacitko) tlacitko.disabled = false;
    }
  }

  async function post(cesta, telo = {}, tlacitko) {
    const klic = cesta + "|" + JSON.stringify(telo);
    const requestId = nedokonceny && nedokonceny.klic === klic ? nedokonceny.requestId : uuid4();
    const { obalka, jisty } = await zavolej("POST", cesta, { requestId, ...telo }, tlacitko);
    nedokonceny = jisty ? null : { klic, requestId };
    return obalka;
  }

  async function get(cesta, parametry) {
    const query = parametry
      ? "?" + new URLSearchParams(Object.entries(parametry).filter(([, v]) => v !== "" && v != null))
      : "";
    return (await zavolej("GET", cesta + query)).obalka;
  }

  async function patch(cesta, telo, tlacitko) {
    return (await zavolej("PATCH", cesta, telo, tlacitko)).obalka;
  }

  return { get, post, patch, uuid4 };
})();
