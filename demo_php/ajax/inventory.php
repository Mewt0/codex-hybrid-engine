<?php
/**
 * Offline inventory fixture. State is scoped to a demo player in a local JSON
 * file so the complete PHP/JS action flow can be exercised without a DB.
 */
declare(strict_types=1);
session_start();

if (!isset($_SESSION['demo_player_id']) || $_SESSION['demo_player_id'] !== 'local-demo-player') {
    http_response_code(401);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(['ok' => false, 'error' => 'Сессия игрока не найдена'], JSON_UNESCAPED_UNICODE);
    exit;
}

const ITEMS = [
    ['id' => 1, 'name' => 'Стальной клинок', 'rarity' => 'common', 'price' => 120, 'type' => 'weapon'],
    ['id' => 2, 'name' => 'Клёпаный щит', 'rarity' => 'common', 'price' => 90, 'type' => 'armor'],
    ['id' => 3, 'name' => 'Плащ ночи', 'rarity' => 'rare', 'price' => 640, 'type' => 'armor'],
    ['id' => 4, 'name' => 'Печать стража', 'rarity' => 'epic', 'price' => 2100, 'type' => 'consumable'],
];

function json_response(array $payload, int $status = 200): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR);
}

function find_item(int $id): ?array
{
    foreach (ITEMS as $item) {
        if ($item['id'] === $id) {
            return $item;
        }
    }
    return null;
}

function demo_state_path(string $playerId): string
{
    $configuredDirectory = getenv('HYBRID_DEMO_STATE_DIR');
    $directory = is_string($configuredDirectory) && $configuredDirectory !== ''
        ? $configuredDirectory
        : sys_get_temp_dir() . DIRECTORY_SEPARATOR . 'codex-hybrid-engine-demo-' . hash('sha256', __DIR__);
    if (!is_dir($directory) && !mkdir($directory, 0700, true) && !is_dir($directory)) {
        throw new RuntimeException('Could not initialize demo state');
    }
    return $directory . DIRECTORY_SEPARATOR . 'inventory-' . hash('sha256', $playerId) . '.json';
}

function read_state(string $playerId): array
{
    $configuredDirectory = getenv('HYBRID_DEMO_STATE_DIR');
    $directory = is_string($configuredDirectory) && $configuredDirectory !== ''
        ? $configuredDirectory
        : sys_get_temp_dir() . DIRECTORY_SEPARATOR . 'codex-hybrid-engine-demo-' . hash('sha256', __DIR__);
    $path = $directory . DIRECTORY_SEPARATOR . 'inventory-' . hash('sha256', $playerId) . '.json';
    if (!is_file($path)) {
        return ['owner' => $playerId, 'items' => [1 => 1, 2 => 1, 3 => 2, 4 => 1], 'equipped' => [], 'used' => []];
    }
    $state = json_decode((string) file_get_contents($path), true);
    if (!is_array($state) || ($state['owner'] ?? null) !== $playerId || !is_array($state['items'] ?? null)) {
        throw new RuntimeException('Demo state is invalid');
    }
    $state['equipped'] = is_array($state['equipped'] ?? null) ? $state['equipped'] : [];
    $state['used'] = is_array($state['used'] ?? null) ? $state['used'] : [];
    return $state;
}

function with_state(string $playerId, callable $operation): array
{
    $path = demo_state_path($playerId);
    $handle = fopen($path, 'c+');
    if ($handle === false || !flock($handle, LOCK_EX)) {
        if (is_resource($handle)) {
            fclose($handle);
        }
        throw new RuntimeException('Could not lock demo state');
    }
    try {
        $raw = stream_get_contents($handle);
        $state = $raw === '' ? ['owner' => $playerId, 'items' => [1 => 1, 2 => 1, 3 => 2, 4 => 1], 'equipped' => [], 'used' => []] : json_decode($raw, true);
        if (!is_array($state) || ($state['owner'] ?? null) !== $playerId || !is_array($state['items'] ?? null)) {
            throw new RuntimeException('Demo state is invalid');
        }
    $state['equipped'] = is_array($state['equipped'] ?? null) ? $state['equipped'] : [];
        $state['used'] = is_array($state['used'] ?? null) ? $state['used'] : [];
        $result = $operation($state);
        rewind($handle);
        if (!ftruncate($handle, 0) || fwrite($handle, json_encode($state, JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR)) === false) {
            throw new RuntimeException('Could not save demo state');
        }
        fflush($handle);
        return $result;
    } finally {
        flock($handle, LOCK_UN);
        fclose($handle);
    }
}

function inventory_items(array $state, ?string $rarity, ?string $search): array
{
    $items = [];
    foreach (ITEMS as $item) {
        $quantity = (int) ($state['items'][$item['id']] ?? 0);
        if ($quantity < 1 || ($rarity && $item['rarity'] !== $rarity)) {
            continue;
        }
        if ($search !== null && $search !== '') {
            $position = function_exists('mb_stripos')
                ? mb_stripos($item['name'], $search)
                : stripos($item['name'], (string) $search);
            if ($position === false) {
                continue;
            }
        }
        $item['quantity'] = $quantity;
        $item['equipped'] = (int) ($state['equipped'][$item['type']] ?? 0) === $item['id'];
        $items[] = $item;
    }
    return $items;
}

function valid_request_key($value): bool
{
    return is_string($value) && preg_match('/^[a-f0-9-]{16,64}$/i', $value) === 1;
}

try {
    $action = $_SERVER['REQUEST_METHOD'] === 'POST' ? ($_POST['action'] ?? '') : ($_GET['action'] ?? 'list');
    if ($action === 'list' && $_SERVER['REQUEST_METHOD'] === 'GET') {
        $state = read_state((string) $_SESSION['demo_player_id']);
        json_response(['ok' => true, 'items' => inventory_items($state, $_GET['rarity'] ?? null, $_GET['q'] ?? null)]);
        exit;
    }

    if ($action === 'use' && $_SERVER['REQUEST_METHOD'] === 'POST') {
        $id = filter_var($_POST['id'] ?? null, FILTER_VALIDATE_INT, ['options' => ['min_range' => 1]]);
        $requestKey = $_POST['request_key'] ?? null;
        $csrf = $_POST['csrf'] ?? '';
        if ($id === false || !valid_request_key($requestKey) || !is_string($csrf)
            || !hash_equals((string) ($_SESSION['inventory_csrf'] ?? ''), $csrf)) {
            json_response(['ok' => false, 'error' => 'Некорректный запрос'], 400);
            exit;
        }
        $item = find_item((int) $id);
        if ($item === null) {
            json_response(['ok' => false, 'error' => 'Предмет не найден'], 404);
            exit;
        }
        if ($item['type'] !== 'consumable') {
            json_response(['ok' => false, 'error' => 'Этот предмет нельзя использовать'], 409);
            exit;
        }
        $playerId = (string) $_SESSION['demo_player_id'];
        $result = with_state($playerId, static function (array &$state) use ($item, $requestKey): array {
            if (isset($state['used'][$requestKey])) {
                return ['ok' => true, 'message' => 'Предмет уже использован', 'replayed' => true, 'items' => inventory_items($state, null, null)];
            }
            if ((int) ($state['items'][$item['id']] ?? 0) < 1) {
                return ['ok' => false, 'error' => 'Предмет отсутствует в инвентаре'];
            }
            $state['items'][$item['id']]--;
            if ($state['items'][$item['id']] === 0) {
                unset($state['items'][$item['id']]);
            }
            $state['used'][$requestKey] = true;
            if (count($state['used']) > 256) {
                $state['used'] = array_slice($state['used'], -256, null, true);
            }
            return ['ok' => true, 'message' => 'Использовано: ' . $item['name'], 'replayed' => false, 'items' => inventory_items($state, null, null)];
        });
        json_response($result, ($result['ok'] ?? false) ? 200 : 409);
        exit;
    }

    if ($action === 'equip' && $_SERVER['REQUEST_METHOD'] === 'POST') {
        $id = filter_var($_POST['id'] ?? null, FILTER_VALIDATE_INT, ['options' => ['min_range' => 1]]);
        $requestKey = $_POST['request_key'] ?? null;
        $csrf = $_POST['csrf'] ?? '';
        if ($id === false || !valid_request_key($requestKey) || !is_string($csrf)
            || !hash_equals((string) ($_SESSION['inventory_csrf'] ?? ''), $csrf)) {
            json_response(['ok' => false, 'error' => 'Некорректный запрос'], 400);
            exit;
        }
        $item = find_item((int) $id);
        if ($item === null) {
            json_response(['ok' => false, 'error' => 'Предмет не найден'], 404);
            exit;
        }
        if (!in_array($item['type'], ['weapon', 'armor'], true)) {
            json_response(['ok' => false, 'error' => 'Этот предмет нельзя экипировать'], 409);
            exit;
        }
        $playerId = (string) $_SESSION['demo_player_id'];
        $result = with_state($playerId, static function (array &$state) use ($item, $requestKey): array {
            if (isset($state['used'][$requestKey])) {
                return ['ok' => true, 'message' => 'Экипировка уже обновлена', 'replayed' => true, 'items' => inventory_items($state, null, null)];
            }
            if ((int) ($state['items'][$item['id']] ?? 0) < 1) {
                return ['ok' => false, 'error' => 'Предмет отсутствует в инвентаре'];
            }
            $state['equipped'][$item['type']] = $item['id'];
            $state['used'][$requestKey] = true;
            if (count($state['used']) > 256) {
                $state['used'] = array_slice($state['used'], -256, null, true);
            }
            return ['ok' => true, 'message' => 'Экипировано: ' . $item['name'], 'replayed' => false, 'items' => inventory_items($state, null, null)];
        });
        json_response($result, ($result['ok'] ?? false) ? 200 : 409);
        exit;
    }

    json_response(['ok' => false, 'error' => 'Неизвестное действие'], 400);
} catch (Throwable $error) {
    error_log('Demo inventory error: ' . $error->getMessage());
    json_response(['ok' => false, 'error' => 'Не удалось обработать инвентарь'], 500);
}
