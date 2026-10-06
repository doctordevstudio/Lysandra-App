buildLayout("dashboard", "Dashboard");

let currentRange = { range: "today" };
let lastSummary = null;

const STAT_DEFS = [
  { key: "new_users", label: "New Users", category: "new_users" },
  { key: "total_users", label: "Total Users", category: null },
  { key: "yesterday_active_today", label: "Yesterday Users Active Today", category: null },
  { key: "fetch_success", label: "Fetch Success", category: "fetch_success" },
  { key: "fetch_failed", label: "Fetch Failed", category: "fetch_failed" },
  { key: "blocked_hits", label: "Blocked Domain Hits", category: "blocked" },
  { key: "maintenance_hits", label: "Maintenance Hits", category: "maintenance" },
];

function defaultDrilldownDate() {
  if (!lastSummary) return new Date().toISOString().slice(0, 10);
  const keys = lastSummary.date_keys;
  if (!keys || keys.length === 0) return new Date().toISOString().slice(0, 10);
  return keys[keys.length - 1];
}

async function loadSummary() {
  lastSummary = await api("/api/admin/dashboard/summary", { params: currentRange });
  renderStatCards();
  renderAdsBreakdown();
}

function renderStatCards() {
  const grid = document.getElementById("stat-cards");
  grid.innerHTML = STAT_DEFS.map(def => `
    <div class="card stat-card" data-category="${def.category || ""}">
      <div class="label">${def.label}</div>
      <div class="value">${lastSummary[def.key] ?? 0}</div>
    </div>
  `).join("");
  grid.querySelectorAll(".stat-card").forEach(card => {
    const category = card.dataset.category;
    if (!category) return;
    card.addEventListener("click", () => openDrilldown(category, STAT_DEFS.find(d => d.category === category).label));
  });
}

function renderAdsBreakdown() {
  const box = document.getElementById("ads-breakdown");
  const breakdown = lastSummary.ads_breakdown || {};
  const adTypes = Object.keys(breakdown);
  if (adTypes.length === 0) {
    box.innerHTML = `<p style="color:var(--text-dim); font-size:13px;">No ad events logged for this range yet.</p>`;
    return;
  }
  let rows = [];
  for (const adType of adTypes) {
    const platforms = breakdown[adType] || {};
    for (const platform of Object.keys(platforms)) {
      const actions = platforms[platform] || {};
      for (const action of Object.keys(actions)) {
        rows.push({ adType, platform, action, count: actions[action] });
      }
    }
  }
  box.innerHTML = `
    <table>
      <thead><tr><th>Ad type</th><th>Platform</th><th>Triggered by</th><th>Count</th></tr></thead>
      <tbody>
        ${rows.map(r => `
          <tr class="ads-row" data-ad-type="${r.adType}" data-platform="${r.platform}" data-action="${r.action}" style="cursor:pointer;">
            <td>${r.adType}</td><td>${r.platform}</td><td>${r.action}</td><td>${r.count}</td>
          </tr>`).join("")}
      </tbody>
    </table>
  `;
  box.querySelectorAll(".ads-row").forEach(row => {
    row.addEventListener("click", () => openAdsDrilldown(row.dataset.adType, row.dataset.platform, row.dataset.action));
  });
}

/* ---- Generic drilldown modal (date-scoped, cursor-paginated) ---- */
let modalState = null;

function openModalShell(title) {
  document.getElementById("modal-title").textContent = title;
  document.getElementById("modal-backdrop").classList.add("open");
}
document.getElementById("modal-close").addEventListener("click", () => {
  document.getElementById("modal-backdrop").classList.remove("open");
});

function renderDateHeaderAndList(items) {
  const body = document.getElementById("modal-body");
  const existingList = body.querySelector(".dd-list") || (() => {
    body.innerHTML = `
      <div class="field">
        <label>Date (IST)</label>
        <input type="date" id="dd-date" value="${modalState.date}">
      </div>
      <table class="dd-list"><thead><tr><th>Device</th><th>IP</th><th>Time</th></tr></thead><tbody></tbody></table>
    `;
    document.getElementById("dd-date").addEventListener("change", (e) => {
      modalState.date = e.target.value;
      modalState.cursor = null;
      fetchDrilldownPage(true);
    });
    return body.querySelector(".dd-list");
  })();
  const tbody = existingList.querySelector("tbody");
  for (const item of items) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${item.device_id || "-"}</td><td>${item.ip || "-"}</td><td>${fmtDate(item.ts)}</td>`;
    tbody.appendChild(tr);
  }
}

async function fetchDrilldownPage(reset) {
  if (reset) document.getElementById("modal-body").innerHTML = "";
  let data;
  if (modalState.kind === "ads") {
    data = await api("/api/admin/dashboard/ads-drilldown", {
      params: { date: modalState.date, ad_type: modalState.adType, platform: modalState.platform, action: modalState.action, cursor: modalState.cursor },
    });
  } else {
    data = await api("/api/admin/dashboard/drilldown", {
      params: { category: modalState.category, date: modalState.date, cursor: modalState.cursor },
    });
  }
  renderDateHeaderAndList(data.items);
  modalState.cursor = data.next_cursor;
  document.getElementById("modal-load-more").style.display = data.next_cursor ? "block" : "none";
}

function openDrilldown(category, title) {
  modalState = { kind: "generic", category, date: defaultDrilldownDate(), cursor: null };
  openModalShell(title);
  fetchDrilldownPage(true);
}

function openAdsDrilldown(adType, platform, action) {
  modalState = { kind: "ads", adType, platform, action, date: defaultDrilldownDate(), cursor: null };
  openModalShell(`${adType} / ${platform} / ${action}`);
  fetchDrilldownPage(true);
}

document.getElementById("modal-load-more-btn").addEventListener("click", () => fetchDrilldownPage(false));

/* ---- Top 50 users ---- */
async function loadTopUsers() {
  const data = await api("/api/admin/dashboard/top-users", { params: { limit: 50 } });
  const tbody = document.querySelector("#top-users-table tbody");
  tbody.innerHTML = data.items.map(u => `
    <tr>
      <td>${u.device_id}</td>
      <td>${u.fetch_count}</td>
      <td>${u.interstitial_watched}</td>
      <td>${u.rewarded_watched}</td>
      <td>${u.last_ip || "-"}</td>
      <td>${fmtDate(u.last_seen)}</td>
    </tr>
  `).join("");
}

buildRangePicker(document.getElementById("range-picker"), (range) => {
  currentRange = range;
  loadSummary();
});

loadSummary();
loadTopUsers();
