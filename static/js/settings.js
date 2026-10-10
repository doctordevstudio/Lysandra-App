buildLayout("settings", "Settings");

const FIELD_MAP = {
  "s-maintenance-mode": { key: "maintenance_mode", type: "checkbox" },
  "s-maintenance-message": { key: "maintenance_message_html", type: "text" },
  "s-ads-enabled": { key: "ads_enabled", type: "checkbox" },
  "s-startio-enabled": { key: "startio_enabled", type: "checkbox" },
  "s-startio-app-id": { key: "startio_app_id", type: "text" },
  "s-startio-banner-id": { key: "startio_banner_id", type: "text" },
  "s-startio-interstitial-id": { key: "startio_interstitial_id", type: "text" },
  "s-startio-rewarded-id": { key: "startio_rewarded_id", type: "text" },
  "s-startio-native-id": { key: "startio_native_id", type: "text" },
  "s-monetag-enabled": { key: "monetag_enabled", type: "checkbox" },
  "s-monetag-zone-id": { key: "monetag_zone_id", type: "text" },
  "s-monetag-direct-link": { key: "monetag_direct_link_url", type: "text" },
  "s-carousel-enabled": { key: "carousel_enabled", type: "checkbox" },
  "s-dialog-enabled": { key: "dialog_enabled", type: "checkbox" },
  "s-theme-default": { key: "theme_default", type: "text" },
  "s-theme-toggle": { key: "theme_allow_toggle", type: "checkbox" },
  "s-terms": { key: "terms_html", type: "text" },
  "s-privacy": { key: "privacy_html", type: "text" },
  "s-support-telegram": { key: "customer_support_telegram", type: "text" },
  "s-dev-telegram": { key: "developer_telegram", type: "text" },
  "s-dev-name": { key: "developer_name", type: "text" },
  "s-dev-bio": { key: "developer_bio", type: "text" },
  "s-dev-image": { key: "developer_image_url", type: "text" },
  "s-dev-rate": { key: "developer_rate", type: "text" },
  "s-latest-version": { key: "latest_version", type: "text" },
  "s-update-url": { key: "update_channel_url", type: "text" },
  "s-proxies": { key: "youtube_proxies", type: "list" },
};

async function loadSettings() {
  const data = await api("/api/admin/settings");
  for (const [elId, def] of Object.entries(FIELD_MAP)) {
    const el = document.getElementById(elId);
    const val = data[def.key];
    if (def.type === "checkbox") el.checked = !!val;
    else if (def.type === "list") el.value = Array.isArray(val) ? val.join("\n") : "";
    else el.value = val ?? "";
  }
}

document.getElementById("save-btn").addEventListener("click", async () => {
  const body = {};
  for (const [elId, def] of Object.entries(FIELD_MAP)) {
    const el = document.getElementById(elId);
    if (def.type === "checkbox") body[def.key] = el.checked;
    else if (def.type === "list") body[def.key] = el.value.split("\n").map(s => s.trim()).filter(Boolean);
    else body[def.key] = el.value;
  }
  await api("/api/admin/settings", { method: "PATCH", body });
  toast("Settings saved and pushed live");
});

loadSettings();
