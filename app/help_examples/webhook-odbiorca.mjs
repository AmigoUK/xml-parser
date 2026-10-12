#!/usr/bin/env node
// Odbiorca webhooka parsera faktur — Node.js 18+ (node:http, node:crypto, bez zależności).
//
// Parser wysyła POST z JSON-em i nagłówkami:
//   X-XP-Timestamp  czas wysyłki (sekundy unixowe, tekst)
//   X-XP-Signature  sha256=<hex HMAC-SHA256(sekret, "<timestamp>.<surowe bajty ciała>")>
//   X-XP-Delivery   identyfikator dostawy (UUID) — taki sam przy ponowieniach; użyj go jako klucza idempotencji
//
// Sekret bierz ze zmiennej XP_WEBHOOK_SECRET (nie wpisuj go w kodzie).
//
//
// Ochrona przed powtórzeniem (replay): podpis obejmuje tylko „<timestamp>.<ciało>”, bez nagłówka X-XP-Delivery,
// więc w oknie ±300 s identyczne żądanie można przesłać ponownie. Deduplikuj po X-XP-Delivery WYŁĄCZNIE PO
// pozytywnej weryfikacji podpisu (inaczej ktoś bez sekretu mógłby „zająć” cudzy identyfikator), przechowuj
// widziane identyfikatory trwale (np. tabela webhook_deliveries_seen z unikalnym kluczem albo zbiór w Redis
// z TTL > 300 s) i powtórzony identyfikator traktuj jak sukces: odpowiedz 200 bez ponownego przetwarzania.
//
// Tryby:
//   node webhook-odbiorca.mjs --port 9000                          serwer HTTP (domyślnie port 9000)
//   node webhook-odbiorca.mjs --check <ts> <podpis> < ciało.json   weryfikacja bez sieci: OK / powód, kod 0 / 1
//                                                                  (opcjonalnie --now <ts> zamiast zegara)
import { createHmac, timingSafeEqual } from "node:crypto";
import { createServer } from "node:http";

const MAX_BODY = 1024 * 1024; // 1 MiB: większe ciało odrzucamy (413)
const seen = new Set(); // ilustracja; w produkcji trwały magazyn (tabela / Redis), nie pamięć procesu
const MAX_SKEW = 300; // sekundy: starsze lub „z przyszłości” żądania odrzucamy (ochrona przed powtórzeniem)

/** null, gdy podpis jest poprawny; w przeciwnym razie powód odrzucenia (po polsku). */
function verify(secret, timestamp, signature, body, now = Math.floor(Date.now() / 1000)) {
  if (!/^-?\d+$/.test(timestamp ?? "")) return "nieprawidłowy znacznik czasu";
  if (Math.abs(now - Number(timestamp)) > MAX_SKEW) return `znacznik czasu poza dopuszczalnym oknem ${MAX_SKEW} s`;
  // Podpis liczymy z SUROWYCH bajtów ciała (Buffer) — nie z ponownie zserializowanego JSON-a.
  const mac = createHmac("sha256", secret).update(`${timestamp}.`).update(body).digest("hex");
  const expected = Buffer.from(`sha256=${mac}`);
  const given = Buffer.from(signature ?? "");
  // timingSafeEqual wymaga równych długości; porównanie w stałym czasie
  if (given.length !== expected.length || !timingSafeEqual(given, expected)) return "nieprawidłowy podpis";
  return null;
}

async function readBody(stream, limit = Infinity) {
  const chunks = [];
  let size = 0;
  for await (const chunk of stream) {
    size += chunk.length;
    if (size > limit) throw new RangeError("za duże ciało");
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

function option(args, name) {
  const i = args.indexOf(name);
  return i === -1 ? undefined : args[i + 1];
}

const args = process.argv.slice(2);
const secret = process.env.XP_WEBHOOK_SECRET ?? "";
if (!secret) {
  console.error("Ustaw zmienną XP_WEBHOOK_SECRET (sekret webhooka z panelu).");
  process.exit(2);
}

const checkAt = args.indexOf("--check");
if (checkAt !== -1) {
  const now = option(args, "--now");
  const reason = verify(secret, args[checkAt + 1], args[checkAt + 2], await readBody(process.stdin),
    now === undefined ? undefined : Number(now));
  console.log(reason ?? "OK");
  process.exit(reason ? 1 : 0);
}

const port = Number(option(args, "--port") ?? 9000);
createServer(async (req, res) => {
  const reply = (code, text) => { res.writeHead(code, { "Content-Type": "text/plain; charset=utf-8" }); res.end(text); };
  try {
    if (req.method !== "POST") return reply(405, "tylko POST");
    let body;
    try { body = await readBody(req, MAX_BODY); } catch { return reply(413, "ciało zbyt duże"); }
    const reason = verify(secret, req.headers["x-xp-timestamp"], req.headers["x-xp-signature"], body);
    if (reason) {
      console.log(`odrzucono: ${reason}`);
      return reply(401, reason);
    }
    // Dopiero po weryfikacji przetwarzamy treść. Odpowiadaj szybko (2xx); ciężką pracę zlecaj w tle.
    let data;
    try { data = JSON.parse(body.toString("utf8")); } catch { return reply(400, "ciało nie jest JSON-em"); }
    if (typeof data !== "object" || data === null || Array.isArray(data)) return reply(400, "ciało musi być obiektem JSON");
    const delivery = req.headers["x-xp-delivery"] ?? "";
    if (seen.has(delivery)) return reply(200, "ok (duplikat)"); // powtórzona dostawa: sukces bez przetwarzania
    seen.add(delivery);
    if (data.event === "webhook.test") console.log("test OK");
    else console.log(`event=${data.event} id=${data.id} status=${data.status} delivery=${delivery}`);
    reply(200, "ok");
  } catch (err) { // nieoczekiwany błąd nie może zabić procesu; parser ponowi dostawę
    console.error(err);
    if (!res.headersSent) reply(500, "błąd wewnętrzny");
  }
}).listen(port, () => console.log(`Nasłuch na porcie ${port} (Ctrl+C kończy)`));
