<?php
// Wysyłka faktury, odbiór wyniku i synchronizacja zmian (PHP 8, rozszerzenie curl).
// Użycie: php faktura.php faktura.xml        — wysyłka i odbiór wyniku (sposób A)
//         php faktura.php --sync [stan.json] — jeden przebieg synchronizacji (sposób B)
const BASE_URL = '__API_BASE__/api/v1';
const FINAL_STATUSES = ['approved', 'duplicate', 'rejected'];
const SYNC_START = '1970-01-01T00:00:00Z'; // pierwszy przebieg: pełna synchronizacja (albo data wdrożenia)
const SYNC_MARGIN = '-5 minutes';          // zapas na zmiany zatwierdzone w innej kolejności niż ich updated_at

function xp_call(string $method, string $path, ?array $post = null): array {
    $key = getenv('XP_API_KEY');
    if ($key === false || $key === '') {
        throw new RuntimeException('Ustaw zmienną środowiskową XP_API_KEY');
    }
    $ch = curl_init(BASE_URL . $path);
    curl_setopt_array($ch, [
        CURLOPT_CUSTOMREQUEST => $method,
        CURLOPT_HTTPHEADER => ['X-API-Key: ' . $key],
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 60,
    ]);
    if ($post !== null) {
        curl_setopt($ch, CURLOPT_POSTFIELDS, $post); // tablica z CURLFile => multipart/form-data
    }
    $body = curl_exec($ch);
    if ($body === false) {
        $err = curl_error($ch);
        curl_close($ch);
        throw new RuntimeException("Błąd połączenia: $err"); // sieć/timeout — można ponowić
    }
    $status = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    curl_close($ch);
    $data = json_decode($body, true);
    if ($status >= 400) {
        $code = $data['error']['code'] ?? 'http_error';
        $msg = $data['error']['message'] ?? substr($body, 0, 200);
        throw new RuntimeException("HTTP $status $code: $msg", $status);
    }
    return $data;
}

function send_invoice(string $path): array {
    return xp_call('POST', '/documents', ['file' => new CURLFile($path, '', basename($path))]);
}

// Dla statusu 'duplicate': id wcześniejszego dokumentu tej samej faktury (albo null).
function original_id(array $doc): ?int {
    foreach ($doc['issues'] ?? [] as $issue) {
        if ($issue['code'] === 'duplicate' && ctype_digit((string) ($issue['source_value'] ?? ''))) {
            return (int) $issue['source_value'];
        }
    }
    return null;
}

function wait_for_result(int $id, int $delay = 5, int $maxDelay = 300, int $timeout = 3600): ?array {
    $deadline = time() + $timeout;
    while (true) {
        $doc = xp_call('GET', "/documents/$id");
        if (in_array($doc['status'], FINAL_STATUSES, true)) {
            return $doc;
        }
        if (time() + $delay > $deadline) {
            return null; // zapisz id i sprawdź później
        }
        sleep($delay);
        $delay = min($delay * 2, $maxDelay);
    }
}

// Czas API ('2026-10-11T06:04:38.312308Z') przesunięty o SYNC_MARGIN, w tym samym formacie.
function minus_margin(string $apiTime): string {
    return (new DateTimeImmutable($apiTime))->modify(SYNC_MARGIN)->format('Y-m-d\TH:i:s.u\Z');
}

// Jeden przebieg synchronizacji: dokumenty zatwierdzone (także przez operatora w panelu) od ostatniego przebiegu.
// Stan w pliku: last_sync = największy odebrany updated_at, seen = przetworzone pary id => updated_at.
// Dostawa „co najmniej raz” — pary już przetworzone są pomijane, import ma być idempotentny (po id).
function sync_approved(string $statePath = 'xp-sync.json'): void {
    $state = is_file($statePath)
        ? json_decode(file_get_contents($statePath), true, 512, JSON_THROW_ON_ERROR)
        : ['last_sync' => null, 'seen' => []];
    $query = [
        'updated_since' => $state['last_sync'] !== null ? minus_margin($state['last_sync']) : SYNC_START,
        'status' => 'approved',
        'limit' => 500,
    ];
    do {
        $page = xp_call('GET', '/documents?' . http_build_query($query)); // http_build_query koduje „+” jako %2B
        foreach ($page['items'] as $item) {
            if (($state['seen'][$item['id']] ?? null) === $item['updated_at']) {
                continue; // już przetworzony: powtórka z marginesu albo z granicy updated_since
            }
            $doc = xp_call('GET', "/documents/{$item['id']}"); // pełny wynik z invoice
            echo "#{$doc['id']} {$doc['status']} {$item['updated_at']} " . ($doc['invoice']['number'] ?? '') . "\n";
            // tu zaimportuj $doc['invoice'] do swojego systemu — idempotentnie (aktualizacja rekordu po id)
            $state['seen'][$item['id']] = $item['updated_at'];
            // czas zawsze w formacie API (6 cyfr ułamka i Z), więc porównanie tekstów = porównanie czasu
            if ($state['last_sync'] === null || strcmp($item['updated_at'], $state['last_sync']) > 0) {
                $state['last_sync'] = $item['updated_at'];
            }
        }
        if ($state['last_sync'] !== null) { // pary sprzed okna marginesu już nie wrócą — plik stanu zostaje mały
            $cutoff = minus_margin($state['last_sync']);
            $state['seen'] = array_filter($state['seen'], fn ($at) => strcmp($at, $cutoff) >= 0);
        }
        file_put_contents("$statePath.tmp", json_encode($state, JSON_FORCE_OBJECT)); // pusty seen jako {}, nie []
        rename("$statePath.tmp", $statePath); // stan po każdej stronie; zapis atomowy
        $query['cursor'] = $page['next_cursor']; // kolejna strona: te same parametry + kursor
    } while ($page['next_cursor'] !== null);
}

if (($argv[1] ?? '') === '--sync') {
    sync_approved($argv[2] ?? 'xp-sync.json');
    exit(0);
}
$doc = send_invoice($argv[1]);
echo "Dokument #{$doc['id']}: {$doc['status']}\n";
if ($doc['status'] === 'duplicate') {
    echo 'Duplikat dokumentu #' . (original_id($doc) ?? '?') . " — użyj wyniku oryginału.\n";
} elseif (!in_array($doc['status'], FINAL_STATUSES, true)) {
    $doc = wait_for_result($doc['id']) ?? $doc;
}
if ($doc['status'] === 'approved') {
    $invoice = $doc['invoice'];
    echo "{$invoice['number']}: {$invoice['totals']['gross']} {$invoice['currency']}\n";
    foreach ($invoice['lines'] as $line) {
        echo "  {$line['product_index']}: {$line['qty']} {$line['unit']}\n";
    }
}
