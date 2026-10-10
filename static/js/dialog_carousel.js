/* Shared logic for the Dialog and Carousel pages (set ENTITY + FIELD_SET
   globals in the page's inline <script> before loading this file). */
buildLayout(ENTITY, ENTITY === "dialogs" ? "Dialog" : "Carousel");

let currentRange = { range: "today" };
let editingId = null;
let viewersState = null;

async function loadSummary() {
  const data = await api(`/api/admin/${ENTITY}/clicks-summary`, { params: currentRange });
  document.getElementById("views-value").textContent = data.views;
  document.getElementById("clicks-value").textContent = data.clicks;
}

async function loadList() {
  const data = await api(`/api/admin/${ENTITY}`);
  const tbody = document.getElementById("table-body");
  tbody.innerHTML = "";
  for (const item of data.items) {
    const tr = document.createElement("tr");
    const messageCell = FIELD_SET === "dialog" ? `<td style="max-width:220px; overflow:hidden; text-overflow:ellipsis;">${item.message_html || ""}</td>` : "";
    tr.innerHTML = `
      <td>${item.sort_order ?? 0}</td>
      ${messageCell}
      <td>${item.image_url ? `<img src="${item.image_url}" style="width:48px;height:48px;object-fit:cover;border-radius:6px;">` : "-"}</td>
      <td><a href="#" data-which="view" class="stat-link">${item.total_view || 0}</a></td>
      <td><a href="#" data-which="click" class="stat-link">${item.total_click || 0}</a></td>
      <td><span class="pill ${item.enabled === false ? "off" : "on"}">${item.enabled === false ? "Disabled" : "Enabled"}</span></td>
      <td>
        <button class="btn secondary edit-btn">Edit</button>
        <button class="btn secondary toggle-btn" data-enabled="${item.enabled !== false}">${item.enabled === false ? "Enable" : "Disable"}</button>
        <button class="btn danger delete-btn">Delete</button>
      </td>
    `;
    tr._data = item;
    tbody.appendChild(tr);
    tr.querySelectorAll(".stat-link").forEach(el => { el.onclick = (e) => { e.preventDefault(); openViewers(item.id, el.dataset.which); }; });
    tr.querySelector(".edit-btn").onclick = () => openForm(item);
    tr.querySelector(".toggle-btn").onclick = async () => {
      await api(`/api/admin/${ENTITY}/${item.id}`, { method: "PATCH", body: { enabled: tr.querySelector(".toggle-btn").dataset.enabled !== "true" } });
      toast("Updated");
      loadList();
    };
    tr.querySelector(".delete-btn").onclick = async () => {
      if (!confirm("Delete this item?")) return;
      await api(`/api/admin/${ENTITY}/${item.id}`, { method: "DELETE" });
      toast("Deleted");
      loadList();
    };
  }
}

function openForm(existing) {
  editingId = existing ? existing.id : null;
  document.getElementById("form-title").textContent = existing ? "Edit" : (ENTITY === "dialogs" ? "New Dialog" : "New Carousel Item");
  if (FIELD_SET === "dialog") document.getElementById("f-message").value = existing?.message_html || "";
  document.getElementById("f-image").value = existing?.image_url || "";
  document.getElementById("f-click").value = existing?.click_url || "";
  document.getElementById("f-sort").value = existing?.sort_order ?? 0;
  document.getElementById("form-modal").classList.add("open");
}

document.getElementById("new-btn").addEventListener("click", () => openForm(null));
document.getElementById("form-cancel").addEventListener("click", () => document.getElementById("form-modal").classList.remove("open"));

document.getElementById("form-save").addEventListener("click", async () => {
  const body = {
    image_url: document.getElementById("f-image").value.trim() || null,
    click_url: document.getElementById("f-click").value.trim() || null,
    sort_order: parseInt(document.getElementById("f-sort").value || "0", 10),
  };
  if (FIELD_SET === "dialog") body.message_html = document.getElementById("f-message").value.trim();
  if (ENTITY === "carousel" && !body.image_url) { toast("Image URL is required", true); return; }

  if (editingId) {
    await api(`/api/admin/${ENTITY}/${editingId}`, { method: "PATCH", body });
  } else {
    await api(`/api/admin/${ENTITY}`, { method: "POST", body });
  }
  document.getElementById("form-modal").classList.remove("open");
  toast("Saved");
  loadList();
});

function openViewers(id, which) {
  viewersState = { id, which, cursor: null };
  document.getElementById("viewers-title").textContent = which === "view" ? "Viewed by" : "Clicked by";
  document.getElementById("viewers-body").innerHTML = "";
  document.getElementById("viewers-modal").classList.add("open");
  fetchViewersPage();
}

async function fetchViewersPage() {
  const data = await api(`/api/admin/${ENTITY}/${viewersState.id}/viewers`, { params: { which: viewersState.which, cursor: viewersState.cursor } });
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

buildRangePicker(document.getElementById("range-picker"), (range) => { currentRange = range; loadSummary(); });

loadSummary();
loadList();
