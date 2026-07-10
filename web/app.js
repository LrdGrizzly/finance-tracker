/* Finance Tracker — frontend (TradingView-style layout) */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

let FX = { EUR: 1.0 };

const SECTOR_COLORS = {
  "Technology": "#05C7F2",
  "Financial Services": "#8B7FFC",
  "Healthcare": "#0FCA7A",
  "Consumer Cyclical": "#F7A23B",
  "Consumer Defensive": "#FBC62F",
  "Energy": "#F75D5F",
  "Industrials": "#7E93A8",
  "Basic Materials": "#9FB3C8",
  "Communication Services": "#5A8DB8",
  "Utilities": "#6E88A3",
  "Real Estate": "#B08DCF",
};
const sectorColor = (s) => SECTOR_COLORS[s] || "#7E93A8";

const VERDICT_COLORS = {
  "STRONG BUY": "#0FCA7A", "BUY": "#4ADE9E", "HOLD": "#F7A23B",
  "SELL": "#F97066", "STRONG SELL": "#F75D5F", "BLOCKED": "#F75D5F",
};

// ---------- tabs ----------
function switchTab(name) {
  $$("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${name}`));
}
$$("#tabs button").forEach((btn) =>
  btn.addEventListener("click", () => switchTab(btn.dataset.tab)));

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
  return `<span class="pill" style="--pill-color:${sectorColor(sector)}">${sector}</span>`;
}

// ticker logo: company website favicon, fallback letter avatar
function logoHTML(q, size = "") {
  const domain = q.website ? q.website.replace(/^https?:\/\/(www\.)?/, "").split("/")[0] : null;
  if (domain) {
    return `<img class="tick-logo ${size}" loading="lazy" alt=""
      src="https://www.google.com/s2/favicons?domain=${domain}&sz=64"
      onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'tick-fallback',textContent:'${(q.symbol || "?").slice(0, 2)}',style:'background:${sectorColor(q.sector)}'}))">`;
  }
  return `<span class="tick-fallback" style="background:${sectorColor(q.sector)}">${(q.symbol || "?").slice(0, 2)}</span>`;
}

// ---------- FX ----------
async function loadFX() {
  try { FX = await api("/api/fx"); } catch (e) { console.warn("FX unavailable:", e); }
}

// ---------- global search with autocomplete (name OR ticker) ----------
const searchInput = $("#global-search");
const searchDrop = $("#search-results");
let searchTimer = null, searchSel = -1, searchItems = [];

function hideSearch() { searchDrop.style.display = "none"; searchSel = -1; }

function pickSearch(item) {
  hideSearch();
  searchInput.value = "";
  switchTab("monitor");
  loadTicker(item.symbol);
}

searchInput.addEventListener("input", () => {
  clearTimeout(searchTimer);
  const q = searchInput.value.trim();
  if (q.length < 2) { hideSearch(); return; }
  searchTimer = setTimeout(async () => {
    try {
      searchItems = await api(`/api/search?q=${encodeURIComponent(q)}`);
      if (!searchItems.length) {
        searchDrop.innerHTML = `<div class="search-noresult">No ticker found for “${q}” — check spelling, or try the exchange suffix (e.g. .MI for Milan, .L for London).</div>`;
        searchDrop.style.display = "";
        return;
      }
      searchDrop.innerHTML = searchItems.map((r, i) => `
        <div class="search-item" data-i="${i}">
          <span class="sy">${r.symbol}</span>
          <span class="nm">${r.name}</span>
          <span class="ex">${r.exchange}</span>
        </div>`).join("");
      searchDrop.style.display = "";
      searchDrop.querySelectorAll(".search-item").forEach((el) =>
        el.addEventListener("mousedown", (e) => { e.preventDefault(); pickSearch(searchItems[+el.dataset.i]); }));
    } catch (e) { hideSearch(); }
  }, 300);
});

searchInput.addEventListener("keydown", (e) => {
  const items = searchDrop.querySelectorAll(".search-item");
  if (e.key === "ArrowDown" && items.length) {
    e.preventDefault(); searchSel = Math.min(searchSel + 1, items.length - 1);
  } else if (e.key === "ArrowUp" && items.length) {
    e.preventDefault(); searchSel = Math.max(searchSel - 1, 0);
  } else if (e.key === "Enter") {
    if (searchSel >= 0 && searchItems[searchSel]) pickSearch(searchItems[searchSel]);
    else if (searchItems.length) pickSearch(searchItems[0]);
    else if (searchInput.value.trim()) {
      switchTab("monitor"); loadTicker(searchInput.value.trim()); searchInput.value = ""; hideSearch();
    }
    return;
  } else if (e.key === "Escape") { hideSearch(); return; }
  items.forEach((el, i) => el.classList.toggle("sel", i === searchSel));
});
searchInput.addEventListener("blur", () => setTimeout(hideSearch, 150));

// ---------- TradingView widgets ----------
// Yahoo suffix -> TradingView exchange prefix (widget speaks TV symbology)
const TV_EXCHANGE = {
  MI: "MIL", L: "LSE", PA: "EURONEXT", AS: "EURONEXT", BR: "EURONEXT",
  LS: "EURONEXT", DE: "XETR", F: "FWB", SW: "SIX", MC: "BME",
  TO: "TSX", V: "TSXV", HK: "HKEX", T: "TSE", AX: "ASX",
  ST: "OMXSTO", OL: "OSL", CO: "OMXCOP", HE: "OMXHEX",
};

function toTVSymbol(symbol) {
  const m = symbol.match(/^(.+)\.([A-Z]+)$/);
  if (m && TV_EXCHANGE[m[2]]) return `${TV_EXCHANGE[m[2]]}:${m[1]}`;
  return symbol;
}

function tvWidget(container, symbolRaw) {
  const symbol = toTVSymbol(symbolRaw);
  $(container).innerHTML = "";
  new TradingView.widget({
    container_id: container.slice(1),
    symbol, autosize: true, interval: "D",
    theme: window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark",
    style: "1", locale: "en",
    hide_side_toolbar: false, allow_symbol_change: true,
    backgroundColor: "rgba(0,0,0,0)",
    // MA Cross plots both MAs with distinct colors (two plain SMA studies
    // get identical default styling in the embed — not distinguishable)
    studies: [
      { id: "MACross@tv-basicstudies", inputs: { in_0: 50, in_1: 200 } },
    ],
    studies_overrides: {
      "compare.plot.color": "#2E7CF6",
      "ma cross.short ma.color": "#2E7CF6",
      "ma cross.long ma.color": "#E5484D",
      "ma cross.short ma.linewidth": 2,
      "ma cross.long ma.linewidth": 2,
      "ma cross.crosses.visible": true,
    },
  });
}

// ---------- analyze progress bar ----------
const AP_STEPS = 5; // quote, signal, quality, deep-value, chart
let apDone = 0, apTrickle = null, apTarget = 0, apShown = 0;

function apStart(symbol) {
  apDone = 0; apTarget = 8; apShown = 0;
  $("#analyze-progress").style.display = "";
  $("#ap-label").textContent = `Analyzing ${symbol} — running the algorithm on its data…`;
  $("#ap-fill").style.width = "0%";
  $("#ap-pct").textContent = "0%";
  clearInterval(apTrickle);
  // smooth trickle toward the current target so the bar never sits frozen
  apTrickle = setInterval(() => {
    if (apShown < apTarget) {
      apShown = Math.min(apTarget, apShown + 1);
      $("#ap-fill").style.width = apShown + "%";
      $("#ap-pct").textContent = apShown + "%";
    }
  }, 60);
}

function apStep(stageLabel) {
  apDone++;
  apTarget = Math.min(96, Math.round((apDone / AP_STEPS) * 100));
  if (stageLabel) $("#ap-label").textContent = stageLabel;
  if (apDone >= AP_STEPS) {
    apTarget = 100;
    setTimeout(() => {
      clearInterval(apTrickle);
      $("#ap-fill").style.width = "100%";
      $("#ap-pct").textContent = "100%";
      setTimeout(() => { $("#analyze-progress").style.display = "none"; }, 450);
    }, 250);
  }
}

// ---------- Ticker Monitor ----------
let currentSymbol = null;

async function loadTicker(symbolRaw) {
  const symbol = symbolRaw.toUpperCase().trim();
  if (!symbol) return;
  currentSymbol = symbol;
  $("#monitor-empty").style.display = "none";
  apStart(symbol);

  let q;
  try {
    q = await api(`/api/quote/${symbol}`);
  } catch (e) {
    clearInterval(apTrickle);
    $("#analyze-progress").style.display = "none";
    $("#monitor-empty").style.display = "";
    $("#monitor-empty").querySelector(".placeholder").textContent =
      `“${symbol}” returned no data — it may not be a valid ticker. Use the search bar to find the right symbol.`;
    ["#monitor-quote", "#monitor-signal", "#monitor-quality", "#monitor-fit", "#monitor-chart-card"]
      .forEach((s) => { $(s).style.display = "none"; });
    return;
  }
  if (q.price == null) {
    clearInterval(apTrickle);
    $("#analyze-progress").style.display = "none";
    $("#monitor-empty").style.display = "";
    $("#monitor-empty").querySelector(".placeholder").textContent =
      `“${symbol}” exists but has no market data — probably not a tradeable ticker. Try the search bar.`;
    return;
  }
  apStep(`Quote loaded — scoring ${symbol} against your criteria…`);

  $("#monitor-quote").style.display = "";
  const logoEl = $("#mq-logo");
  const domain = q.website ? q.website.replace(/^https?:\/\/(www\.)?/, "").split("/")[0] : null;
  if (domain) {
    logoEl.src = `https://www.google.com/s2/favicons?domain=${domain}&sz=64`;
    logoEl.style.display = "";
  } else logoEl.style.display = "none";

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

  // Overall signal
  api(`/api/signal/${symbol}`).then((sig) => {
    apStep("Signal engine done — computing quality score…");
    const card = $("#monitor-signal");
    if (sig.composite === null) { card.style.display = "none"; return; }
    card.style.display = "";
    const vColor = VERDICT_COLORS[sig.verdict] || "#7E93A8";
    $("#sig-verdict").innerHTML = `<span class="verdict" style="--v:${vColor}">${sig.verdict}</span>`;
    const scoreEl = $("#sig-score");
    scoreEl.textContent = `${sig.composite}/100`;
    scoreEl.style.color = vColor;

    if (sig.strength != null) {
      $("#sig-strength-wrap").style.display = "";
      $("#sig-strength-fill").style.width = `${sig.strength}%`;
      $("#sig-strength-label").textContent = `strength ${sig.strength}/100`;
    } else $("#sig-strength-wrap").style.display = "none";

    $("#sig-layers").innerHTML = Object.entries(sig.layers).map(([name, layer]) => {
      const s = layer.score;
      const w = Math.round((sig.weights[name] || 0) * 100);
      const notes = (layer.notes || []).filter(Boolean);
      return `<div class="stat">
        <div class="caption">${name} · ${w}%</div>
        <div class="v">${s == null ? "—" : s + "/100"}</div>
        <div class="sub">${notes.slice(0, 3).join("<br>")}</div>
      </div>`;
    }).join("");

    $("#sig-secular").textContent =
      `Secular context: CAPE ${sig.secular.cape ?? "n/a"} → composite × ${sig.secularMultiplier}` +
      (sig.secularCaution ? " (expensive regime — graduated haircut applied, position sizing should follow)" : " (no drag)");

    const m = sig.methodology;
    $("#sig-method").innerHTML = `
      <strong>Formula:</strong> ${m.compositeFormula}<br>
      <strong>Verdict ladder:</strong> ${m.verdictLadder}<br>
      <strong>Selection blend:</strong> ${sig.selectionBlend}<br>
      <strong>Raw composite before secular:</strong> ${sig.rawComposite}<br>
      <strong>Data:</strong> ${m.historyBars} daily bars · ${m.dataSource}<br>
      <strong>Hard gates failed:</strong> ${sig.hardGates.length ? sig.hardGates.join("; ") : "none"}<br>
      <strong>Caveats:</strong><br>${m.caveats.map((c) => "· " + c).join("<br>")}`;
  }).catch(() => { apStep(); $("#monitor-signal").style.display = "none"; });

  // Quality-Compounder
  api(`/api/quality/${symbol}`).then((ql) => {
    apStep("Quality-compounder scored — checking deep value…");
    const card = $("#monitor-quality");
    if (ql.score == null) { card.style.display = "none"; return; }
    card.style.display = "";
    const el = $("#q-score");
    el.textContent = `${ql.score}/100`;
    el.style.color = ql.score >= 70 ? "var(--up)" : ql.score >= 45 ? "var(--cat-orange)" : "var(--down)";
    $("#q-components").innerHTML = (ql.components || []).map((c) =>
      `<div class="stat"><div class="caption">${c.name}</div><div class="v">${c.score}/100</div></div>`
    ).join("");
    $("#q-notes").innerHTML = (ql.notes || []).map((n) => `<li>${n}</li>`).join("");
    const m = ql.methodology || {};
    $("#q-method").innerHTML = `
      <strong>ROIC formula:</strong> ${m.roic || ""}<br>
      <strong>Source:</strong> ${m.source || ""} — years: ${(ql.yearsCovered || []).join(", ")}<br>
      <strong>Caveats:</strong><br>${(m.caveats || []).map((c) => "· " + c).join("<br>")}`;
  }).catch(() => { apStep(); $("#monitor-quality").style.display = "none"; });

  // Deep-Value
  api(`/api/fit/${symbol}`).then((fit) => {
    apStep("Deep-value checked — loading chart…");
    const card = $("#monitor-fit");
    if (fit.score === null || !fit.criteria.length) { card.style.display = "none"; return; }
    card.style.display = "";
    const scoreEl = $("#fit-score");
    scoreEl.textContent = `${fit.score}/100`;
    scoreEl.style.color = fit.score >= 70 ? "var(--up)" : fit.score >= 40 ? "var(--cat-orange)" : "var(--down)";
    $("#fit-note").textContent = fit.note;
    $("#fit-table tbody").innerHTML = fit.criteria.map((c) => {
      const verdict = c.passed
        ? `<span class="pill" style="--pill-color:var(--up)">PASS</span>`
        : `<span class="pill" style="--pill-color:var(--down)">MISS</span>`;
      return `<tr>
        <td><strong>${c.name}</strong></td>
        <td>${c.threshold}</td>
        <td class="num">${c.actual}</td>
        <td>${verdict}</td>
        <td class="muted small">${c.note}</td>
      </tr>`;
    }).join("");
  }).catch(() => { apStep(); $("#monitor-fit").style.display = "none"; });

  // chart
  $("#monitor-chart-card").style.display = "";
  tvWidget("#tv-chart-container", symbol);
  apStep();
}

$("#monitor-watch").addEventListener("click", async () => {
  if (!currentSymbol) return;
  await api("/api/watchlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbol: currentSymbol }),
  });
  renderWatchlist();
});
$("#chart-expand").addEventListener("click", () => {
  $("#tv-chart-container").classList.toggle("expanded");
  $("#chart-expand").textContent =
    $("#tv-chart-container").classList.contains("expanded") ? "Shrink" : "Expand";
});

// ---------- Watchlist ----------
async function renderWatchlist() {
  const data = await api("/api/watchlist");
  const tbody = $("#watch-table tbody");
  tbody.innerHTML = "";
  $("#watch-empty").style.display = data.tickers.length ? "none" : "";
  const rail = $("#home-watch-rail");
  rail.innerHTML = data.tickers.length ? "" : `<div class="placeholder">Empty</div>`;

  for (const t of data.tickers) {
    const tr = document.createElement("tr");
    tr.className = "clickable";
    tr.innerHTML = `<td><strong>${t.symbol}</strong></td><td colspan="3" class="muted">loading…</td><td></td>`;
    tr.addEventListener("click", () => { switchTab("monitor"); loadTicker(t.symbol); });
    tbody.appendChild(tr);

    const railItem = document.createElement("div");
    railItem.className = "rail-item";
    railItem.innerHTML = `<span class="sym">${t.symbol}</span><span class="px muted">…</span>`;
    railItem.addEventListener("click", () => { switchTab("monitor"); loadTicker(t.symbol); });
    rail.appendChild(railItem);

    api(`/api/quote/${t.symbol}`).then((q) => {
      tr.innerHTML = `
        <td><div class="tick-cell">${logoHTML(q)}<div><strong>${q.symbol}</strong><span class="nm">${q.name}</span></div></div></td>
        <td>${sectorPill(q.sector)}</td>
        <td class="num">${moneyCell(q.price, q.currency)}</td>
        <td class="num">${changeCell(q.changePercent)}</td>
        <td><button class="btn danger" data-del="${q.symbol}">✕</button></td>`;
      tr.querySelector("[data-del]").addEventListener("click", async (e) => {
        e.stopPropagation();
        await api(`/api/watchlist/${q.symbol}`, { method: "DELETE" });
        renderWatchlist();
      });
      railItem.innerHTML = `${logoHTML(q)}<div><div class="sym">${q.symbol}</div><div class="nm">${q.name}</div></div>
        <div class="px">${fmt(q.price)}<br>${changeCell(q.changePercent)}</div>`;
    }).catch(() => { tr.children[1].textContent = "failed"; });
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
$("#watch-input").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#watch-add").click(); });

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
      tr.children[0].innerHTML = `<div class="tick-cell">${logoHTML(q)}<strong>${p.symbol}</strong></div>`;
      tr.children[4].innerHTML = moneyCell(q.price, q.currency);
      tr.children[5].innerHTML = changeCell(pl);
      if (nowVal != null && q.currency && FX[q.currency]) {
        totalCostEUR += costVal * FX[q.currency];
        totalNowEUR += nowVal * FX[q.currency];
        resolved++;
        if (resolved === data.positions.length) {
          const plTot = ((totalNowEUR - totalCostEUR) / totalCostEUR) * 100;
          $("#pf-total").innerHTML =
            `€${fmt(totalNowEUR)} ${changeCell(plTot)} <span class="muted small">(cost €${fmt(totalCostEUR)})</span>`;
        }
      }
    }).catch(() => { tr.children[4].textContent = "?"; });
  });
}

// prefill with current market values — editable for past transactions
let prefillTimer = null;
$("#h-symbol").addEventListener("input", () => {
  clearTimeout(prefillTimer);
  const sym = $("#h-symbol").value.toUpperCase().trim();
  if (sym.length < 2) return;
  prefillTimer = setTimeout(async () => {
    try {
      const q = await api(`/api/quote/${sym}`);
      if ($("#h-symbol").value.toUpperCase().trim() !== sym) return;
      if (!$("#h-date").value) $("#h-date").value = new Date().toISOString().slice(0, 10);
      if (!$("#h-price").value && q.price != null) {
        $("#h-price").value = q.price;
        $("#h-price").title = `Pre-filled with current market price (${q.currency}). Edit for a past transaction.`;
      }
    } catch (e) { /* unknown ticker */ }
  }, 600);
});

$("#h-add").addEventListener("click", async () => {
  const body = {
    symbol: $("#h-symbol").value, date: $("#h-date").value,
    price: $("#h-price").value, quantity: $("#h-qty").value,
  };
  if (!body.symbol || !body.date || !body.price || !body.quantity) {
    alert("All fields required."); return;
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
      ? `Last screen: ${st.done}/${st.total} processed, ${st.errors} errors.`
      : "";
    if (screenPoll) { clearInterval(screenPoll); screenPoll = null; }
    renderSuggestions();
  }
}

$("#screen-start").addEventListener("click", async () => {
  await api("/api/screen/start", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
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
      <td class="muted">${i + 1}</td>
      <td><div class="tick-cell"><strong>${r.symbol}</strong><span class="nm">${r.name}</span></div></td>
      <td>${sectorPill(r.sector)}</td>
      <td class="num">${r.earningsYield != null ? fmt(r.earningsYield * 100, 1) + "%" : "—"}</td>
      <td class="num">${r.returnOnAssets != null ? fmt(r.returnOnAssets * 100, 1) + "%" : "—"}</td>
      <td class="num">${r.grahamPass}/${r.grahamChecks}</td>
      <td class="num">${r.marginOfSafety != null ? fmt(r.marginOfSafety * 100, 0) + "%" : "—"}</td>
    </tr>`).join("");
  tbody.querySelectorAll("tr").forEach((tr) => {
    tr.addEventListener("click", () => { switchTab("monitor"); loadTicker(tr.dataset.sym); });
  });
}

// ---------- Home ----------
let homeChartLoaded = false;

async function renderHome(watchCount) {
  const h = await api("/api/holdings");
  $("#home-summary").innerHTML = `
    <div class="stat"><div class="caption">Watchlist</div><div class="v">${watchCount ?? "…"}</div></div>
    <div class="stat"><div class="caption">Positions</div><div class="v">${h.positions.length}</div></div>
    <div class="stat"><div class="caption">FX rates</div><div class="v">${Object.keys(FX).length}</div></div>
    <div class="stat" id="home-vix"><div class="caption">VIX / VVIX</div><div class="v">…</div></div>`;
  try {
    const [vix, vvix] = await Promise.all([api("/api/quote/^VIX"), api("/api/quote/^VVIX")]);
    const v = vix.price, vv = vvix.price;
    const regime = v == null ? "n/a" : v < 15 ? "calm" : v < 22 ? "normal" : v < 30 ? "elevated" : "stressed";
    const color = { calm: "var(--up)", normal: "var(--text)", elevated: "var(--cat-orange)", stressed: "var(--down)" }[regime] || "var(--text)";
    $("#home-vix").innerHTML = `
      <div class="caption">VIX / VVIX regime</div>
      <div class="v" style="color:${color}">${fmt(v, 1)} / ${fmt(vv, 1)} · ${regime}</div>
      <div class="sub">Volatility regime — size positions inversely</div>`;
    $("#top-regime").innerHTML = `VIX <b>${fmt(v, 1)}</b> · <span style="color:${color}">${regime}</span>`;
  } catch (e) { /* leave placeholder */ }

  if (!homeChartLoaded) {
    homeChartLoaded = true;
    loadHomeChart("^GSPC", "S&P 500");
  }
}

// ---------- home chart: our own data + Lightweight Charts (no symbol locks) ----------
let homeChart = null, homeSeries = null, homeMA50 = null, homeMA200 = null;
let homeSymbol = "^GSPC", homeLabel = "S&P 500", homePeriod = "1y", homeInterval = "1d";

// valid period options per interval (Yahoo free limits)
const INTERVAL_PERIODS = {
  "1m": ["1d", "5d", "7d"],
  "15m": ["1d", "5d", "1mo", "60d"],
  "1h": ["5d", "1mo", "3mo", "6mo", "1y", "2y"],
  "1d": ["1mo", "6mo", "ytd", "1y", "5y", "10y", "max"],
  "1wk": ["1y", "5y", "10y", "max"],
};

// fetch window: max free depth per interval, so MAs have full lookback
// (compute on everything, DISPLAY the requested window — TradingView behavior)
const FETCH_PERIOD = { "1m": "7d", "15m": "60d", "1h": "2y", "1d": "max", "1wk": "max" };

// requested period → seconds of visible window
function periodSeconds(p) {
  const day = 86400;
  const map = {
    "1d": day, "5d": 5 * day, "7d": 7 * day, "1mo": 31 * day, "60d": 60 * day,
    "3mo": 92 * day, "6mo": 183 * day, "1y": 365 * day, "2y": 730 * day,
    "5y": 5 * 365 * day, "10y": 10 * 365 * day,
  };
  if (p === "ytd") {
    return Math.floor((Date.now() - new Date(new Date().getFullYear(), 0, 1)) / 1000);
  }
  return map[p] || null; // null = max → show everything
}

let latestMA50 = null, latestMA200 = null;

function maLegendHTML(v50, v200) {
  const f = (v) => (v == null ? "—" : Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 }));
  return `<span style="color:#2E7CF6">● SMA 50: <b>${f(v50)}</b></span>
          <span style="color:#E5484D; margin-left:14px;">● SMA 200: <b>${f(v200)}</b></span>`;
}

function updateMALegendLatest() {
  const legend = $("#home-ma-legend");
  if (legend) legend.innerHTML = maLegendHTML(latestMA50, latestMA200);
}

function smaLine(rows, period) {
  const out = [];
  let sum = 0;
  for (let i = 0; i < rows.length; i++) {
    sum += rows[i].close;
    if (i >= period) sum -= rows[i - period].close;
    if (i >= period - 1) out.push({ time: rows[i].t, value: sum / period });
  }
  return out;
}

async function loadHomeChart(symbol, label, period, interval) {
  homeSymbol = symbol; homeLabel = label || symbol;
  if (interval) homeInterval = interval;
  if (period) homePeriod = period;
  // clamp period to what this interval supports
  const allowed = INTERVAL_PERIODS[homeInterval] || ["1y"];
  if (!allowed.includes(homePeriod)) homePeriod = allowed[allowed.length - 1];
  const el = $("#home-chart");
  $("#home-chart-label").textContent =
    `${homeLabel} · ${homeInterval} · ${homePeriod.toUpperCase()}`;
  // dim unusable range chips for the current interval
  $$("#range-chips .chip").forEach((c) => {
    const ok = allowed.includes(c.dataset.period);
    c.style.opacity = ok ? "" : "0.3";
    c.style.pointerEvents = ok ? "" : "none";
    c.classList.toggle("active", c.dataset.period === homePeriod);
  });

  if (!homeChart) {
    const css = getComputedStyle(document.documentElement);
    homeChart = LightweightCharts.createChart(el, {
      layout: {
        background: { type: "solid", color: "transparent" },
        textColor: css.getPropertyValue("--text-muted").trim(),
        fontFamily: "Inter, sans-serif",
      },
      grid: {
        vertLines: { color: "rgba(133,153,141,0.07)" },
        horzLines: { color: "rgba(133,153,141,0.07)" },
      },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false },
      crosshair: { mode: 0 },
      autoSize: true,
    });
    homeSeries = homeChart.addCandlestickSeries({
      upColor: "#0FCA7A", downColor: "#F75D5F",
      borderUpColor: "#0FCA7A", borderDownColor: "#F75D5F",
      wickUpColor: "rgba(15,202,122,0.6)", wickDownColor: "rgba(247,93,95,0.6)",
    });
    // public-analysis convention: 50MA blue, 200MA red
    homeMA50 = homeChart.addLineSeries({
      color: "#2E7CF6", lineWidth: 2, priceLineVisible: false,
      lastValueVisible: true, crosshairMarkerVisible: true,
      title: "SMA 50",
    });
    homeMA200 = homeChart.addLineSeries({
      color: "#E5484D", lineWidth: 2, priceLineVisible: false,
      lastValueVisible: true, crosshairMarkerVisible: true,
      title: "SMA 200",
    });
    // live legend: follows crosshair, shows latest values at rest
    homeChart.subscribeCrosshairMove((param) => {
      const legend = $("#home-ma-legend");
      if (!legend) return;
      let v50 = param.seriesData && param.seriesData.get(homeMA50);
      let v200 = param.seriesData && param.seriesData.get(homeMA200);
      if (v50 == null && v200 == null) { updateMALegendLatest(); return; }
      legend.innerHTML = maLegendHTML(v50 && v50.value, v200 && v200.value);
    });
  }

  try {
    const fetchPeriod = FETCH_PERIOD[homeInterval] || homePeriod;
    const rows = await api(
      `/api/history/${encodeURIComponent(symbol)}?period=${fetchPeriod}&interval=${homeInterval}`);
    homeSeries.setData(rows.map((r) => ({
      time: r.t, open: r.open, high: r.high, low: r.low, close: r.close,
    })));
    // 50/200-bar MAs computed on FULL fetched history so the lines span
    // the whole visible window (TradingView behavior), not just its tail
    const ma50data = rows.length > 50 ? smaLine(rows, 50) : [];
    const ma200data = rows.length > 200 ? smaLine(rows, 200) : [];
    homeMA50.setData(ma50data);
    homeMA200.setData(ma200data);
    latestMA50 = ma50data.length ? ma50data[ma50data.length - 1].value : null;
    latestMA200 = ma200data.length ? ma200data[ma200data.length - 1].value : null;
    updateMALegendLatest();
    // show only the requested window; pan left to see the rest
    const secs = periodSeconds(homePeriod);
    if (secs && rows.length) {
      const to = rows[rows.length - 1].t;
      homeChart.timeScale().setVisibleRange({ from: to - secs, to });
    } else {
      homeChart.timeScale().fitContent();
    }
  } catch (e) {
    $("#home-chart-label").textContent = `${symbol} — no data`;
  }
}

$$("#index-chips .chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    $$("#index-chips .chip").forEach((c) => c.classList.remove("active"));
    chip.classList.add("active");
    loadHomeChart(chip.dataset.sym, chip.textContent);
  });
});
$("#home-chart-search").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.target.value.trim()) {
    $$("#index-chips .chip").forEach((c) => c.classList.remove("active"));
    loadHomeChart(e.target.value.trim().toUpperCase());
    e.target.value = "";
  }
});
$$("#range-chips .chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    $$("#range-chips .chip").forEach((c) => c.classList.remove("active"));
    chip.classList.add("active");
    loadHomeChart(homeSymbol, homeLabel, chip.dataset.period);
  });
});
$$("#interval-chips .chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    $$("#interval-chips .chip").forEach((c) => c.classList.remove("active"));
    chip.classList.add("active");
    loadHomeChart(homeSymbol, homeLabel, chip.dataset.defperiod, chip.dataset.interval);
  });
});

// near-live price refresh on the open ticker (every 60s; free data ~15min delayed)
setInterval(async () => {
  if (!currentSymbol || !$("#tab-monitor").classList.contains("active")) return;
  try {
    const q = await api(`/api/quote/${currentSymbol}`);
    $("#mq-price").innerHTML = moneyCell(q.price, q.currency);
    $("#mq-change").innerHTML = changeCell(q.changePercent);
  } catch (e) { /* transient */ }
}, 60 * 1000);

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
    row.innerHTML = `<span class="pill" style="--pill-color:#7E93A8">…</span> <span>${c.name}</span>`;
    el.appendChild(row);
    const pill = row.querySelector(".pill");
    c.probe()
      .then(() => { pill.style.setProperty("--pill-color", "#0FCA7A"); pill.textContent = "OK"; })
      .catch(() => { pill.style.setProperty("--pill-color", "#F75D5F"); pill.textContent = "FAIL"; });
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
  setInterval(() => { renderWatchlist(); renderPortfolio(); }, 5 * 60 * 1000);
})();
