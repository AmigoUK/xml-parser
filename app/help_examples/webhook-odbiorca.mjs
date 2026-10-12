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
// Tryby:
//   node webhook-odbiorca.mjs --port 9000                          serwer HTTP (domyślnie port 9000)
//   node webhook-odbiorca.mjs --check <ts> <podpis> < ciało.json   weryfikacja bez sieci: OK / powód, kod 0 / 1
//                                                                  (opcjonalnie --now <ts> zamiast zegara)
import { createHmac, timingSafeEqual } from "node:crypto";
import { createServer } from "node:http";

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

async function readBody(stream) {
  const chunks = [];
  for await (const chunk of stream) chunks.push(chunk);
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
  if (req.method !== "POST") return reply(405, "tylko POST");
  const body = await readBody(req);
  const reason = verify(secret, req.headers["x-xp-timestamp"], req.headers["x-xp-signature"], body);
  if (reason) {
    console.log(`odrzucono: ${reason}`);
    return reply(401, reason);
  }
  // Dopiero po weryfikacji przetwarzamy treść. Odpowiadaj szybko (2xx); ciężką pracę zlecaj w tle.
  // Dostawa może przyjść ponownie z tym samym X-XP-Delivery — zapisuj go i pomijaj duplikaty.
  let data;
  try { data = JSON.parse(body.toString("utf8")); } catch { return reply(400, "ciało nie jest JSON-em"); }
  if (data.event === "webhook.test") console.log("test OK");
  else console.log(`event=${data.event} id=${data.id} status=${data.status} delivery=${req.headers["x-xp-delivery"]}`);
  reply(200, "ok");
}).listen(port, () => console.log(`Nasłuch na porcie ${port} (Ctrl+C kończy)`));
