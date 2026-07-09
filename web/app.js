/* Finance Tracker — Phase 1 frontend */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

let FX = { EUR: 1.0 };

// sector -> categorical palette color
const SECTOR_COLORS = {
  "Technology": "#05C7F2",
  "Financial Services": "#695CFB",
  "Healthcare": "#0FCA7A",
  "Consumer Cyclical": "#F7A23B",
  "Consumer Defensive": "#FBC62F",
  "Energy": "#F75D5F",
  "Industrials": "#627D98",
  "Basic Materials": "#829AB1",
  "Communication Services": "#486581",
  "Utilities": "#334E68",
  "Real Estate": "#9FB3C8",
};
const sectorColor = (s) => SECTOR_COLORS[s] || "#64748B";

// ---------- tabs ----------
$$("#tabs button").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$("#tabs button").forEach((b) => b.classList.remove("active"));
    $$(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $(`#tab-${btn.dataset.tab}`).classList.add("active");
  });
});

// ---------- helpers ----------
async function api(path, opts) {
  const res = await fetch(path, opts);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function fmt(n, dec = 2) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return Number(n).toLocaleString("en-US", {
    minimumFractionDigits: dec, maximumFractionDigits: dec,
  });
}

function moneyCell(amount, currency) {
  if (amount == null) return "—";
  const text = `${fmt(amount)} ${currency || ""}`.trim();
  if (currency && currency !== "EUR" && FX[currency]) {
    const eur = amount * FX[currency];
    return `<span class="fx-hover" data-eur="≈ €${fmt(eur)}">${text}</span>`;
  }
  return text;
}

function changeCell(pct) {
  if (pct == null) return "—";
  const cls = pct >= 0 ? "up" : "down";
  const sign = pct >= 0 ? "+" : "";
  return `<span class="${cls}">${sign}${fmt(pct)}%</span>`;
}

function sectorPill(sector) {
  if (!sector) return "";
  return `<span class="pill" style="background:${sectorColor(sector)}">${sector}</span>`;
}

// ---------- FX ----------
async function loadFX() {
  try { FX = await api("/api/fx"); } catch (e) { console.warn("FX unavailable:", e); }
}

// ---------- Ticker Monitor ----------
let tvWidget = null;
let currentSymbol = null;

async function loadTicker(symbolRaw) {
  const symbol = symbolRaw.toUpperCase().trim();
  if (!symbol) return;
  currentSymbol = symbol;
  const q = await api(`/api/quote/${symbol}`);

  $("#monitor-quote").style.display = "";
  $("#mq-meta").textContent = `${q.exchange || ""} · ${q.quoteType || ""} · ${q.currency || ""}`;
  $("#mq-name").textContent = `${q.symbol} — ${q.name}`;
  $("#mq-price").innerHTML = moneyCell(q.price, q.currency);
  $("#mq-change").innerHTML = changeCell(q.changePercent);
  $("#mq-pills").innerHTML = sectorPill(q.sector);

  const stats = [
    ["P/E (trailing)", fmt(q.trailingPE)],
    ["P/E (forward)", fmt(q.forwardPE)],
    ["P/B", fmt(q.priceToBook)],
    ["PEG", fmt(q.pegRatio)],
    ["ROE", q.returnOnEquity != null ? fmt(q.returnOnEquity * 100) + "%" : "—"],
    ["Debt/Equity", fmt(q.debtToEquity)],
    ["Current ratio", fmt(q.currentRatio)],
    ["Dividend yield", q.dividendYield != null ? fmt(q.dividendYield) + "%" : "—"],
    ["50d avg", moneyCell(q.fiftyDayAverage, q.currency)],
    ["200d avg", moneyCell(q.twoHundredDayAverage, q.currency)],
    ["52w high", moneyCell(q.fiftyTwoWeekHigh, q.currency)],
    ["52w low", moneyCell(q.fiftyTwoWeekLow, q.currency)],
  ];
  $("#mq-stats").innerHTML = stats.map(([k, v]) =>
    `<div class="stat"><div class="caption">${k}</div><div class="v">${v}</div></div>`
  ).join("");

  // Signal engine — 5-layer composite
  api(`/api/signal/${symbol}`).then((sig) => {
    const card = $("#monitor-signal");
    if (sig.composite === null) { card.style.display = "none"; return; }
    card.style.display = "";
    const verdictColors = { BUY: "var(--up)", WATCH: "var(--cat-orange)", AVOID: "var(--down)", BLOCKED: "var(--down)" };
    $("#sig-verdict").innerHTML =
      `<span class="pill signal-pill" style="background:${verdictColors[sig.verdict] || "var(--n-5)"}">${sig.verdict}</span>`;
    const scoreEl = $("#sig-score");
    scoreEl.textContent = `${sig.composite}/100`;
    scoreEl.style.color = verdictColors[sig.verdict] || "var(--text)";

    $("#sig-layers").innerHTML = Object.entries(sig.layers).map(([name, layer]) => {
      const s = layer.score;
      const w = Math.round((sig.weights[name] || 0) * 100);
      const notes = (layer.notes || (layer.criteria ? [layer.note] : [])).filter(Boolean);
      return `<div class="stat">
        <div class="caption">${name} · weight ${w}%</div>
        <div class="v">${s === null || s === undefined ? "—" : s + "/100"}</div>
        <div style="font-size:0.72rem; color:var(--text-muted); margin-top:4px;">${notes.slice(0, 3).join("<br>")}</div>
      </div>`;
    }).join("");

    $("#sig-secular").textContent = sig.secularCaution
      ? `⚠ Secular gate: CAPE ${sig.secular.cape} > ${sig.secular.gate} — expensive regime, fresh BUY signals suppressed to WATCH.`
      : `Secular gate: CAPE ${sig.secular.cape ?? "n/a"} (threshold ${sig.secular.gate}) — regime OK.`;

    const m = sig.methodology;
    $("#sig-method").innerHTML = `
      <strong>Formula:</strong> ${m.compositeFormula}<br>
      <strong>BUY threshold:</strong> ≥ ${m.buyThreshold} + all gates pass<br>
      <strong>Data considered:</strong> ${m.historyBars} daily bars, sources: ${m.dataSource}<br>
      <strong>Hard gates failed:</strong> ${sig.hardGates.length ? sig.hardGates.join("; ") : "none"}<br>
      <strong>Caveats:</strong><br>${m.caveats.map((c) => "· " + c).join("<br>")}`;
  }).catch(() => { $("#monitor-signal").style.display = "none"; });

  // Strategy Fit
  api(`/api/fit/${symbol}`).then((fit) => {
    const card = $("#monitor-fit");
    if (fit.score === null || !fit.criteria.length) {
      card.style.display = "none";
      return;
    }
    card.style.display = "";
    const scoreEl = $("#fit-score");
    scoreEl.textContent = `${fit.score}/100`;
    scoreEl.style.color = fit.score >= 70 ? "var(--up)" : fit.score >= 40 ? "var(--cat-orange)" : "var(--down)";
    $("#fit-note").textContent = fit.note;
    $("#fit-table tbody").innerHTML = fit.criteria.map((c) => {
      const verdict = c.passed
        ? `<span class="pill" style="background:var(--up)">PASS</span>`
        : `<span class="pill" style="background:var(--down)">MISS</span>`;
      return `<tr>
        <td><strong>${c.name}</strong></td>
        <td>${c.threshold}</td>
        <td class="num">${c.actual}</td>
        <td>${verdict}</td>
        <td style="color:var(--text-muted); font-size:0.82rem;">${c.note}</td>
      </tr>`;
    }).join("");
  }).catch(() => { $("#monitor-fit").style.display = "none"; });

  // TradingView chart
  $("#monitor-chart-card").style.display = "";
  $("#tv-chart-container").innerHTML = "";
  tvWidget = new TradingView.widget({
    container_id: "tv-chart-container",
    symbol: symbol,
    autosize: true,
    interval: "D",
    theme: window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light",
    style: "1",
    locale: "en",
    hide_side_toolbar: false,
    allow_symbol_change: true,
    studies: ["MASimple@tv-basicstudies"],
  });
}

$("#monitor-load").addEventListener("click", () => loadTicker($("#monitor-input").value));
$("#monitor-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") loadTicker($("#monitor-input").value);
});
$("#monitor-watch").addEventListener("click", async () => {
  const sym = ($("#monitor-input").value || currentSymbol || "").toUpperCase().trim();
  if (!sym) return;
  await api("/api/watchlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbol: sym }),
  });
  renderWatchlist();
});
$("#chart-expand").addEventListener("click", () => {
  $("#tv-chart-container").classList.toggle("expanded");
  $("#chart-expand").textContent =
    $("#tv-chart-container").classList.contains("expanded") ? "Shrink chart" : "Expand chart";
});

// ---------- Watchlist ----------
async function renderWatchlist() {
  const data = await api("/api/watchlist");
  const tbody = $("#watch-table tbody");
  tbody.innerHTML = "";
  $("#watch-empty").style.display = data.tickers.length ? "none" : "";

  for (const t of data.tickers) {
    const tr = document.createElement("tr");
    tr.className = "clickable";
    tr.innerHTML = `<td><strong>${t.symbol}</strong></td><td colspan="4">loading…</td><td></td>`;
    tr.addEventListener("click", () => {
      $$("#tabs button").forEach((b) => b.classList.remove("active"));
      $$(".tab-panel").forEach((p) => p.classList.remove("active"));
      document.querySelector('[data-tab="monitor"]').classList.add("active");
      $("#tab-monitor").classList.add("active");
      $("#monitor-input").value = t.symbol;
      loadTicker(t.symbol);
    });
    tbody.appendChild(tr);

    api(`/api/quote/${t.symbol}`).then((q) => {
      tr.innerHTML = `
        <td><strong>${q.symbol}</strong></td>
        <td>${q.name}</td>
        <td>${sectorPill(q.sector)}</td>
        <td class="num">${moneyCell(q.price, q.currency)}</td>
        <td class="num">${changeCell(q.changePercent)}</td>
        <td><button class="btn danger" data-del="${q.symbol}">✕</button></td>`;
      tr.querySelector("[data-del]").addEventListener("click", async (e) => {
        e.stopPropagation();
        await api(`/api/watchlist/${q.symbol}`, { method: "DELETE" });
        renderWatchlist();
      });
    }).catch(() => {
      tr.children[1].textContent = "failed to load";
    });
  }
  renderHome(data.tickers.length);
}

$("#watch-add").addEventListener("click", async () => {
  const sym = $("#watch-input").value.toUpperCase().trim();
  if (!sym) return;
  await api("/api/watchlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbol: sym }),
  });
  $("#watch-input").value = "";
  renderWatchlist();
});
$("#watch-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("#watch-add").click();
});

// ---------- Portfolio ----------
async function renderPortfolio() {
  const data = await api("/api/holdings");
  const tbody = $("#pf-table tbody");
  tbody.innerHTML = "";
  $("#pf-empty").style.display = data.positions.length ? "none" : "";
  $("#pf-total").textContent = "";

  let totalCostEUR = 0, totalNowEUR = 0, resolved = 0;

  data.positions.forEach((p, idx) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td><strong>${p.symbol}</strong></td><td>${p.date}</td>
      <td class="num">${fmt(p.quantity, 4)}</td>
      <td class="num">${fmt(p.price)}</td>
      <td class="num">…</td><td class="num">…</td>
      <td><button class="btn danger" data-del="${idx}">✕</button></td>`;
    tbody.appendChild(tr);
    tr.querySelector("[data-del]").addEventListener("click", async () => {
      await api(`/api/holdings/${idx}`, { method: "DELETE" });
      renderPortfolio();
    });

    api(`/api/quote/${p.symbol}`).then((q) => {
      const nowVal = q.price != null ? q.price * p.quantity : null;
      const costVal = p.price * p.quantity;
      const pl = nowVal != null ? ((nowVal - costVal) / costVal) * 100 : null;
      tr.children[4].innerHTML = moneyCell(q.price, q.currency);
      tr.children[5].innerHTML = changeCell(pl);
      if (nowVal != null && q.currency && FX[q.currency]) {
        totalCostEUR += costVal * FX[q.currency];
        totalNowEUR += nowVal * FX[q.currency];
        resolved++;
        if (resolved === data.positions.length) {
          const plTot = ((totalNowEUR - totalCostEUR) / totalCostEUR) * 100;
          $("#pf-total").innerHTML =
            `€${fmt(totalNowEUR)} ${changeCell(plTot)} <span class="subtitle">(cost €${fmt(totalCostEUR)})</span>`;
        }
      }
    }).catch(() => { tr.children[4].textContent = "?"; });
  });
}

// Pre-populate price + date with current market values when ticker entered.
// Values stay editable — verify or overwrite them to record a past transaction.
let prefillTimer = null;
$("#h-symbol").addEventListener("input", () => {
  clearTimeout(prefillTimer);
  const sym = $("#h-symbol").value.toUpperCase().trim();
  if (sym.length < 2) return;
  prefillTimer = setTimeout(async () => {
    try {
      const q = await api(`/api/quote/${sym}`);
      if ($("#h-symbol").value.toUpperCase().trim() !== sym) return; // user kept typing
      if (!$("#h-date").value) {
        $("#h-date").value = new Date().toISOString().slice(0, 10);
      }
      if (!$("#h-price").value && q.price != null) {
        $("#h-price").value = q.price;
        $("#h-price").title = `Pre-filled with current market price (${q.currency}). Edit for a past transaction.`;
      }
    } catch (e) { /* unknown ticker — leave fields alone */ }
  }, 600);
});

$("#h-add").addEventListener("click", async () => {
  const body = {
    symbol: $("#h-symbol").value,
    date: $("#h-date").value,
    price: $("#h-price").value,
    quantity: $("#h-qty").value,
  };
  if (!body.symbol || !body.date || !body.price || !body.quantity) {
    alert("All fields required.");
    return;
  }
  await api("/api/holdings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  ["#h-symbol", "#h-price", "#h-qty"].forEach((s) => ($(s).value = ""));
  renderPortfolio();
});

// ---------- Suggestions / Screening ----------
let screenPoll = null;

async function pollScreen() {
  const st = await api("/api/screen/status");
  const el = $("#screen-progress");
  if (st.running) {
    el.textContent = `Screening… ${st.done}/${st.total} (errors: ${st.errors}, last: ${st.lastSymbol || ""})`;
    if (st.done % 25 === 0) renderSuggestions();
  } else {
    el.textContent = st.finishedAt
      ? `Last screen finished — ${st.done}/${st.total} processed, ${st.errors} errors.`
      : "";
    if (screenPoll) { clearInterval(screenPoll); screenPoll = null; }
    renderSuggestions();
  }
}

$("#screen-start").addEventListener("click", async () => {
  await api("/api/screen/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!screenPoll) screenPoll = setInterval(pollScreen, 3000);
  pollScreen();
});

$("#screen-refresh").addEventListener("click", renderSuggestions);

async function renderSuggestions() {
  const rows = await api("/api/screen/results?top=50");
  const tbody = $("#sugg-table tbody");
  $("#sugg-empty").style.display = rows.length ? "none" : "";
  tbody.innerHTML = rows.map((r, i) => `
    <tr class="clickable" data-sym="${r.symbol}">
      <td>${i + 1}</td>
      <td><strong>${r.symbol}</strong></td>
      <td>${r.name}</td>
      <td>${sectorPill(r.sector)}</td>
      <td class="num">${r.earningsYield != null ? fmt(r.earningsYield * 100, 1) + "%" : "—"}</td>
      <td class="num">${r.returnOnAssets != null ? fmt(r.returnOnAssets * 100, 1) + "%" : "—"}</td>
      <td class="num">${r.grahamPass}/${r.grahamChecks}</td>
      <td class="num">${r.marginOfSafety != null ? fmt(r.marginOfSafety * 100, 0) + "%" : "—"}</td>
    </tr>`).join("");
  tbody.querySelectorAll("tr").forEach((tr) => {
    tr.addEventListener("click", () => {
      document.querySelector('[data-tab="monitor"]').click();
      $("#monitor-input").value = tr.dataset.sym;
      loadTicker(tr.dataset.sym);
    });
  });
}

// ---------- Home ----------
function renderHome(watchCount) {
  api("/api/holdings").then((h) => {
    $("#home-summary").innerHTML = `
      <div class="stat"><div class="caption">Watchlist</div><div class="v">${watchCount ?? "…"} tickers</div></div>
      <div class="stat"><div class="caption">Positions held</div><div class="v">${h.positions.length}</div></div>
      <div class="stat"><div class="caption">FX rates</div><div class="v">${Object.keys(FX).length} currencies</div></div>
      <div class="stat"><div class="caption">Data status</div><div class="v">see Maintenance</div></div>`;
  });
}

// ---------- Maintenance ----------
async function renderMaintenance() {
  const checks = [
    { name: "Yahoo Finance (quotes)", probe: () => api("/api/quote/AAPL") },
    { name: "ECB FX rates", probe: () => api("/api/fx") },
  ];
  const el = $("#maint-checks");
  el.innerHTML = "";
  for (const c of checks) {
    const row = document.createElement("div");
    row.className = "row";
    row.style.padding = "8px 0";
    row.innerHTML = `<span class="pill" style="background:#64748B">…</span> <span>${c.name}</span>`;
    el.appendChild(row);
    c.probe()
      .then(() => { row.querySelector(".pill").style.background = "#0FCA7A"; row.querySelector(".pill").textContent = "OK"; })
      .catch(() => { row.querySelector(".pill").style.background = "#F75D5F"; row.querySelector(".pill").textContent = "FAIL"; });
  }
}

// ---------- boot ----------
(async function boot() {
  await loadFX();
  renderWatchlist();
  renderPortfolio();
  renderMaintenance();
  renderSuggestions().catch(() => {});
  pollScreen().catch(() => {});
  // quote auto-refresh while app open (cache TTL is 5 min server-side)
  setInterval(() => { renderWatchlist(); renderPortfolio(); }, 5 * 60 * 1000);
})();
