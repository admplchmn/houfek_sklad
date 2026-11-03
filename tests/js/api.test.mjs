// Testy api.js bez prohlížeče: node --test tests/js/api.test.mjs
// Hlídají ochranu proti dvojímu zápisu: po neznámém výsledku jde stejný požadavek se stejným requestId.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const KOD = readFileSync(new URL("../../app/platforma/ui/static/api.js", import.meta.url), "utf8");

function nactiApi(odpovedi) {
  const volani = [];
  const kontext = {
    crypto: globalThis.crypto,
    URLSearchParams,
    fetch: async (cesta, moznosti) => {
      volani.push({ cesta, telo: moznosti.body ? JSON.parse(moznosti.body) : undefined });
      const dalsi = odpovedi.shift();
      if (dalsi instanceof Error) throw dalsi;
      return {
        status: dalsi.status,
        json: async () => {
          if (dalsi.json === undefined) throw new SyntaxError("není JSON");
          return dalsi.json;
        },
      };
    },
  };
  vm.createContext(kontext);
  vm.runInContext(KOD + "\nglobalThis.api = api;", kontext);
  return { api: kontext.api, volani };
}

const OK = { status: 200, json: { success: true, code: "OK", message: "", data: {}, transakceId: "t", varovani: [] } };
const ODMITNUTO = { status: 409, json: { success: false, code: "INSUFFICIENT_STOCK", message: "", data: null, transakceId: null, varovani: [] } };

test("po výpadku sítě se opakuje stejný requestId", async () => {
  const { api, volani } = nactiApi([new TypeError("Failed to fetch"), OK]);
  const prvni = await api.post("/api/sklad/vydej", { zdrojKod: "BPLE037-A", pocetKs: 5 });
  assert.equal(prvni.code, "NETWORK_ERROR");
  await api.post("/api/sklad/vydej", { zdrojKod: "BPLE037-A", pocetKs: 5 });
  assert.equal(volani[0].telo.requestId, volani[1].telo.requestId);
});

test("po 504 z proxy bez obálky se opakuje stejný requestId", async () => {
  const { api, volani } = nactiApi([{ status: 504 }, OK]);
  const prvni = await api.post("/api/sklad/vydej", { zdrojKod: "BPLE037-A", pocetKs: 5 });
  assert.equal(prvni.code, "UNKNOWN_RESULT");
  await api.post("/api/sklad/vydej", { zdrojKod: "BPLE037-A", pocetKs: 5 });
  assert.equal(volani[0].telo.requestId, volani[1].telo.requestId);
});

test("po jisté odpovědi (OK i odmítnutí) má další požadavek nový requestId", async () => {
  const { api, volani } = nactiApi([OK, ODMITNUTO, OK]);
  await api.post("/api/sklad/vydej", { zdrojKod: "A", pocetKs: 1 });
  await api.post("/api/sklad/vydej", { zdrojKod: "A", pocetKs: 1 });
  await api.post("/api/sklad/vydej", { zdrojKod: "A", pocetKs: 1 });
  const ids = new Set(volani.map((v) => v.telo.requestId));
  assert.equal(ids.size, 3);
});

test("jiný obsah po výpadku dostane nový requestId", async () => {
  const { api, volani } = nactiApi([new TypeError("Failed to fetch"), OK]);
  await api.post("/api/sklad/vydej", { zdrojKod: "A", pocetKs: 1 });
  await api.post("/api/sklad/vydej", { zdrojKod: "A", pocetKs: 2 });
  assert.notEqual(volani[0].telo.requestId, volani[1].telo.requestId);
});

test("get skládá query a vynechá prázdné parametry", async () => {
  const { api, volani } = nactiApi([OK]);
  await api.get("/api/prehledy/pohyby", { dilId: 12, od: "", typ: null });
  assert.equal(volani[0].cesta, "/api/prehledy/pohyby?dilId=12");
});

test("REQUEST_IN_PROGRESS: výsledek prvního požadavku ještě neznáme, opakuje se stejný requestId", async () => {
  const PROBIHA = { status: 409, json: { success: false, code: "REQUEST_IN_PROGRESS", message: "", data: null, transakceId: null, varovani: [] } };
  const { api, volani } = nactiApi([PROBIHA, OK]);
  await api.post("/api/sklad/vydej", { zdrojKod: "A", pocetKs: 1 });
  await api.post("/api/sklad/vydej", { zdrojKod: "A", pocetKs: 1 });
  assert.equal(volani[0].telo.requestId, volani[1].telo.requestId);
});

test("po INTERNAL_ERROR 500 se opakuje stejný requestId (chyba mohla nastat po potvrzení)", async () => {
  const CHYBA = { status: 500, json: { success: false, code: "INTERNAL_ERROR", message: "", data: null, transakceId: null, varovani: [] } };
  const { api, volani } = nactiApi([CHYBA, OK]);
  await api.post("/api/sklad/vydej", { zdrojKod: "A", pocetKs: 1 });
  await api.post("/api/sklad/vydej", { zdrojKod: "A", pocetKs: 1 });
  assert.equal(volani[0].telo.requestId, volani[1].telo.requestId);
});
