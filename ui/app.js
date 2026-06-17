const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) {
    // Surface the server's own message (FastAPI puts it in `detail`) so the user
    // sees "check your app password", not "/api/... -> 502".
    let detail = "";
    try { detail = (await res.json()).detail || ""; } catch { /* non-JSON body */ }
    throw new Error(detail || `${path} -> ${res.status}`);
  }
  return res.json();
}

let objectiveOptions = [];   // [{key,label}] in slider order

// ---- navigation ----
function showScreen(name) {
  document.querySelectorAll(".screen").forEach((s) => s.classList.add("hidden"));
  $(`#screen-${name}`).classList.remove("hidden");
  document.querySelectorAll(".nav-btn").forEach((b) =>
    b.classList.toggle("active", b.dataset.screen === name));
  if (name === "watchlist") loadSettings();
  if (name === "positions") loadPositions();
  if (name === "integrations") loadIntegrations();
}
document.querySelectorAll(".nav-btn").forEach((b) =>
  b.addEventListener("click", () => showScreen(b.dataset.screen)));

// ---- briefing ----
async function loadBriefing(autoRun = true) {
  const data = await api("/api/briefing/today");
  if (data.status === "none") {
    if (autoRun) { await runBriefing(); return; }
    $("#briefing-status").textContent = "No briefing yet. Click “Run now”.";
    return;
  }
  $("#briefing-status").textContent = "";
  $("#briefing-content").innerHTML = data.html;   // our own server-rendered HTML
}

async function runBriefing() {
  $("#run-btn").disabled = true;
  $("#briefing-status").textContent = "Running… fetching market data (this can take ~30s).";
  try {
    const r = await api("/api/run", { method: "POST" });
    if (r.status === "ok") { await loadBriefing(false); await loadHistory(); }
    else if (r.status === "skipped") { $("#briefing-status").textContent = r.message; }
    else { $("#briefing-status").textContent = "Run failed: " + (r.message || "unknown error"); }
  } catch (e) {
    $("#briefing-status").textContent = "Run failed: " + e.message;
  } finally {
    $("#run-btn").disabled = false;
  }
}
$("#run-btn").addEventListener("click", runBriefing);

// ---- objective slider ----
async function loadObjective() {
  const d = await api("/api/objective");
  objectiveOptions = d.options;
  const slider = $("#objective-slider");
  slider.max = String(objectiveOptions.length - 1);
  const idx = objectiveOptions.findIndex((o) => o.key === d.objective);
  slider.value = String(idx < 0 ? 1 : idx);
  $("#objective-label").textContent = objectiveOptions[slider.value]?.label || "Balanced";
}
$("#objective-slider").addEventListener("input", () => {
  const o = objectiveOptions[$("#objective-slider").value];
  if (o) $("#objective-label").textContent = o.label;
});
$("#objective-slider").addEventListener("change", async () => {
  const o = objectiveOptions[$("#objective-slider").value];
  if (!o) return;
  try {
    await api("/api/objective", { method: "PUT", body: JSON.stringify({ objective: o.key }) });
    $("#briefing-status").textContent =
      `Strategy set to ${o.label}. Click “Run now” to generate a briefing with it.`;
  } catch (e) { $("#briefing-status").textContent = "Could not save strategy: " + e.message; }
});

// ---- briefing history ----
async function loadHistory(selectId) {
  const { items } = await api("/api/briefing/history");
  const sel = $("#briefing-history");
  sel.innerHTML = items.map((i) => `<option value="${esc(i.id)}">${esc(i.label)}</option>`).join("");
  if (selectId) sel.value = selectId;
}
$("#briefing-history").addEventListener("change", async () => {
  const id = $("#briefing-history").value;
  if (!id) return;
  const d = await api("/api/briefing/item/" + encodeURIComponent(id));
  if (d.status === "ok") $("#briefing-content").innerHTML = d.html;
});

// ---- watchlist / settings ----
let tickers = [];
let loadedSettings = {};   // full settings from GET, so PUT can preserve UI-hidden keys
function renderChips() {
  $("#ticker-chips").innerHTML = tickers.map((t, i) =>
    `<span class="chip">${esc(t)}<button data-i="${i}" class="chip-x">×</button></span>`).join("");
  document.querySelectorAll(".chip-x").forEach((b) =>
    b.addEventListener("click", () => { tickers.splice(+b.dataset.i, 1); renderChips(); }));
}
async function loadSettings() {
  const data = await api("/api/settings");
  tickers = data.tickers.slice();
  loadedSettings = data.settings || {};
  renderChips();
  $("#shortlist-size").value = loadedSettings.shortlist_size ?? 8;
  $("#lookback-days").value = loadedSettings.lookback_days ?? 200;
  $("#settings-msg").textContent = "";
}
$("#add-ticker-btn").addEventListener("click", () => {
  const v = $("#new-ticker").value.trim().toUpperCase();
  if (v && !tickers.includes(v)) { tickers.push(v); renderChips(); }
  $("#new-ticker").value = "";
});
$("#save-settings-btn").addEventListener("click", async () => {
  const body = {
    tickers,
    settings: {
      ...loadedSettings,   // preserve fields the UI doesn't expose (min_price, min_avg_volume)
      shortlist_size: +$("#shortlist-size").value || 8,
      lookback_days: +$("#lookback-days").value || 200,
    },
  };
  try {
    await api("/api/settings", { method: "PUT", body: JSON.stringify(body) });
    $("#settings-msg").textContent = "Saved.";
  } catch (e) { $("#settings-msg").textContent = "Save failed: " + e.message; }
});

// ---- positions ----
function positionRow(p = {}) {
  const tr = document.createElement("tr");
  tr.innerHTML =
    `<td><input class="p-ticker" value="${esc(p.ticker || "")}" maxlength="8"></td>` +
    `<td><input class="p-price" type="number" step="0.01" value="${p.entry_price ?? ""}"></td>` +
    `<td><input class="p-date" type="date" value="${esc(p.entry_date || "")}"></td>` +
    `<td><input class="p-shares" type="number" step="any" value="${p.shares ?? ""}"></td>` +
    `<td><button class="p-del">×</button></td>`;
  tr.querySelector(".p-del").addEventListener("click", () => tr.remove());
  return tr;
}
async function loadPositions() {
  const data = await api("/api/positions");
  const body = $("#positions-body");
  body.innerHTML = "";
  data.positions.forEach((p) => body.appendChild(positionRow(p)));
  $("#positions-msg").textContent = "";
}
$("#add-position-btn").addEventListener("click", () =>
  $("#positions-body").appendChild(positionRow()));
$("#save-positions-btn").addEventListener("click", async () => {
  const positions = [];
  for (const tr of document.querySelectorAll("#positions-body tr")) {
    const ticker = tr.querySelector(".p-ticker").value.trim().toUpperCase();
    const price = parseFloat(tr.querySelector(".p-price").value);
    if (!ticker || !(price > 0)) continue;
    const date = tr.querySelector(".p-date").value.trim();
    const shares = tr.querySelector(".p-shares").value.trim();
    const p = { ticker, entry_price: price };
    if (date) p.entry_date = date;
    if (shares) p.shares = parseFloat(shares);
    positions.push(p);
  }
  try {
    await api("/api/positions", { method: "PUT", body: JSON.stringify({ positions }) });
    $("#positions-msg").textContent = "Saved.";
  } catch (e) { $("#positions-msg").textContent = "Save failed: " + e.message; }
});

// ---- integrations ----
async function loadIntegrations() {
  const d = await api("/api/integrations");
  $("#ai-status").textContent = d.ai.key_set ? "Key saved ✓" : "No key set.";
  $("#ai-key").value = "";
  $("#email-user").value = d.email.user || "";
  $("#email-to").value = d.email.to || "";
  $("#email-host").value = d.email.host || "smtp.gmail.com";
  $("#email-port").value = d.email.port || "465";
  $("#email-pass").value = "";
  $("#email-status").textContent = d.email.password_set ? "App password saved ✓" : "No app password set.";
  $("#integrations-msg").textContent = "";
}
$("#save-ai-btn").addEventListener("click", async () => {
  try {
    await api("/api/integrations/ai", { method: "PUT",
      body: JSON.stringify({ api_key: $("#ai-key").value.trim() }) });
    $("#integrations-msg").textContent = "AI key saved.";
    loadIntegrations();
  } catch (e) { $("#integrations-msg").textContent = "Save failed: " + e.message; }
});
$("#clear-ai-btn").addEventListener("click", async () => {
  try {
    await api("/api/integrations/ai", { method: "PUT", body: JSON.stringify({ api_key: "" }) });
    $("#integrations-msg").textContent = "AI key cleared.";
    loadIntegrations();
  } catch (e) { $("#integrations-msg").textContent = "Clear failed: " + e.message; }
});
$("#save-email-btn").addEventListener("click", async () => {
  const body = {
    user: $("#email-user").value.trim(),
    to: $("#email-to").value.trim(),
    host: $("#email-host").value.trim() || "smtp.gmail.com",
    port: $("#email-port").value.trim() || "465",
  };
  const pw = $("#email-pass").value;          // omit when blank -> keep existing
  if (pw) body.password = pw;
  try {
    await api("/api/integrations/email", { method: "PUT", body: JSON.stringify(body) });
    $("#integrations-msg").textContent = "Email settings saved.";
    loadIntegrations();
  } catch (e) { $("#integrations-msg").textContent = "Save failed: " + e.message; }
});
$("#test-email-btn").addEventListener("click", async () => {
  $("#integrations-msg").textContent = "Sending test email…";
  try {
    await api("/api/integrations/email/test", { method: "POST" });
    $("#integrations-msg").textContent = "Test email sent — check your inbox.";
  } catch (e) { $("#integrations-msg").textContent = "Test failed: " + e.message; }
});

// ---- boot ----
async function boot() {
  const state = await api("/api/state");
  await loadObjective();
  const start = async () => { await loadBriefing(); await loadHistory(); };
  if (!state.disclaimer_accepted) {
    $("#disclaimer").classList.remove("hidden");
    $("#accept-btn").addEventListener("click", async () => {
      await api("/api/disclaimer/accept", { method: "POST" });
      $("#disclaimer").classList.add("hidden");
      start();
    });
  } else {
    start();
  }
}
boot();
