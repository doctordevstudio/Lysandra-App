buildLayout("notifications", "Notifications");

let currentRange = { range: "today" };
let listCursor = null;
let editingId = null;
let viewersState = null;

async function loadSummary() {
  const data = await api("/api/admin/notifications/clicks-summary", { params: currentRange });
  document.querySelector("#views-card .value").textContent = data.views;
  document.querySelector("#clicks-card .value").textContent = data.clicks;
}

async function loadList(reset) {
  if (reset) { listCursor = null; document.getElementById("notif-table-body").innerHTML = ""; }
  const data = await api("/api/admin/notifications", { params: { cursor: listCursor } });
  const tbody = document.getElementById("notif-table-body");
  for (const n of data.items) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${n.title || ""}</td>
      <td style="max-width:260px; overflow:hidden; text-overflow:ellipsis;">${n.message || ""}</td>
      <td><a href="#" data-id="${n.key}" data-which="view" class="stat-link">${n.total_view || 0}</a></td>
      <td><a href="#" data-id="${n.key}" data-which="click" class="stat-link">${n.total_click || 0}</a></td>
      <td><span class="pill ${n.enabled === false ? "off" : "on"}">${n.enabled === false ? "Disabled" : "Enabled"}</span></td>
      <td>${fmtDate(n.created_at)}</td>
      <td>
        <button class="btn secondary edit-btn" data-id="${n.key}">Edit</button>
        <button class="btn secondary toggle-btn" data-id="${n.key}" data-enabled="${n.enabled !== false}">${n.enabled === false ? "Enable" : "Disable"}</button>
        <button class="btn danger delete-btn" data-id="${n.key}">Delete</button>
      </td>
    `;
    tbody.appendChild(tr);
    tr._data = n;
  }
  document.getElementById("list-load-more").style.display = data.next_cursor ? "block" : "none";
  listCursor = data.next_cursor;
  wireRowButtons();
}

function wireRowButtons() {
  document.querySelectorAll(".stat-link").forEach(el => {
    el.onclick = (e) => { e.preventDefault(); openViewers(el.dataset.id, el.dataset.which); };
  });
  document.querySelectorAll(".edit-btn").forEach(el => {
    el.onclick = () => openForm(el.closest("tr")._data);
  });
  document.querySelectorAll(".toggle-btn").forEach(el => {
    el.onclick = async () => {
      await api(`/api/admin/notifications/${el.dataset.id}`, { method: "PATCH", body: { enabled: el.dataset.enabled !== "true" } });
      toast("Updated");
      loadList(true);
    };
  });
  document.querySelectorAll(".delete-btn").forEach(el => {
    el.onclick = async () => {
      if (!confirm("Delete this notification?")) return;
      await api(`/api/admin/notifications/${el.dataset.id}`, { method: "DELETE" });
      toast("Deleted");
      loadList(true);
    };
  });
}

function openForm(existing) {
  editingId = existing ? existing.key : null;
  document.getElementById("form-title").textContent = existing ? "Edit Notification" : "New Notification";
  document.getElementById("f-title").value = existing?.title || "";
  document.getElementById("f-message").value = existing?.message || "";
  document.getElementById("f-image").value = existing?.image_url || "";
  document.getElementById("f-click").value = existing?.click_url || "";
  document.getElementById("form-save").textContent = existing ? "Save" : "Send";
  document.getElementById("form-modal").classList.add("open");
}

document.getElementById("new-btn").addEventListener("click", () => openForm(null));
document.getElementById("form-cancel").addEventListener("click", () => document.getElementById("form-modal").classList.remove("open"));

document.getElementById("form-save").addEventListener("click", async () => {
  const body = {
    title: document.getElementById("f-title").value.trim(),
    message: document.getElementById("f-message").value.trim(),
    image_url: document.getElementById("f-image").value.trim() || null,
    click_url: document.getElementById("f-click").value.trim() || null,
  };
  if (!body.title || !body.message) { toast("Title and message are required", true); return; }
  if (editingId) {
    await api(`/api/admin/notifications/${editingId}`, { method: "PATCH", body });
  } else {
    await api("/api/admin/notifications", { method: "POST", body });
  }
  document.getElementById("form-modal").classList.remove("open");
  toast(editingId ? "Notification updated" : "Notification sent to all users");
  loadList(true);
});

function openViewers(id, which) {
  viewersState = { id, which, cursor: null };
  document.getElementById("viewers-title").textContent = which === "view" ? "Viewed by" : "Clicked by";
  document.getElementById("viewers-body").innerHTML = "";
  document.getElementById("viewers-modal").classList.add("open");
  fetchViewersPage();
}

async function fetchViewersPage() {
  const data = await api(`/api/admin/notifications/${viewersState.id}/viewers`, {
    params: { which: viewersState.which, cursor: viewersState.cursor },
  });
  const tbody = document.getElementById("viewers-body");
  for (const item of data.items) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${item.device_id || "-"}</td><td>${item.ip || "-"}</td><td>${fmtDate(item.ts)}</td>`;
    tbody.appendChild(tr);
  }
  viewersState.cursor = data.next_cursor;
  document.getElementById("viewers-load-more").style.display = data.next_cursor ? "block" : "none";
}

document.getElementById("viewers-load-more-btn").addEventListener("click", fetchViewersPage);
document.getElementById("viewers-close").addEventListener("click", () => document.getElementById("viewers-modal").classList.remove("open"));
document.getElementById("list-load-more-btn").addEventListener("click", () => loadList(false));

buildRangePicker(document.getElementById("range-picker"), (range) => { currentRange = range; loadSummary(); });

loadSummary();
loadList(true);
