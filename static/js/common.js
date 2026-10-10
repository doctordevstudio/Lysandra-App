/* Shared shell: sidebar nav, topbar, theme toggle (day default), logout,
   15-minute session countdown with a warning toast before it expires. */

const NAV_ITEMS = [
  { key: "dashboard", label: "Dashboard", icon: "📊" },
  { key: "notifications", label: "Notification", icon: "🔔" },
  { key: "dialogs", label: "Dialog", icon: "💬" },
  { key: "carousel", label: "Carousel", icon: "🖼️" },
  { key: "block", label: "Block", icon: "⛔" },
  { key: "settings", label: "Settings", icon: "⚙️" },
];

function applyStoredTheme() {
  const saved = localStorage.getItem("lysandra_theme");
  if (saved === "dark") document.documentElement.setAttribute("data-theme", "dark");
}

function toggleTheme() {
  const isDark = document.documentElement.getAttribute("data-theme") === "dark";
  if (isDark) {
    document.documentElement.removeAttribute("data-theme");
    localStorage.setItem("lysandra_theme", "light");
  } else {
    document.documentElement.setAttribute("data-theme", "dark");
    localStorage.setItem("lysandra_theme", "dark");
  }
}

function buildLayout(activeKey, title) {
  applyStoredTheme();

  const sidebar = document.createElement("div");
  sidebar.className = "sidebar";
  sidebar.innerHTML = `
    <div class="brand">
      <img src="/static/img/icon.png" alt="Lysandra">
      <span>Lysandra</span>
    </div>
    ${NAV_ITEMS.map(i => `
      <div class="nav-link ${i.key === activeKey ? "active" : ""}" data-nav="${i.key}">
        <span>${i.icon}</span><span>${i.label}</span>
      </div>`).join("")}
    <div class="sidebar-footer">©️ Copyright by Dr. Dev || Dr. Hamza 2026<br>All Rights Reserved.</div>
  `;
  sidebar.querySelectorAll("[data-nav]").forEach(el => {
    el.addEventListener("click", () => { window.location.href = "/" + el.dataset.nav; });
  });

  const overlay = document.createElement("div");
  overlay.className = "sidebar-overlay";

  const topbar = document.createElement("div");
  topbar.className = "topbar";
  topbar.innerHTML = `
    <div style="display:flex;align-items:center;gap:10px;">
      <button class="menu-toggle" id="menu-toggle-btn" aria-label="Menu">☰</button>
      <h1>${title}</h1>
    </div>
    <div class="topbar-actions">
      <span id="session-countdown" style="font-size:12px;color:var(--text-dim);"></span>
      <button class="theme-toggle" id="theme-toggle-btn" title="Toggle day/night">🌓</button>
      <button class="btn secondary" id="logout-btn">Log out</button>
    </div>
  `;

  document.body.prepend(overlay);
  document.body.prepend(topbar);
  document.body.prepend(sidebar);
  document.body.classList.add("app-shell");

  function closeMobileSidebar() {
    sidebar.classList.remove("open");
    overlay.classList.remove("open");
  }
  document.getElementById("menu-toggle-btn").addEventListener("click", () => {
    sidebar.classList.toggle("open");
    overlay.classList.toggle("open");
  });
  overlay.addEventListener("click", closeMobileSidebar);

  document.getElementById("theme-toggle-btn").addEventListener("click", toggleTheme);
  document.getElementById("logout-btn").addEventListener("click", async () => {
    await api("/api/admin/logout", { method: "POST" });
    window.location.href = "/login";
  });

  startSessionCountdown();
}

let _sessionDeadline = null;

function startSessionCountdown() {
  // Sliding 15-min window: every authenticated API call resets it server-side;
  // we just show an approximate local countdown and refresh it on each api() call.
  _sessionDeadline = Date.now() + 15 * 60 * 1000;
  const el = document.getElementById("session-countdown");
  setInterval(() => {
    const remaining = Math.max(0, _sessionDeadline - Date.now());
    const mins = Math.floor(remaining / 60000);
    const secs = Math.floor((remaining % 60000) / 1000);
    if (el) el.textContent = remaining > 0 ? `Session: ${mins}:${String(secs).padStart(2, "0")}` : "Session expired";
    if (remaining === 0) window.location.href = "/login";
  }, 1000);
}

function bumpSessionCountdown() {
  _sessionDeadline = Date.now() + 15 * 60 * 1000;
}

/* Wrap the global api() from api.js so every successful call resets the
   on-screen countdown to match the server's sliding expiry. */
const _rawApi = api;
api = async function (...args) {
  const result = await _rawApi(...args);
  bumpSessionCountdown();
  return result;
};

/* Reusable Today/Yesterday/All time/Custom range picker used on every
   analytics page. onChange receives {range, start, end}. */
function buildRangePicker(container, onChange) {
  container.className = "range-picker";
  container.innerHTML = `
    <button data-r="today" class="active">Today</button>
    <button data-r="yesterday">Yesterday</button>
    <button data-r="all">All time</button>
    <button data-r="custom">Custom</button>
    <span id="custom-range-inputs" style="display:none; gap:6px; align-items:center; flex-wrap: wrap;">
      <input type="date" id="range-start" style="width:130px; min-width:0; flex:1 1 130px;">
      <input type="date" id="range-end" style="width:130px; min-width:0; flex:1 1 130px;">
      <button class="btn" id="range-apply" style="padding:6px 10px;">Go</button>
    </span>
  `;
  const customBox = container.querySelector("#custom-range-inputs");
  container.querySelectorAll("button[data-r]").forEach(btn => {
    btn.addEventListener("click", () => {
      container.querySelectorAll("button[data-r]").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const r = btn.dataset.r;
      if (r === "custom") {
        customBox.style.display = "inline-flex";
        return;
      }
      customBox.style.display = "none";
      onChange({ range: r });
    });
  });
  container.querySelector("#range-apply").addEventListener("click", () => {
    const start = container.querySelector("#range-start").value;
    const end = container.querySelector("#range-end").value;
    if (!start || !end) { toast("Pick both dates", true); return; }
    onChange({ range: "custom", start, end });
  });
}
