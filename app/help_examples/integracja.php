<?php
// Wysyłka faktury i odbiór wyniku (PHP 8, rozszerzenie curl).
const BASE_URL = '__API_BASE__/api/v1';
const FINAL_STATUSES = ['approved', 'duplicate', 'rejected'];

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

$doc = send_invoice($argv[1]);
echo "Dokument #{$doc['id']}: {$doc['status']}\n";
if (!in_array($doc['status'], FINAL_STATUSES, true)) {
    $doc = wait_for_result($doc['id']) ?? $doc;
}
if ($doc['status'] === 'approved') {
    $invoice = $doc['invoice'];
    echo "{$invoice['number']}: {$invoice['totals']['gross']} {$invoice['currency']}\n";
    foreach ($invoice['lines'] as $line) {
        echo "  {$line['product_index']}: {$line['qty']} {$line['unit']}\n";
    }
}
