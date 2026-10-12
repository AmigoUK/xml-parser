<?php
// Odbiorca webhooka parsera faktur — PHP 8+, jeden plik, bez zależności.
//
// Parser wysyła POST z JSON-em i nagłówkami:
//   X-XP-Timestamp  czas wysyłki (sekundy unixowe, tekst)
//   X-XP-Signature  sha256=<hex HMAC-SHA256(sekret, "<timestamp>.<surowe bajty ciała>")>
//   X-XP-Delivery   identyfikator dostawy (UUID) — taki sam przy ponowieniach; użyj go jako klucza idempotencji
//
// Sekret bierz ze zmiennej XP_WEBHOOK_SECRET (nie wpisuj go w kodzie).
//
// Tryby:
//   XP_WEBHOOK_SECRET=... php -S 0.0.0.0:9000 webhook-odbiorca.php     serwer HTTP (wbudowany serwer PHP)
//   php webhook-odbiorca.php --check <ts> <podpis> < ciało.json        weryfikacja bez sieci: OK / powód, kod 0 / 1
//                                                                      (opcjonalnie --now <ts> zamiast zegara)

const MAX_SKEW = 300; // sekundy: starsze lub „z przyszłości” żądania odrzucamy (ochrona przed powtórzeniem)

/** null, gdy podpis jest poprawny; w przeciwnym razie powód odrzucenia (po polsku). */
function verify(string $secret, string $timestamp, string $signature, string $body, ?int $now = null): ?string
{
    if (!preg_match('/^-?\d+$/', $timestamp)) {
        return 'nieprawidłowy znacznik czasu';
    }
    if (abs(($now ?? time()) - (int) $timestamp) > MAX_SKEW) {
        return 'znacznik czasu poza dopuszczalnym oknem ' . MAX_SKEW . ' s';
    }
    // Podpis liczymy z SUROWYCH bajtów ciała — nie z ponownie zserializowanego JSON-a.
    $expected = 'sha256=' . hash_hmac('sha256', $timestamp . '.' . $body, $secret);
    if (!hash_equals($expected, $signature)) { // porównanie w stałym czasie
        return 'nieprawidłowy podpis';
    }
    return null;
}

$secret = getenv('XP_WEBHOOK_SECRET') ?: '';

if (PHP_SAPI === 'cli') {
    if ($secret === '') {
        fwrite(STDERR, "Ustaw zmienną XP_WEBHOOK_SECRET (sekret webhooka z panelu).\n");
        exit(2);
    }
    $at = array_search('--check', $argv, true);
    if ($at === false) {
        fwrite(STDERR, "Serwer: XP_WEBHOOK_SECRET=... php -S 0.0.0.0:9000 webhook-odbiorca.php\n"
            . "Weryfikacja: php webhook-odbiorca.php --check <ts> <podpis> < ciało.json\n");
        exit(2);
    }
    $nowAt = array_search('--now', $argv, true);
    $reason = verify($secret, $argv[$at + 1] ?? '', $argv[$at + 2] ?? '', stream_get_contents(STDIN),
        $nowAt === false ? null : (int) ($argv[$nowAt + 1] ?? 0));
    echo ($reason ?? 'OK') . "\n";
    exit($reason === null ? 0 : 1);
}

// --- tryb serwera (php -S) ---
function reply(int $code, string $text): void
{
    http_response_code($code);
    header('Content-Type: text/plain; charset=utf-8');
    echo $text;
}

function log_line(string $line): void
{
    file_put_contents('php://stderr', $line . "\n"); // wbudowany serwer pokazuje stderr w konsoli
}

if ($secret === '') {
    return reply(500, 'brak XP_WEBHOOK_SECRET');
}
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    return reply(405, 'tylko POST');
}
$body = file_get_contents('php://input'); // surowe bajty
$reason = verify($secret, $_SERVER['HTTP_X_XP_TIMESTAMP'] ?? '', $_SERVER['HTTP_X_XP_SIGNATURE'] ?? '', $body);
if ($reason !== null) {
    log_line("odrzucono: $reason");
    return reply(401, $reason);
}
// Dopiero po weryfikacji przetwarzamy treść. Odpowiadaj szybko (2xx); ciężką pracę zlecaj w tle.
// Dostawa może przyjść ponownie z tym samym X-XP-Delivery — zapisuj go i pomijaj duplikaty.
$data = json_decode($body, true);
if (!is_array($data)) {
    return reply(400, 'ciało nie jest JSON-em');
}
if (($data['event'] ?? null) === 'webhook.test') {
    log_line('test OK');
} else {
    log_line(sprintf('event=%s id=%s status=%s delivery=%s', $data['event'] ?? '', $data['id'] ?? '',
        $data['status'] ?? '', $_SERVER['HTTP_X_XP_DELIVERY'] ?? ''));
}
reply(200, 'ok');
