// Wysyłka faktury i odbiór wyniku (Node.js 18+: wbudowane fetch, FormData i Blob).
// Uruchom: node faktura.mjs faktura.xml
import { readFile } from "node:fs/promises";
import { basename } from "node:path";

const BASE_URL = "__API_BASE__/api/v1";
const API_KEY = process.env.XP_API_KEY;
const FINAL = new Set(["approved", "duplicate", "rejected"]);
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

if (!API_KEY) throw new Error("Ustaw zmienną środowiskową XP_API_KEY");
let doc = await sendInvoice(process.argv[2]);
console.log(`Dokument #${doc.id}: ${doc.status}`);
if (!FINAL.has(doc.status)) doc = (await waitForResult(doc.id)) ?? doc;
if (doc.status === "approved") {
  const { number, totals, currency, lines } = doc.invoice;
  console.log(`${number}: ${totals.gross} ${currency}`);
  for (const line of lines) console.log(`  ${line.product_index}: ${line.qty} ${line.unit}`);
}
