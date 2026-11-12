"use strict";

const DATASET_URL = "data/banks.json";
const CURRENCY_LABELS = { USD: "USD", EUR: "EUR", RUB: "RUB", KZT: "KZT", GBP: "GBP" };
const STATUS_LABELS = {
  verified: "tasdiqlangan",
  partial: "qismiy",
  stale: "eski",
  unavailable: "mavjud emas",
};

let dataset = null;

function formatNumber(value) {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("uz-UZ").format(value);
}

function ageHours(iso) {
  if (!iso) return null;
  const when = Date.parse(iso);
  if (Number.isNaN(when)) return null;
  return (Date.now() - when) / 3_600_000;
}

/** Refuse to present rates that are older than the dataset's max_age_hours. */
function isStale(data) {
  const limit = data.max_age_hours ?? 24;
  const age = ageHours(data.generated_at);
  return age !== null && age > limit;
}

function buildCurrencyOptions(data) {
  const select = document.getElementById("currency");
  select.innerHTML = "";
  for (const code of data.supported_currencies) {
    const option = document.createElement("option");
    option.value = code;
    option.textContent = CURRENCY_LABELS[code] ?? code;
    select.append(option);
  }
}

function render() {
  const currency = document.getElementById("currency").value;
  const rateType = document.getElementById("rate-type").value;
  const body = document.querySelector("#rates tbody");
  body.innerHTML = "";

  if (!dataset) return;
  const stale = isStale(dataset);

  dataset.banks.forEach((bank, index) => {
    const entry = bank.currencies?.[currency]?.[rateType] ?? null;
    const row = document.createElement("tr");

    const position = document.createElement("td");
    position.textContent = String(index + 1);

    const name = document.createElement("td");
    name.textContent = bank.name;

    const buy = document.createElement("td");
    buy.className = "num buy";
    if (entry) {
      buy.textContent = formatNumber(entry.buy);
    } else {
      buy.textContent = "—";
      buy.classList.add("missing");
    }

    const sell = document.createElement("td");
    sell.className = "num";
    if (entry) {
      sell.textContent = formatNumber(entry.sell);
    } else {
      sell.textContent = "—";
      sell.classList.add("missing");
    }

    const status = document.createElement("td");
    const badge = document.createElement("span");
    badge.className = `badge ${bank.status}`;
    badge.textContent = STATUS_LABELS[bank.status] ?? bank.status;
    status.append(badge);
    if (bank.carried_forward) {
      const note = document.createElement("span");
      note.className = "badge stale";
      note.textContent = "avvalgi ma'lumot";
      status.append(document.createTextNode(" "), note);
    }

    // Never show a numeric cell for a stale dataset: clear it and explain why.
    if (stale) {
      for (const cell of [buy, sell]) {
        cell.textContent = "—";
        cell.classList.add("missing");
      }
    }

    row.append(position, name, buy, sell, status);
    body.append(row);
  });
}

function renderMeta(data) {
  const meta = document.getElementById("meta");
  const collected = new Date(data.generated_at).toLocaleString("uz-UZ");
  meta.textContent =
    `${data.summary.banks_with_rates}/${data.summary.banks_total} bank kurs e'lon qilgan · ` +
    `yangilangan: ${collected}`;
  document.getElementById("generated").textContent = `Yangilangan: ${collected}.`;

  const warning = document.getElementById("stale-warning");
  if (isStale(data)) {
    warning.hidden = false;
    warning.textContent =
      `Diqqat: ma'lumot ${data.max_age_hours} soatdan eski. ` +
      `Hisob-kitob qilishdan oldin yangilanishini kuting.`;
  } else {
    warning.hidden = true;
  }
}

async function load() {
  try {
    const response = await fetch(DATASET_URL, { cache: "no-cache" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    dataset = await response.json();
    buildCurrencyOptions(dataset);
    renderMeta(dataset);
    render();
  } catch (error) {
    document.getElementById("meta").textContent =
      `Ma'lumotni yuklab bo'lmadi: ${error.message}`;
  }
}

document.getElementById("currency").addEventListener("change", render);
document.getElementById("rate-type").addEventListener("change", render);
load();
