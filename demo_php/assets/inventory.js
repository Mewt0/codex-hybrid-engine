/* Demo inventory UI: fetch, error handling, double-submit guard, a11y. */

(function () {
  "use strict";

  var grid = document.getElementById("grid");
  var status = document.getElementById("status");
  var filterRarity = document.getElementById("rarity");
  var filterSearch = document.getElementById("search");
  var refresh = document.getElementById("refresh");
  var itemCount = document.getElementById("item-count");
  var rarityLabels = { common: "Обычная", rare: "Редкая", epic: "Эпическая" };
  var csrfToken = document.querySelector('meta[name="inventory-csrf"]').content;

  function setStatus(text, state) {
    status.textContent = text;
    status.dataset.state = state || "ok";
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderItems(items) {
    if (!items.length) {
      grid.innerHTML = '<p class="empty">Ничего не найдено. Измените фильтры.</p>';
      return;
    }
    grid.innerHTML = items
      .map(function (item) {
        var usable = item.type === "consumable";
        var equipable = item.type === "weapon" || item.type === "armor";
        var actionLabel = usable ? "Использовать" : item.equipped ? "Экипировано" : "Экипировать";
        return (
          '<article class="card" data-rarity="' + escapeHtml(item.rarity) + '" data-equipped="' + (item.equipped ? "true" : "false") + '">' +
          '<span class="rarity">' + escapeHtml(rarityLabels[item.rarity] || "Предмет") + " · " + escapeHtml(item.quantity) + " шт.</span>" +
          "<h3>" + escapeHtml(item.name) + "</h3>" +
          '<p class="price">' + escapeHtml(item.price) + " монет</p>" +
          (item.equipped ? '<span class="equipped-state">Экипировано</span>' : "") +
          (usable ? '<button type="button" data-action="use" data-id="' + escapeHtml(item.id) + '">Использовать</button>' : equipable && !item.equipped ? '<button type="button" data-action="equip" data-id="' + escapeHtml(item.id) + '">' + actionLabel + '</button>' : !equipable ? '<span class="item-note">Декоративный предмет</span>' : "") +
          "</article>"
        );
      })
      .join("");
  }

  function updateItemCount(items) {
    var total = items.reduce(function (sum, item) { return sum + Number(item.quantity || 0); }, 0);
    var lastTwo = total % 100;
    var last = total % 10;
    var noun = lastTwo >= 11 && lastTwo <= 14 ? "предметов" : last === 1 ? "предмет" : last >= 2 && last <= 4 ? "предмета" : "предметов";
    itemCount.textContent = total + " " + noun;
  }

  function loadItems() {
    var params = new URLSearchParams({ action: "list" });
    if (filterRarity.value) {
      params.set("rarity", filterRarity.value);
    }
    if (filterSearch.value.trim()) {
      params.set("q", filterSearch.value.trim());
    }
    refresh.disabled = true;
    setStatus("Загрузка…");
    return fetch("ajax/inventory.php?" + params.toString(), { headers: { Accept: "application/json" } })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("Сервер вернул " + response.status);
        }
        return response.json();
      })
      .then(function (payload) {
        if (!payload.ok) {
          throw new Error(payload.error || "Неизвестная ошибка");
        }
        renderItems(payload.items);
        updateItemCount(payload.items);
        setStatus("Инвентарь обновлён");
      })
      .catch(function (error) {
        setStatus("Ошибка: " + error.message, "error");
      })
      .finally(function () {
        refresh.disabled = false;
      });
  }

  grid.addEventListener("click", function (event) {
    var button = event.target.closest("button[data-action][data-id]");
    if (!button) {
      return;
    }
    button.disabled = true;
    var id = button.dataset.id;
    var requestKey = window.crypto && window.crypto.randomUUID
      ? window.crypto.randomUUID()
      : "demo-" + Date.now() + "-" + Math.random().toString(16).slice(2);
    var body = new URLSearchParams({ action: button.dataset.action, id: id, request_key: requestKey, csrf: csrfToken });
    fetch("ajax/inventory.php", {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" },
      body: body.toString(),
    })
      .then(function (response) {
        return response.json().then(function (payload) {
          return { response: response, payload: payload };
        });
      })
      .then(function (result) {
        var response = result.response;
        var payload = result.payload;
        if (!response.ok || !payload.ok) {
          throw new Error(payload.error || "Неизвестная ошибка");
        }
        renderItems(payload.items);
        updateItemCount(payload.items);
        setStatus(payload.message);
        return loadItems();
      })
      .catch(function (error) {
        setStatus("Ошибка: " + error.message, "error");
      })
      .finally(function () {
        button.disabled = false;
      });
  });

  refresh.addEventListener("click", loadItems);
  filterRarity.addEventListener("change", loadItems);
  filterSearch.addEventListener("input", function () {
    window.clearTimeout(filterSearch._timer);
    filterSearch._timer = window.setTimeout(loadItems, 250);
  });

  loadItems();
})();
