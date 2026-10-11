// Wysyłka faktury, odbiór wyniku i synchronizacja zmian (Node.js 18+: wbudowane fetch, FormData i Blob).
// Uruchom: node faktura.mjs faktura.xml        — wysyłka i odbiór wyniku (sposób A)
//          node faktura.mjs --sync [stan.json] — jeden przebieg synchronizacji (sposób B)
import { readFile, rename, writeFile } from "node:fs/promises";
import { basename } from "node:path";

const BASE_URL = "__API_BASE__/api/v1";
const API_KEY = process.env.XP_API_KEY;
const FINAL = new Set(["approved", "duplicate", "rejected"]);
const SYNC_START = "1970-01-01T00:00:00Z"; // pierwszy przebieg: pełna synchronizacja (albo data wdrożenia)
const SYNC_MARGIN_MS = 5 * 60 * 1000; // zapas na zmiany zatwierdzone w innej kolejności niż ich updated_at
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function call(method, path, body) {
  const res = await fetch(BASE_URL + path, {
    method,
    headers: { "X-API-Key": API_KEY },
    body,
    signal: AbortSignal.timeout(60_000),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = data.error ?? {};
    throw new Error(`HTTP ${res.status} ${err.code ?? "http_error"}: ${err.message ?? ""}`);
  }
  return data;
}

export async function sendInvoice(path) {
  const form = new FormData();
  form.append("file", new Blob([await readFile(path)]), basename(path));
  return call("POST", "/documents", form);
}

// Dla statusu "duplicate": id wcześniejszego dokumentu tej samej faktury (albo null).
export function originalId(doc) {
  const issue = (doc.issues ?? []).find((i) => i.code === "duplicate" && /^\d+$/.test(i.source_value ?? ""));
  return issue ? Number(issue.source_value) : null;
}

export async function waitForResult(id, { delay = 5, maxDelay = 300, timeout = 3600 } = {}) {
  const deadline = Date.now() + timeout * 1000;
  for (;;) {
    const doc = await call("GET", `/documents/${id}`);
    if (FINAL.has(doc.status)) return doc;
    if (Date.now() + delay * 1000 > deadline) return null; // zapisz id i sprawdź później
    await sleep(delay * 1000);
    delay = Math.min(delay * 2, maxDelay);
  }
}

async function loadState(path) {
  try {
    return JSON.parse(await readFile(path, "utf8"));
  } catch (e) {
    if (e.code === "ENOENT") return { last_sync: null, seen: {} }; // pierwszy przebieg
    throw e;
  }
}

// Czas API minus SYNC_MARGIN (Date ma dokładność do milisekund — przy odejmowaniu marginesu to bez znaczenia).
const minusMargin = (apiTime) => new Date(Date.parse(apiTime) - SYNC_MARGIN_MS).toISOString();

// Jeden przebieg synchronizacji: dokumenty zatwierdzone (także przez operatora w panelu) od ostatniego przebiegu.
// Stan w pliku: last_sync = największy odebrany updated_at, seen = przetworzone pary id → updated_at.
// Dostawa „co najmniej raz” — pary już przetworzone są pomijane, import ma być idempotentny (po id).
export async function syncApproved(statePath = "xp-sync.json") {
  const state = await loadState(statePath);
  const since = state.last_sync ? minusMargin(state.last_sync) : SYNC_START;
  const params = new URLSearchParams({ updated_since: since, status: "approved", limit: "500" });
  for (;;) {
    const page = await call("GET", `/documents?${params}`); // URLSearchParams koduje „+” jako %2B
    for (const item of page.items) {
      if (state.seen[item.id] === item.updated_at) continue; // już przetworzony (margines, granica updated_since)
      const doc = await call("GET", `/documents/${item.id}`); // pełny wynik z invoice
      console.log(`#${doc.id} ${doc.status} ${item.updated_at} ${doc.invoice?.number ?? ""}`);
      // tu zaimportuj doc.invoice do swojego systemu — idempotentnie (aktualizacja rekordu po id)
      state.seen[item.id] = item.updated_at; // updated_at jako tekst — Date obcięłoby mikrosekundy
      // czas zawsze w formacie API (6 cyfr ułamka i Z), więc porównanie tekstów = porównanie czasu
      if (!state.last_sync || item.updated_at > state.last_sync) state.last_sync = item.updated_at;
    }
    if (state.last_sync) { // pary sprzed okna marginesu już nie wrócą — plik stanu zostaje mały
      const cutoff = Date.parse(state.last_sync) - SYNC_MARGIN_MS;
      for (const [id, at] of Object.entries(state.seen)) if (Date.parse(at) < cutoff) delete state.seen[id];
    }
    await writeFile(`${statePath}.tmp`, JSON.stringify(state));
    await rename(`${statePath}.tmp`, statePath); // stan po każdej stronie; zapis atomowy
    if (!page.next_cursor) return state; // null = ostatnia strona
    params.set("cursor", page.next_cursor); // kolejna strona: te same parametry + kursor
  }
}

if (!API_KEY) throw new Error("Ustaw zmienną środowiskową XP_API_KEY");
if (process.argv[2] === "--sync") {
  await syncApproved(process.argv[3]);
} else {
  let doc = await sendInvoice(process.argv[2]);
  console.log(`Dokument #${doc.id}: ${doc.status}`);
  if (doc.status === "duplicate") console.log(`Duplikat dokumentu #${originalId(doc) ?? "?"} — użyj wyniku oryginału.`);
  else if (!FINAL.has(doc.status)) doc = (await waitForResult(doc.id)) ?? doc;
  if (doc.status === "approved") {
    const { number, totals, currency, lines } = doc.invoice;
    console.log(`${number}: ${totals.gross} ${currency}`);
    for (const line of lines) console.log(`  ${line.product_index}: ${line.qty} ${line.unit}`);
  }
}
