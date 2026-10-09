<?php
/**
 * Demo inventory page. Fixture only: no real player data, no database.
 */
declare(strict_types=1);
session_start();
if (!isset($_SESSION['demo_player_id'])) {
    $_SESSION['demo_player_id'] = 'local-demo-player';
    $_SESSION['inventory_csrf'] = bin2hex(random_bytes(24));
}
?>
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Инвентарь — Hybrid Engine demo</title>
<link rel="icon" href="data:,">
<link rel="stylesheet" href="assets/inventory.css">
</head>
<body>
<header class="topbar">
    <h1>Инвентарь</h1>
    <p class="player">Странник <span aria-hidden="true">·</span> 120 монет</p>
    <span id="status" class="status" role="status" aria-live="polite">готово</span>
</header>
<meta name="inventory-csrf" content="<?= htmlspecialchars($_SESSION['inventory_csrf'], ENT_QUOTES, 'UTF-8') ?>">

<form class="filters" onsubmit="return false">
    <label for="search">Поиск
        <input id="search" name="search" type="search" placeholder="Название предмета" autocomplete="off">
    </label>
    <label for="rarity">Редкость
        <select id="rarity" name="rarity">
            <option value="">любая</option>
            <option value="common">обычная</option>
            <option value="rare">редкая</option>
            <option value="epic">эпическая</option>
        </select>
    </label>
    <button id="refresh" type="button">Обновить</button>
</form>

<main>
    <section class="inventory-panel" aria-labelledby="inventory-title">
        <div class="section-heading">
            <div>
                <p class="eyebrow">Снаряжение героя</p>
                <h2 id="inventory-title">Ваша поклажа</h2>
            </div>
            <span id="item-count" class="item-count">0 предметов</span>
        </div>
        <div id="grid" class="grid" aria-live="polite"></div>
    </section>
</main>

<script src="assets/inventory.js"></script>
</body>
</html>
