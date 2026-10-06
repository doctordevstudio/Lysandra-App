buildLayout("block", "Block");

let currentRange = { range: "today" };
let hitsCursor = null;

async function loadSummary() {
  const data = await api("/api/admin/block/summary", { params: currentRange });
  document.querySelector("#hits-card .value").textContent = data.total_hits;
}

async function loadList() {
  const data = await api("/api/admin/block");
  const tbody = document.getElementById("table-body");
  tbody.innerHTML = data.items.map(item => `
    <tr>
      <td>${item.domain}</td>
      <td style="max-width:260px; overflow:hidden; text-overflow:ellipsis;">${item.message_html || ""}</td>
      <td>${fmtDate(item.added_at)}</td>
      <td><button class="btn danger remove-btn" data-domain="${item.domain}">Unblock</button></td>
    </tr>
  `).join("");
  tbody.querySelectorAll(".remove-btn").forEach(el => {
    el.onclick = async () => {
      if (!confirm(`Unblock ${el.dataset.domain}?`)) return;
      await api(`/api/admin/block/${el.dataset.domain}`, { method: "DELETE" });
      toast("Unblocked");
      loadList();
    };
  });
}

document.getElementById("new-btn").addEventListener("click", () => document.getElementById("form-modal").classList.add("open"));
document.getElementById("form-cancel").addEventListener("click", () => document.getElementById("form-modal").classList.remove("open"));

document.getElementById("form-save").addEventListener("click", async () => {
  const domains = document.getElementById("f-domains").value.trim();
  const message_html = document.getElementById("f-message").value.trim();
  if (!domains || !message_html) { toast("Domain(s) and message are required", true); return; }
  const result = await api("/api/admin/block", { method: "POST", body: { domains, message_html } });
  document.getElementById("form-modal").classList.remove("open");
  document.getElementById("f-domains").value = "";
  document.getElementById("f-message").value = "";
  toast(`Blocked ${result.blocked.length} domain(s)`);
  loadList();
});

document.querySelector("#hits-card").addEventListener("click", () => {
  hitsCursor = null;
  document.getElementById("hits-body").innerHTML = "";
  const dateInput = document.getElementById("hits-date");
  if (!dateInput.value) dateInput.value = new Date().toISOString().slice(0, 10);
  document.getElementById("hits-modal").classList.add("open");
  fetchHitsPage();
});

document.getElementById("hits-date").addEventListener("change", () => {
  hitsCursor = null;
  document.getElementById("hits-body").innerHTML = "";
  fetchHitsPage();
});

async function fetchHitsPage() {
  const date = document.getElementById("hits-date").value;
  const data = await api("/api/admin/block/hits", { params: { date, cursor: hitsCursor } });
  const tbody = document.getElementById("hits-body");
  for (const item of data.items) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${item.device_id || "-"}</td><td>${item.ip || "-"}</td><td>${item.domain || "-"}</td><td>${fmtDate(item.ts)}</td>`;
    tbody.appendChild(tr);
  }
  hitsCursor = data.next_cursor;
  document.getElementById("hits-load-more").style.display = data.next_cursor ? "block" : "none";
}

document.getElementById("hits-load-more-btn").addEventListener("click", fetchHitsPage);
document.getElementById("hits-close").addEventListener("click", () => document.getElementById("hits-modal").classList.remove("open"));

buildRangePicker(document.getElementById("range-picker"), (range) => { currentRange = range; loadSummary(); });

loadSummary();
loadList();
