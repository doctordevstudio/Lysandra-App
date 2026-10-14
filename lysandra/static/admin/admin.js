'use strict';
/* Lysandra admin panel – vanilla JS. All dynamic text goes through esc(); no inline scripts (CSP). */
const $ = (s, r = document) => r.querySelector(s);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const ADMIN_ROOT = ((document.querySelector('meta[name="lys-admin"]') || {}).content || location.pathname).replace(/\/+$/, '');
const BASE = ADMIN_ROOT + '/api';
const ASSET = ADMIN_ROOT + '/static/';
// if anything fails while starting, say so instead of leaving a blank page
window.addEventListener('error', e => { const a = document.getElementById('app'); if (a && /^\s*Loading/.test(a.textContent)) a.textContent = 'Admin panel error: ' + e.message; });
const S = {csrf: '', user: '', page: 'dashboard', range: null, idle: 0};
const fmt = ts => ts ? new Date(ts * 1000).toLocaleString('en-IN', {timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit'}) : '-';
const istDate = (off = 0) => { const d = new Date(Date.now() + off * 864e5); return new Intl.DateTimeFormat('en-CA', {timeZone: 'Asia/Kolkata'}).format(d); };
const num = n => Number(n || 0).toLocaleString('en-IN');
const toIstInput = ts => new Date(ts * 1000 + 19800000).toISOString().slice(0, 16);
const fromIstInput = v => Math.floor(Date.parse(v + ':00+05:30') / 1000);
async function planOptions() { const c = (await get('/settings')).config.premium.plans; return c.map(p => [p.id, p.name]); }
const inr = n => '₹' + Number(n || 0).toLocaleString('en-IN');

function toast(m, kind = '') { const t = document.createElement('div'); t.className = 't ' + kind; t.textContent = m; $('#toast').append(t); setTimeout(() => t.remove(), 3800); }

async function api(method, path, body) {
  const opt = {method, headers: {'X-CSRF-Token': S.csrf}, credentials: 'same-origin'};
  if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  const r = await fetch(BASE + path, opt);
  let j = {}; try { j = await r.json(); } catch (e) {}
  if (r.status === 401 && !path.startsWith('/auth/login')) { showLogin('Session expired. Please sign in again.'); throw new Error('auth'); }
  if (!r.ok) { const e = new Error(j.error || 'Request failed'); e.data = j; e.status = r.status; throw e; }
  return j;
}
const get = p => api('GET', p), post = (p, b) => api('POST', p, b || {}), put = (p, b) => api('PUT', p, b || {}), del = p => api('DELETE', p);
const guard = fn => async (...a) => { try { return await fn(...a); } catch (e) { if (e.message !== 'auth') toast(e.message, 'bad'); } };

/* ---------- modal ---------- */
function modal(title, html, {small = false} = {}) {
  const m = document.createElement('div'); m.className = 'modal';
  m.innerHTML = `<div class="mbox ${small ? 'sm' : ''}"><div class="mhead"><h3>${esc(title)}</h3><button class="g s" data-x>✕</button></div><div data-b>${html}</div></div>`;
  m.addEventListener('mousedown', e => { if (e.target === m) m.remove(); });
  $('[data-x]', m).onclick = () => m.remove();
  document.body.append(m); return m;
}

/* ---------- fingerprint ---------- */
async function fingerprint() {
  const c = document.createElement('canvas').getContext('2d'); c.font = '14px Arial'; c.fillText('Lysandra✓', 4, 14);
  const raw = [navigator.userAgent, navigator.language, screen.width + 'x' + screen.height, screen.colorDepth, Intl.DateTimeFormat().resolvedOptions().timeZone,
    navigator.hardwareConcurrency, c.canvas.toDataURL().slice(-60)].join('|');
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(raw));
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('').slice(0, 40);
}

/* ---------- login ---------- */
function showLogin(msg) {
  document.documentElement.dataset.theme = localStorage.getItem('lys_theme') || 'day';
  $('#app').innerHTML = `<div class="login"><div style="margin-top:12vh"><img src="${ASSET}icon.png" alt=""><h1>Lysandra</h1></div>
  <div class="card"><h3>Admin sign in</h3>${msg ? `<p class="hint" style="color:var(--bad)">${esc(msg)}</p>` : ''}
  <label class="f">Username<input id="u" autocomplete="username"></label>
  <label class="f">Password<input id="p" type="password" autocomplete="current-password"></label>
  <button class="o" id="go" style="width:100%">Sign in</button><p class="hint" id="err" style="color:var(--bad);margin-top:10px"></p></div></div>
  <footer>©️Copyright by Dr. Dev || Dr. Hamza 2026 All Rights Reserved.</footer>`;
  const go = async () => {
    $('#go').disabled = true; $('#err').textContent = '';
    try {
      const r = await fetch(BASE + '/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json'}, credentials: 'same-origin',
        body: JSON.stringify({username: $('#u').value, password: $('#p').value, fp: await fingerprint()})});
      const j = await r.json();
      if (r.ok) { S.csrf = j.csrf; boot(); return; }
      $('#err').textContent = j.locked ? 'This device is locked until ' + fmt(j.locked_until) + ' after too many failed attempts.' : (j.error || 'Login failed');
    } catch (e) { $('#err').textContent = 'Network error'; }
    $('#go').disabled = false;
  };
  $('#go').onclick = go; $('#p').onkeydown = e => { if (e.key === 'Enter') go(); };
}

/* ---------- shell ---------- */
const NAV = [['dashboard', '📊', 'Dashboard'], ['users', '👥', 'Users'], ['notifications', '🔔', 'Notification'], ['dialogs', '💬', 'Dialog'],
  ['carousel', '🖼️', 'Carousel'], ['videos', '🎬', 'Videos'], ['apps', '🧩', 'Apps'], ['blocks', '⛔', 'Block'], ['premium', '👑', 'Premium'], ['payments', '💳', 'Payments'],
  ['settings', '⚙️', 'Settings'], ['logs', '📜', 'Logs']];

async function boot() {
  let me; try { me = await (await fetch(BASE + '/auth/me', {credentials: 'same-origin'})).json(); } catch (e) { me = {}; }
  if (!me.auth) return showLogin();
  S.csrf = me.csrf; S.user = me.user; S.info = me;
  document.documentElement.dataset.theme = localStorage.getItem('lys_theme') || 'day';
  $('#app').innerHTML = `<div class="shell"><aside class="side" id="side"><div class="brand"><img src="${ASSET}icon.png" alt=""><b>Lysandra</b></div>
  <nav class="nav">${NAV.map(n => `<a data-p="${n[0]}">${n[1]} ${n[2]}</a>`).join('')}</nav></aside>
  <div class="main"><div class="top"><button class="g s burger" id="bg">☰</button><h2 id="title"></h2><span class="mu" id="who"></span>
  <button class="g s" id="th">🌓</button><button class="g s" id="lo">Logout</button></div><div class="page" id="page"></div>
  <footer>©️Copyright by Dr. Dev || Dr. Hamza 2026 All Rights Reserved.</footer></div></div>`;
  $('#who').textContent = '👤 ' + S.user + ' · IST';
  $('#bg').onclick = () => $('#side').classList.toggle('open');
  $('#th').onclick = () => { const n = document.documentElement.dataset.theme === 'day' ? 'night' : 'day'; document.documentElement.dataset.theme = n; localStorage.setItem('lys_theme', n); };
  $('#lo').onclick = guard(async () => { await post('/auth/logout'); showLogin(); });
  document.querySelectorAll('.nav a').forEach(a => a.onclick = () => { location.hash = a.dataset.p; $('#side').classList.remove('open'); });
  window.onhashchange = route; route();
}
function route() {
  const p = (location.hash || '#dashboard').slice(1); S.page = PAGES[p] ? p : 'dashboard';
  document.querySelectorAll('.nav a').forEach(a => a.classList.toggle('on', a.dataset.p === S.page));
  $('#title').textContent = NAV.find(n => n[0] === S.page)[2];
  $('#page').innerHTML = '<p class="mu">Loading…</p>';
  guard(PAGES[S.page])($('#page'));
}

/* ---------- reusable UI ---------- */
function table(cols, rows, empty = 'Nothing here yet') {
  if (!rows.length) return `<p class="mu" style="padding:12px">${esc(empty)}</p>`;
  return `<div class="tw"><table><thead><tr>${cols.map(c => `<th>${esc(c[0])}</th>`).join('')}</tr></thead><tbody>${rows.map(r => `<tr>${cols.map(c => `<td>${c[1](r)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}
function rangeBar(onChange, preset) {
  const a = (S.range && S.range[0]) || istDate(-6), b = (S.range && S.range[1]) || istDate();
  const el = document.createElement('div'); el.className = 'row'; el.style.marginBottom = '14px';
  el.innerHTML = `<span class="mu">Custom range (IST)</span><input type="date" id="rf" value="${a}" style="width:auto"><input type="date" id="rt" value="${b}" style="width:auto"><button class="o s" id="rg">Apply</button>`;
  $('#rg', el).onclick = () => { S.range = [$('#rf', el).value, $('#rt', el).value]; onChange(); };
  return el;
}
function periodDates(period, d) {
  const r = S.range || [istDate(-6), istDate()];
  return {today: [istDate(), istDate()], yesterday: [istDate(-1), istDate(-1)], all: ['all', 'all'], range: r}[period];
}
function stat(label, val, {kind, period, o = false, fmtv = num} = {}) {
  const c = kind ? ` click" data-k="${esc(kind)}" data-pd="${esc(period)}` : '';
  return `<div class="stat${o ? ' o' : ''}${c}"><small>${esc(label)}</small><b>${esc(fmtv(val))}</b></div>`;
}
function wireDrill(root, title) {
  root.querySelectorAll('.stat.click').forEach(s => s.onclick = () => eventsModal(title ? title : s.dataset.k, s.dataset.k, periodDates(s.dataset.pd)));
}
async function eventsModal(title, kind, [from, to]) {
  const m = modal(`${title} · ${from === 'all' ? 'last 365 days' : from === to ? from : from + ' → ' + to}`, '<div id="ev"></div><div class="pager"><button class="g s" id="more" style="display:none">Load more</button></div>');
  let cursor = '', rows = [];
  const load = guard(async () => {
    const j = await get(`/events?kind=${encodeURIComponent(kind)}&from=${from}&to=${to}&limit=25&cursor=${encodeURIComponent(cursor)}`);
    rows = rows.concat(j.items); cursor = j.next; $('#more', m).style.display = cursor ? '' : 'none';
    $('#ev', m).innerHTML = table([['Time (IST)', r => fmt(r.ts)], ['Device ID', r => `<a class="mono" data-u="${esc(r.dev)}">${esc((r.dev || '').slice(0, 14))}…</a>`],
      ['IP', r => esc(r.ip)], ['Device', r => esc([r.brand, r.model].filter(Boolean).join(' '))],
      ['Detail', r => esc(r.domain || r.host || r.item || r.why || (r.env || []).join(',') || '')]], rows);
    $('#ev', m).querySelectorAll('[data-u]').forEach(a => a.onclick = () => userModal(a.dataset.u));
  });
  $('#more', m).onclick = load; load();
}
async function userModal(dev) {
  const j = await get('/user/' + dev), u = j.user || {};
  const prem = j.premium, ov = j.override || {}, q = j.quota_today || {};
  const planOpts = await planOptions();
  const m = modal('User ' + dev.slice(0, 12) + '…', `
  <div class="mono" style="margin-bottom:10px">${esc(dev)}</div>
  <div class="grid g3"><div class="stat"><small>IP</small><b style="font-size:16px">${esc(u.ip)}</b></div><div class="stat"><small>Device</small><b style="font-size:16px">${esc((u.brand || '') + ' ' + (u.model || ''))}</b></div>
  <div class="stat"><small>Android / App</small><b style="font-size:16px">${esc(u.android)} / v${esc(u.ver)}</b></div>
  <div class="stat"><small>Fetch ok / failed</small><b>${num(u.fetch_ok)} / ${num(u.fetch_fail)}</b></div><div class="stat"><small>Interstitial / Rewarded</small><b>${num(u.ad_interstitial)} / ${num(u.ad_rewarded)}</b></div>
  <div class="stat"><small>First seen</small><b style="font-size:14px">${fmt(u.first_seen)}</b></div></div>
  <p class="row" style="margin:12px 0"><span class="tag ${prem && prem.status === 'active' ? 'ok' : ''}">${prem ? 'Premium: ' + esc(prem.status) + ' · ' + esc(prem.plan_name) : 'Free user'}</span>
  ${j.banned ? '<span class="tag bad">BANNED</span>' : ''}${j.canon !== dev ? `<span class="tag warn">linked to ${esc(j.canon.slice(0, 10))}…</span>` : ''}<span class="sp"></span>
  <button class="${j.banned ? 'g' : 'r'} s" id="bn">${j.banned ? 'Unban device' : 'Ban device'}</button></p>
  ${j.linked.length ? `<p class="hint">Clone / extra devices sharing this account: ${j.linked.map(x => `<a class="mono" data-u="${esc(x)}">${esc(x.slice(0, 10))}…</a>`).join(', ')}</p>` : ''}
  ${j.canon !== dev ? '<p class="hint">This device is a clone of another install on the same phone. <a id="ul">Unlink it</a> to give it its own account.</p>' : ''}
  <div class="card" style="margin:12px 0"><h3>✏️ Edit user</h3>
    <div class="grid g2"><label class="f">Notes<textarea id="e_notes">${esc(u.notes || '')}</textarea></label>
    <div><label class="f">Brand<input id="e_brand" value="${esc(u.brand || '')}"></label><label class="f">Model<input id="e_model" value="${esc(u.model || '')}"></label></div></div>
    <div class="grid g4"><label class="f">Fetch ok<input type="number" id="e_fetch_ok" value="${u.fetch_ok || 0}"></label><label class="f">Fetch failed<input type="number" id="e_fetch_fail" value="${u.fetch_fail || 0}"></label>
    <label class="f">Downloads used today<input type="number" id="e_dl_used" value="${q.dl_used || 0}"></label><label class="f">Watch used today<input type="number" id="e_w_used" value="${q.w_used || 0}"></label></div>
    <div class="grid g4"><label class="f">Own downloads / day<input type="number" id="e_ov_dl" placeholder="default" value="${ov.dl ?? ''}"></label><label class="f">Own watch / day<input type="number" id="e_ov_w" placeholder="default" value="${ov.w ?? ''}"></label></div>
    <p class="hint">Own limits replace the free limits for this user only. Leave empty to use the global free limits.</p>
    <button class="o" id="eu">Save changes</button></div>
  <div class="card" style="margin:12px 0"><h3>👑 Subscription</h3>
    <div class="grid g4"><label class="f">Plan<select id="p_plan">${planOpts.map(o => `<option value="${esc(o[0])}" ${prem && prem.plan_id === o[0] ? 'selected' : ''}>${esc(o[1])}</option>`).join('')}</select></label>
    <label class="f">Start (IST)<input type="datetime-local" id="p_start" value="${prem && prem.started ? toIstInput(prem.started) : ''}"></label>
    <label class="f">Expiry (IST)<input type="datetime-local" id="p_exp" value="${prem && prem.expires ? toIstInput(prem.expires) : ''}"></label>
    <label class="f">Renew +days<input type="number" id="p_days" value="30"></label></div>
    <div class="row"><button class="o s" id="ps">Save subscription</button><button class="g s" id="pr">Renew</button><button class="r s" id="pv">Revoke</button></div></div>
  <h3 style="margin:10px 0">Login logs (${j.logs.length})</h3>${table([['Time', r => fmt(r.ts)], ['IP', r => esc(r.ip)], ['Model', r => esc(r.model)], ['Android', r => esc(r.android)], ['App', r => 'v' + esc(r.ver)]], j.logs)}
  <h3 style="margin:14px 0 8px">Seen / clicked</h3>${['dialogs', 'carousel', 'notifications'].map(k => `<p class="mu"><b>${k}</b>: ${(j.engagement[k] || []).map(e => esc(e.title) + (e.c ? ' (clicked)' : ' (seen)')).join(', ') || '—'}</p>`).join('')}
  <h3 style="margin:14px 0 8px">Transactions</h3>${table([['Txn', r => `<span class="mono">${esc(r.txn_id)}</span>`], ['Plan', r => esc(r.plan_name)], ['₹', r => r.amount], ['Status', r => statusTag(r.status)], ['Time', r => fmt(r.created)]], j.txns)}
  <p style="margin-top:16px"><button class="r s" id="du">Delete this user</button></p>`);
  const again = () => { m.remove(); userModal(dev); };
  m.querySelectorAll('[data-u]').forEach(a => a.onclick = () => userModal(a.dataset.u));
  const ul = $('#ul', m); if (ul) ul.onclick = guard(async () => { await post(`/user/${dev}/unlink`); toast('Unlinked', 'ok'); again(); });
  $('#bn', m).onclick = guard(async () => { await post(`/user/${dev}/ban`, {banned: !j.banned}); toast('Updated', 'ok'); again(); });
  const val = id => $('#' + id, m).value;
  $('#eu', m).onclick = guard(async () => {
    const ovb = {}; if (val('e_ov_dl') !== '') ovb.dl = +val('e_ov_dl'); if (val('e_ov_w') !== '') ovb.w = +val('e_ov_w');
    await put('/user/' + dev, {notes: val('e_notes'), brand: val('e_brand'), model: val('e_model'), fetch_ok: +val('e_fetch_ok'), fetch_fail: +val('e_fetch_fail'), dl_used: +val('e_dl_used'), w_used: +val('e_w_used'), override: ovb});
    toast('User saved', 'ok'); again();
  });
  const pdev = j.canon;
  $('#ps', m).onclick = guard(async () => { const b = {plan_id: val('p_plan')}; if (val('p_start')) b.started = fromIstInput(val('p_start')); if (val('p_exp')) b.expires = fromIstInput(val('p_exp')); await post(`/premium/${pdev}/edit`, b); toast('Subscription saved', 'ok'); again(); });
  $('#pr', m).onclick = guard(async () => { await post(`/premium/${pdev}/renew`, {days: +val('p_days')}); toast('Renewed', 'ok'); again(); });
  $('#pv', m).onclick = guard(async () => { if (confirm('Revoke premium now?')) { await post(`/premium/${pdev}/revoke`, {reason: 'admin'}); toast('Revoked', 'ok'); again(); } });
  $('#du', m).onclick = guard(async () => { if (confirm('Delete this user and all of their logs? This cannot be undone.')) { await del(`/user/${dev}?premium=${confirm('Also delete their premium subscription?') ? 1 : 0}`); toast('Deleted', 'ok'); m.remove(); route(); } });
}
const statusTag = s => `<span class="tag ${s === 'success' ? 'ok' : s === 'failed' ? 'bad' : 'warn'}">${esc(s)}</span>`;

function formModal(title, fields, vals, onSave, {small = true} = {}) {
  const html = fields.map(f => {
    const v = vals[f.k] ?? f.def ?? '';
    if (f.type === 'checkbox') return `<label class="f chk"><input type="checkbox" data-k="${f.k}" ${v ? 'checked' : ''}> ${esc(f.label)}</label>`;
    if (f.type === 'select') return `<label class="f">${esc(f.label)}<select data-k="${f.k}">${(f.options || []).map(o => `<option value="${esc(o[0])}" ${o[0] === v ? 'selected' : ''}>${esc(o[1])}</option>`).join('')}</select></label>`;
    if (f.type === 'textarea') return `<label class="f">${esc(f.label)}<textarea data-k="${f.k}" placeholder="${esc(f.ph || '')}">${esc(v)}</textarea></label>`;
    return `<label class="f">${esc(f.label)}<input data-k="${f.k}" type="${f.type || 'text'}" value="${esc(v)}" placeholder="${esc(f.ph || '')}"></label>`;
  }).join('') + (fields.some(f => f.hint) ? `<p class="hint">${fields.filter(f => f.hint).map(f => esc(f.hint)).join(' ')}</p>` : '') + '<button class="o" id="sv">Save</button>';
  const m = modal(title, html, {small});
  $('#sv', m).onclick = guard(async () => {
    const o = {}; m.querySelectorAll('[data-k]').forEach(e => o[e.dataset.k] = e.type === 'checkbox' ? e.checked : e.value);
    $('#sv', m).disabled = true;
    try { await onSave(o); m.remove(); } catch (e) { $('#sv', m).disabled = false; throw e; }
  });
}
const CHECK = (cb) => async () => { try { await cb(); } catch (e) { if (e.message !== 'auth') toast(e.message, 'bad'); } };

/* ---------- user search (dashboard) ---------- */
function searchCard() {
  const c = document.createElement('div'); c.className = 'card';
  c.innerHTML = `<h3>🔍 Find a user</h3><div class="row"><input id="uq" placeholder="Device ID (full or first characters), IP, model or note" style="max-width:520px"><button class="o" id="uqb">Search</button></div><div id="ur" style="margin-top:12px"></div>`;
  const run = guard(async () => {
    const q = $('#uq', c).value.trim(); if (q.length < 3) { toast('Type at least 3 characters', 'bad'); return; }
    const j = await get('/users/search?q=' + encodeURIComponent(q));
    $('#ur', c).innerHTML = table([['Device ID', r => `<a class="mono" data-u="${esc(r.id)}">${esc(r.id)}</a>`], ['IP', r => esc(r.ip)], ['Device', r => esc((r.brand + ' ' + r.model).trim())], ['Last seen', r => fmt(r.last_seen)], ['Note', r => esc(r.notes)]], j.items, 'No user found');
    c.querySelectorAll('[data-u]').forEach(a => a.onclick = () => userModal(a.dataset.u));
  });
  $('#uqb', c).onclick = run; $('#uq', c).onkeydown = e => { if (e.key === 'Enter') run(); };
  return c;
}

/* ---------- dashboard ---------- */
const AD_LABEL = {interstitial: 'Interstitial', rewarded: 'Rewarded', banner: 'Banner', native: 'Native'};
const PAGES = {};
PAGES.dashboard = async root => {
  const draw = guard(async () => {
    const [a, b] = S.range || [istDate(-6), istDate()];
    const d = await get(`/dashboard?from=${a}&to=${b}`), P = ['today', 'yesterday', 'all', 'range'], PL = {today: 'Today', yesterday: 'Yesterday', all: 'All time', range: 'Range'};
    const row = (title, key, o) => `<div class="card"><h3>${title}</h3><div class="grid g4">${P.map(p => stat(PL[p], d[p][key], {kind: key, period: p, o})).join('')}</div></div>`;
    const ads = {}; P.forEach(p => Object.entries(d[p]).forEach(([k, v]) => { if (k.startsWith('ad_')) { (ads[k] = ads[k] || {})[p] = v; } }));
    const adRows = Object.keys(ads).sort().map(k => { const [, t, pf, ...ac] = k.split('_'); return {k, t, pf, ac: ac.join('_'), v: ads[k]}; });
    root.innerHTML = '';
    root.append(searchCard());
    root.append(rangeBar(draw));
    const wrap = document.createElement('div');
    wrap.innerHTML = `
    <div class="card"><h3>👥 Users</h3><div class="grid g4">${P.map(p => stat((p === 'all' ? 'Total' : 'New ' + PL[p]), d[p].new_user, {kind: 'new_user', period: p, o: true})).join('')}</div>
    <div class="grid g4" style="margin-top:12px">${P.slice(0, 2).map(p => stat('Active ' + PL[p], d[p].active, {kind: 'active', period: p})).join('')}${stat('Yesterday users active today', d.yesterday_active_today)}${stat('Open in maintenance (today)', d.today.maint_open, {kind: 'maint_open', period: 'today'})}</div></div>
    ${row('🔎 Fetch success', 'fetch_ok')}${row('❗ Fetch failed', 'fetch_fail')}${row('⛔ Admin-blocked domain hits', 'blocked_hit')}${row('🛡️ Blocked by VPN / proxy / emulator checks', 'env_blocked')}${row('🧬 Clone / parallel-space copies refused', 'clone_blocked')}${row('⬇ APK downloads from the landing page', 'apk_download')}
    <div class="card"><h3>📺 Ads by platform & action <span class="tag">Start.io</span></h3>${table([['Type', r => esc(AD_LABEL[r.t] || r.t)], ['Platform', r => esc(r.pf)], ['Action / page', r => esc(r.ac)],
      ...P.map(p => [PL[p], r => r.t === 'interstitial' || r.t === 'rewarded' ? `<a data-ad="${esc(r.k)}" data-pd="${p}">${num(r.v[p])}</a>` : num(r.v[p])])], adRows, 'No ad impressions recorded yet')}</div>
    <div class="card"><h3>👑 Premium</h3><div class="grid g4">${stat('Earned today', d.premium.today.amount, {fmtv: inr, o: true})}${stat('Earned yesterday', d.premium.yesterday.amount, {fmtv: inr, o: true})}${stat('Earned all time', d.premium.all.amount, {fmtv: inr, o: true})}${stat('Earned (range)', d.premium.range.amount, {fmtv: inr, o: true})}
    ${stat('Active premium users', d.premium.active)}${stat('Purchases today', d.premium.today.count)}${stat('Purchases all time', d.premium.all.count)}${stat('Purchases (range)', d.premium.range.count)}</div></div>
    ${['dialog', 'carousel', 'notification'].map(k => `<div class="card"><h3>${k === 'notification' ? '🔔' : k === 'dialog' ? '💬' : '🖼️'} ${k[0].toUpperCase() + k.slice(1)} views & clicks</h3><div class="grid g4">${P.map(p => stat(PL[p] + ' · views / clicks', 0).replace('<b>0</b>', `<b>${num(d[p][k + '_view'])} / ${num(d[p][k + '_click'])}</b>`)).join('')}</div></div>`).join('')}
    <div class="card"><h3>📈 Daily (range)</h3>${table([['Date', r => esc(r[0])], ['New users', r => num(r[1].new_user)], ['Active', r => num(r[1].active)], ['Fetch ok', r => num(r[1].fetch_ok)], ['Fetch failed', r => num(r[1].fetch_fail)], ['Blocked hits', r => num(r[1].blocked_hit)]], Object.entries(d.range_days).reverse())}</div>`;
    root.append(wrap); wireDrill(wrap);
    wrap.querySelectorAll('[data-ad]').forEach(x => x.onclick = () => eventsModal('Ad events', x.dataset.ad, periodDates(x.dataset.pd)));
  });
  draw();
};

/* ---------- users ---------- */
PAGES.users = async root => {
  const j = await get('/top-users');
  root.innerHTML = `<div class="card"><h3>🔍 Find a user</h3><div class="row"><input id="q" placeholder="Paste full device ID" style="max-width:420px"><button class="o" id="fq">Open</button></div></div>
  <div class="card"><h3>🏆 Top 50 users by fetches</h3>${table([['Device ID', r => `<a class="mono" data-u="${esc(r.id)}">${esc(r.id.slice(0, 14))}…</a>`], ['IP', r => esc(r.ip)], ['Device', r => esc(r.brand + ' ' + r.model)],
    ['Fetch ✓', r => num(r.fetch_ok)], ['Fetch ✗', r => num(r.fetch_fail)], ['Interstitial', r => num(r.ad_interstitial)], ['Rewarded', r => num(r.ad_rewarded)], ['Last seen', r => fmt(r.last_seen)]], j.items, 'No users yet')}</div>`;
  root.querySelectorAll('[data-u]').forEach(a => a.onclick = () => userModal(a.dataset.u));
  $('#fq').onclick = guard(() => userModal($('#q').value.trim().toLowerCase()));
};

/* ---------- dialogs / carousel / notifications / apps ---------- */
const CONTENT = {
  notifications: {icon: '🔔', singular: 'notification', summary: true, fields: [{k: 'image_url', label: 'Image URL (optional)'}, {k: 'title', label: 'Title'}, {k: 'message', label: 'Message', type: 'textarea'}, {k: 'url', label: 'On click URL (optional)'}, {k: 'enabled', label: 'Enabled', type: 'checkbox', def: true}],
    cols: [['Image', r => r.image_url ? `<img class="thumb" src="${esc(r.image_url)}" alt="">` : ''], ['Title', r => `<b>${esc(r.title)}</b><div class="mu">${esc((r.message || '').slice(0, 70))}</div>`]]},
  dialogs: {icon: '💬', singular: 'dialog', summary: true, fields: [{k: 'image_url', label: 'Image URL (optional)'}, {k: 'message', label: 'Message (text / HTML, optional if image given)', type: 'textarea'}, {k: 'url', label: 'On click URL (optional)'}, {k: 'sort', label: 'Sort order', type: 'number', def: 0, hint: 'Existing dialogs with the same or higher consecutive sort move down by one.'}, {k: 'enabled', label: 'Enabled', type: 'checkbox', def: true}],
    cols: [['Sort', r => `<span class="tag">${r.sort}</span>`], ['Image', r => r.image_url ? `<img class="thumb" src="${esc(r.image_url)}" alt="">` : ''], ['Message', r => esc((r.message || '').replace(/<[^>]*>/g, ' ').slice(0, 80))]]},
  carousel: {icon: '🖼️', singular: 'carousel', summary: true, fields: [{k: 'image_url', label: 'Image URL'}, {k: 'url', label: 'On click URL (leave empty = no redirect)'}, {k: 'sort', label: 'Sort order', type: 'number', def: 0}, {k: 'enabled', label: 'Enabled', type: 'checkbox', def: true}],
    cols: [['Sort', r => `<span class="tag">${r.sort}</span>`], ['Image', r => `<img class="thumb" style="width:90px" src="${esc(r.image_url)}" alt="">`]]},
  apps: {icon: '🧩', singular: 'app tile', summary: false, fields: [{k: 'name', label: 'Website / app name'}, {k: 'url', label: 'Website URL (optional)'}, {k: 'icon_url', label: 'Icon URL (optional)'}, {k: 'domain', label: 'Domain for auto-fill (optional, e.g. youtube.com)'}, {k: 'sort', label: 'Sort number', type: 'number', def: 0}, {k: 'highlight', label: 'Highlight (shaking animation)', type: 'checkbox'}, {k: 'enabled', label: 'Enabled', type: 'checkbox', def: true}],
    cols: [['Sort', r => `<span class="tag">${r.sort}</span>`], ['App', r => `<b>${esc(r.name)}</b><div class="mu">${esc(r.url || '')}</div>`], ['Highlight', r => r.highlight ? '✨' : '']]},
};
function contentPage(kind) {
  const C = CONTENT[kind];
  return async root => {
    const draw = guard(async () => {
      const items = (await get('/content/' + kind)).items;
      const sm = C.summary ? await get(`/content/${kind}/summary?from=${(S.range || [istDate(-6)])[0]}&to=${(S.range || [0, istDate()])[1]}`) : null;
      const ev = kind.replace(/s$/, '');
      root.innerHTML = '';
      if (sm) {
        root.append(rangeBar(draw));
        const c = document.createElement('div'); c.className = 'card';
        c.innerHTML = `<h3>${C.icon} ${esc(kind)} — views & clicks</h3><div class="grid g4">${['today', 'yesterday', 'all', 'range'].map(p => `<div class="stat click" data-k="${ev}_view" data-pd="${p}"><small>${p === 'all' ? 'All time' : p}</small><b>${num(sm[p].views)} / ${num(sm[p].clicks)}</b></div>`).join('')}</div><p class="hint">views / clicks (unique per user). Click a box to see the users.</p>`;
        root.append(c); wireDrill(c, kind + ' views'); 
      }
      const card = document.createElement('div'); card.className = 'card';
      card.innerHTML = `<h3>${C.icon} All ${esc(kind)} <span class="sp"></span><button class="o" id="add">+ Add ${esc(C.singular)}</button></h3>` +
        table([...C.cols, ...(C.summary ? [['Views', r => `<a data-uv="${r.id}" data-a="view">${num(r.views)}</a>`], ['Clicks', r => `<a data-uv="${r.id}" data-a="click">${num(r.clicks)}</a>`], ['Redirect', r => esc(r.url || '—')]] : []),
          ['Status', r => r.enabled === false ? '<span class="tag bad">Disabled</span>' : '<span class="tag ok">Enabled</span>'],
          ['', r => `<div class="row" style="flex-wrap:nowrap"><button class="g s" data-t="${r.id}">${r.enabled === false ? 'Enable' : 'Disable'}</button><button class="g s" data-e="${r.id}">Edit</button><button class="r s" data-d="${r.id}">Delete</button></div>`]], items, 'Nothing added yet');
      root.append(card);
      if (kind === 'carousel') await movieStatsCard(root, 'Movies in carousel');
      const by = id => items.find(i => i.id === id);
      $('#add', card).onclick = () => formModal('Add ' + C.singular, C.fields, {}, async o => { await post('/content/' + kind, o); toast('Added', 'ok'); draw(); });
      card.querySelectorAll('[data-e]').forEach(b => b.onclick = () => formModal('Edit ' + C.singular, C.fields, by(b.dataset.e), async o => { await put(`/content/${kind}/${b.dataset.e}`, o); toast('Saved', 'ok'); draw(); }));
      card.querySelectorAll('[data-t]').forEach(b => b.onclick = CHECK(async () => { const it = by(b.dataset.t); await put(`/content/${kind}/${it.id}`, {enabled: it.enabled === false}); draw(); }));
      card.querySelectorAll('[data-d]').forEach(b => b.onclick = CHECK(async () => { if (confirm('Delete permanently?')) { await del(`/content/${kind}/${b.dataset.d}`); draw(); } }));
      card.querySelectorAll('[data-uv]').forEach(a => a.onclick = () => engagedModal(kind, a.dataset.uv, a.dataset.a));
    });
    draw();
  };
}
async function engagedModal(kind, id, action, page = 1) {
  const j = await get(`/content/${kind}/${id}/users?action=${action}&page=${page}`);
  const m = modal(`Users who ${action === 'view' ? 'saw' : 'clicked'} (${j.total})`, table([['Time', r => fmt(r.ts)], ['Device', r => `<a class="mono" data-u="${esc(r.dev)}">${esc(r.dev.slice(0, 14))}…</a>`], ['IP', r => esc(r.ip)], ['Model', r => esc(r.brand + ' ' + r.model)]], j.items) +
    `<div class="pager"><button class="g s" id="pv" ${page <= 1 ? 'disabled' : ''}>‹ Prev</button><span>Page ${page}</span><button class="g s" id="nx" ${page * j.per >= j.total ? 'disabled' : ''}>Next ›</button></div>`);
  m.querySelectorAll('[data-u]').forEach(a => a.onclick = () => userModal(a.dataset.u));
  $('#pv', m).onclick = () => { m.remove(); engagedModal(kind, id, action, page - 1); }; $('#nx', m).onclick = () => { m.remove(); engagedModal(kind, id, action, page + 1); };
}
['notifications', 'dialogs', 'carousel', 'apps'].forEach(k => PAGES[k] = contentPage(k));

/* ---------- videos / movies ---------- */
const fmtDur = t => { if (!t) return ''; const h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), x = t % 60; const p = n => String(n).padStart(2, '0'); return h ? `${h}:${p(m)}:${p(x)}` : `${m}:${p(x)}`; };
const VCATS = [['video', 'Videos'], ['bollywood', 'Bollywood'], ['hollywood', 'Hollywood'], ['series', 'Series'], ['livetv', 'Live TV']];
const VFIELDS = [{k: 'title', label: 'Title'}, {k: 'category', label: 'Category (where it appears in the app)', type: 'select', options: VCATS}, {k: 'description', label: 'Description', type: 'textarea'},
  {k: 'thumbnail_url', label: 'Thumbnail URL'}, {k: 'preview_url', label: 'Preview URL (short mp4 that plays inside the thumbnail, optional)'}, {k: 'duration', label: 'Duration (1:35:00, 12:30 or minutes)'},
  {k: 'tags', label: 'Tags (comma separated)'}, {k: 'video_link', label: 'Video link (m3u8, mp4 or any supported page)'},
  {k: 'sources', label: 'More sources – one per line: Label | URL | Quality | embed (optional)', type: 'textarea'}, {k: 'year', label: 'Year (optional)', type: 'number'}, {k: 'rating', label: 'Rating 0-10 (optional)', type: 'number'},
  {k: 'enabled', label: 'Visible in the app', type: 'checkbox', def: true}];

async function movieStatsCard(root, title) {
  const [a, b] = S.range || [istDate(-6), istDate()];
  const j = await get(`/videos/stats?from=${a}&to=${b}`);
  const c = document.createElement('div'); c.className = 'card';
  const cell = x => `<b>${num(x.watch)}</b> watched · <b>${num(x.download)}</b> downloaded`;
  c.innerHTML = `<h3>🎬 ${esc(title || 'Movies')} – watched & downloaded <span class="mu small">(range ${esc(a)} → ${esc(b)})</span></h3>` +
    table([['Category', r => `<b>${esc(r.label)}</b> <span class="mu">(${r.count} titles)</span>`], ['Today', r => cell(r.today)], ['Yesterday', r => cell(r.yesterday)], ['All time', r => cell(r.all)], ['Custom range', r => cell(r.range)]],
      [...j.categories, {label: 'Total', count: j.categories.reduce((x, y) => x + y.count, 0), today: j.total.today, yesterday: j.total.yesterday, all: j.total.all, range: j.total.range}]);
  root.append(c);
}

PAGES.videos = async root => {
  let tab = 'library', q = '', cat = '', page = 1;
  const draw = guard(async () => {
    root.innerHTML = `<div class="tabs"><button data-t="library" class="${tab === 'library' ? 'on' : ''}">Library</button><button data-t="stats" class="${tab === 'stats' ? 'on' : ''}">Watched & downloaded</button></div>`;
    root.querySelectorAll('[data-t]').forEach(b => b.onclick = () => { tab = b.dataset.t; draw(); });
    if (tab === 'stats') { root.append(rangeBar(draw)); await movieStatsCard(root, 'Movies & videos'); return; }
    const j = await get(`/videos?q=${encodeURIComponent(q)}&category=${cat}&page=${page}&per=12`);
    const c = document.createElement('div'); c.className = 'card';
    c.innerHTML = `<h3>🎬 Video library <span class="tag">${j.total} titles</span><span class="sp"></span><button class="o" id="av">+ Add video</button></h3>
      <p class="hint">Only add links to content you own or are licensed to distribute. Disable or delete a title to take it down instantly (DMCA requests).</p>
      <div class="row" style="margin-bottom:12px"><input id="sq" placeholder="Search title, description or tag" value="${esc(q)}" style="max-width:320px"><select id="sc" style="width:auto"><option value="">All categories</option>${VCATS.map(v => `<option value="${v[0]}" ${v[0] === cat ? 'selected' : ''}>${v[1]}</option>`).join('')}</select><button class="o s" id="sg">Search</button></div>` +
      table([['', r => r.thumbnail_url ? `<img class="thumb" src="${esc(r.thumbnail_url)}" alt="">` : ''], ['Title', r => `<b>${esc(r.title)}</b><div class="mu">${esc((r.description || '').slice(0, 70))}</div><div class="mu small">${esc((r.tags || []).join(', '))}</div>`],
        ['Category', r => `<span class="tag">${esc((VCATS.find(v => v[0] === r.category) || [0, r.category])[1])}</span>`], ['Duration', r => esc(r.duration_text || '—')],
        ['Preview', r => r.preview_url ? '▶ yes' : '—'], ['Watched', r => num(r.watch_count)], ['Downloaded', r => num(r.download_count)], ['Added (server time)', r => esc(r.created_human)],
        ['Status', r => r.enabled === false ? '<span class="tag bad">Hidden</span>' : '<span class="tag ok">Live</span>'],
        ['', r => `<div class="row" style="flex-wrap:nowrap"><button class="g s" data-t2="${r.id}">${r.enabled === false ? 'Show' : 'Hide'}</button><button class="g s" data-e="${r.id}">Edit</button><button class="r s" data-d="${r.id}">Delete</button></div>`]], j.items, 'No videos yet') +
      `<div class="pager"><button class="g s" id="pv" ${j.page <= 1 ? 'disabled' : ''}>‹ Prev</button><span>Page ${j.page} / ${j.pages}</span><button class="g s" id="nx" ${j.page >= j.pages ? 'disabled' : ''}>Next ›</button></div>`;
    root.append(c);
    const find = id => j.items.find(x => x.id === id);
    const toForm = v => ({...v, duration: fmtDur(v.duration_sec || 0), tags: (v.tags || []).join(', '),
      sources: (v.sources || []).map(s => [s.label, s.url, s.quality || '', s.embed ? 'embed' : ''].join(' | ')).join('\n')});
    $('#av', c).onclick = () => formModal('Add video', VFIELDS, {category: 'video', enabled: true}, async o => { await post('/videos', o); toast('Video added', 'ok'); draw(); }, {small: false});
    c.querySelectorAll('[data-e]').forEach(b => b.onclick = () => formModal('Edit video', VFIELDS, toForm(find(b.dataset.e)), async o => { await put('/videos/' + b.dataset.e, o); toast('Saved', 'ok'); draw(); }, {small: false}));
    c.querySelectorAll('[data-t2]').forEach(b => b.onclick = CHECK(async () => { const v = find(b.dataset.t2); await put('/videos/' + v.id, {enabled: v.enabled === false}); draw(); }));
    c.querySelectorAll('[data-d]').forEach(b => b.onclick = CHECK(async () => { if (confirm('Delete this video permanently?')) { await del('/videos/' + b.dataset.d); draw(); } }));
    const go = () => { q = $('#sq', c).value; cat = $('#sc', c).value; page = 1; draw(); };
    $('#sg', c).onclick = go; $('#sq', c).onkeydown = e => { if (e.key === 'Enter') go(); };
    $('#pv', c).onclick = () => { page--; draw(); }; $('#nx', c).onclick = () => { page++; draw(); };
  });
  draw();
};

/* ---------- blocks ---------- */
PAGES.blocks = async root => {
  const draw = guard(async () => {
    const [list, sm] = await Promise.all([get('/blocks'), get(`/dashboard?from=${(S.range || [istDate(-6)])[0]}&to=${(S.range || [0, istDate()])[1]}`)]);
    const P = ['today', 'yesterday', 'all', 'range'];
    root.innerHTML = ''; root.append(rangeBar(draw));
    const c = document.createElement('div');
    c.innerHTML = `<div class="card"><h3>⛔ Blocked-domain hits</h3><div class="grid g4">${P.map(p => stat(p === 'all' ? 'All time' : p, sm[p].blocked_hit, {kind: 'blocked_hit', period: p, o: true})).join('')}</div></div>
    <div class="card"><h3>Add blocked domains</h3><label class="f">Domains (one per line or comma separated)<textarea id="bd" placeholder="example.com&#10;another.org"></textarea></label>
    <label class="f">Message shown to users (text / HTML)<textarea id="bm" placeholder="<b>This website is temporarily blocked</b>"></textarea></label><button class="o" id="ba">Add to block</button></div>
    <div class="card"><h3>Blocked domains (${list.items.length})</h3>${table([['Domain', r => `<b>${esc(r.domain)}</b>`], ['Message', r => `<iframe class="prev" sandbox="" srcdoc="${esc(r.message)}" style="height:70px"></iframe>`], ['Added', r => fmt(r.created)], ['', r => `<button class="r s" data-d="${esc(r.key)}">Remove</button>`]], list.items, 'No domains blocked')}</div>`;
    root.append(c); wireDrill(c, 'Blocked domain hits');
    $('#ba', c).onclick = CHECK(async () => { const r = await post('/blocks', {domains: $('#bd', c).value, message: $('#bm', c).value}); toast('Blocked: ' + r.added.join(', '), 'ok'); draw(); });
    c.querySelectorAll('[data-d]').forEach(b => b.onclick = CHECK(async () => { await del('/blocks/' + b.dataset.d); draw(); }));
  }); draw();
};

/* ---------- premium ---------- */

async function subscriberModal(title, query) {
  let page = 1;
  const m = modal(title, '<div id="sl"></div>');
  const draw = guard(async () => {
    const j = await get(`/premium/users?${query}&page=${page}&per=20`);
    $('#sl', m).innerHTML = table([['Device', r => `<a class="mono" data-u="${esc(r.dev)}">${esc(r.dev.slice(0, 12))}…</a><div class="mu">${esc(r.ip)} ${esc(r.model)}</div>`],
      ['Plan', r => esc(r.plan_name || 'Free')], ['Started', r => fmt(r.started)], ['Expires', r => fmt(r.expires)],
      ['Status', r => `<span class="tag ${r.status === 'active' ? 'ok' : r.status === 'free' ? '' : 'bad'}">${esc(r.status)}</span>`],
      ['', r => `<div class="row" style="flex-wrap:nowrap"><button class="g s" data-ed="${esc(r.dev)}">Edit</button><button class="g s" data-rn="${esc(r.dev)}">Renew</button>${r.status === 'active' ? `<button class="r s" data-rv="${esc(r.dev)}">Revoke</button>` : ''}</div>`]], j.items, 'No users here') +
      `<div class="pager"><button class="g s" id="pv" ${page <= 1 ? 'disabled' : ''}>‹</button><span>${page} / ${Math.max(1, Math.ceil(j.total / j.per))} · ${j.total} users</span><button class="g s" id="nx" ${page * j.per >= j.total ? 'disabled' : ''}>›</button></div>`;
    const box = $('#sl', m);
    box.querySelectorAll('[data-u]').forEach(a => a.onclick = () => userModal(a.dataset.u));
    $('#pv', box).onclick = () => { page--; draw(); }; $('#nx', box).onclick = () => { page++; draw(); };
    const done = () => { draw(); if (S.refreshPremium) S.refreshPremium(); };
    box.querySelectorAll('[data-rv]').forEach(b => b.onclick = CHECK(async () => { if (confirm('Revoke this subscription now?')) { await post(`/premium/${b.dataset.rv}/revoke`, {reason: 'admin'}); toast('Revoked', 'ok'); done(); } }));
    box.querySelectorAll('[data-rn]').forEach(b => b.onclick = () => formModal('Renew subscription', [{k: 'days', label: 'Add days', type: 'number', def: 30}], {}, async o => { await post(`/premium/${b.dataset.rn}/renew`, {days: +o.days}); toast('Renewed', 'ok'); done(); }));
    box.querySelectorAll('[data-ed]').forEach(b => b.onclick = guard(async () => {
      const r = j.items.find(x => x.dev === b.dataset.ed), opts = await planOptions();
      formModal('Edit subscription', [{k: 'plan_id', label: 'Plan', type: 'select', options: opts}, {k: 'started', label: 'Start date & time (IST)', type: 'datetime-local'}, {k: 'expires', label: 'Expiry date & time (IST)', type: 'datetime-local'}],
        {plan_id: r.plan_id, started: r.started ? toIstInput(r.started) : '', expires: r.expires ? toIstInput(r.expires) : ''},
        async o => { const body = {plan_id: o.plan_id}; if (o.started) body.started = fromIstInput(o.started); if (o.expires) body.expires = fromIstInput(o.expires); await post(`/premium/${r.dev}/edit`, body); toast('Subscription updated', 'ok'); done(); });
    }));
  });
  draw();
}

PAGES.premium = async root => {
  const draw = guard(async () => {
    const [a, b] = S.range || [istDate(-6), istDate()];
    const [ov, d] = await Promise.all([get(`/premium/overview?from=${a}&to=${b}`), get(`/dashboard?from=${a}&to=${b}`)]);
    const s = d.premium, er = await get(`/premium/earnings?from=${a}&to=${b}`);
    S.refreshPremium = draw;
    root.innerHTML = ''; root.append(rangeBar(draw));
    const cell = (n, qs, title) => n ? `<a data-q="${esc(qs)}" data-t="${esc(title)}"><b>${num(n)}</b></a>` : '0';
    const rows = ov.order.map(id => ({id, ...ov.plans[id]}));
    const c = document.createElement('div');
    c.innerHTML = `<div class="card"><h3>💰 Earnings</h3><div class="grid g4">
      ${stat('Today', s.today.amount, {fmtv: inr, o: true})}${stat('Yesterday', s.yesterday.amount, {fmtv: inr, o: true})}${stat('All time', s.all.amount, {fmtv: inr, o: true})}${stat('Range', s.range.amount, {fmtv: inr, o: true})}
      ${stat('Purchases today', s.today.count)}${stat('Purchases yesterday', s.yesterday.count)}${stat('Purchases all time', s.all.count)}${stat('Purchases range', s.range.count)}</div></div>
    <div class="card"><h3>👥 Users by plan <button class="o s" id="gr">+ Grant premium</button></h3>
      <div class="grid g3" style="margin-bottom:14px"><div class="stat click" id="fr"><small>Free users</small><b>${num(ov.free_users)}</b></div>${stat('Active premium', ov.active_total, {o: true})}${stat('All users', ov.users_total)}</div>
      <p class="hint">Click any count to open the users (paginated). Range = ${esc(a)} → ${esc(b)} (IST). Purchased includes renewals and admin grants.</p>
      ${table([['Plan', r => `<b>${esc(r.name)}</b>`], ['Active now', r => cell(r.active, `mode=active&plan=${r.id}`, r.name + ' · active')],
        ['Bought today', r => cell(r.purchased.today, `mode=purchased&plan=${r.id}&period=today`, r.name + ' · bought today')], ['Bought yesterday', r => cell(r.purchased.yesterday, `mode=purchased&plan=${r.id}&period=yesterday`, r.name + ' · bought yesterday')], ['Bought (range)', r => cell(r.purchased.range, `mode=purchased&plan=${r.id}&period=range`, r.name + ' · bought in range')],
        ['Expires today', r => cell(r.expiring.today, `mode=expiring&plan=${r.id}&period=today`, r.name + ' · expiring today')], ['Expired / expires yesterday', r => cell(r.expiring.yesterday, `mode=expiring&plan=${r.id}&period=yesterday`, r.name + ' · expiry yesterday')], ['Expiry in range', r => cell(r.expiring.range, `mode=expiring&plan=${r.id}&period=range`, r.name + ' · expiry in range')],
        ['All subscriptions', r => cell(r.expiring.all, `mode=expiring&plan=${r.id}&period=all`, r.name + ' · all')]], rows)}</div>
    <div class="card"><h3>📅 Earnings per day (range)</h3>${table([['Date', r => esc(r.date)], ['Purchases', r => r.count], ['Amount', r => inr(r.amount)]], er.days, 'No earnings in range')}</div>`;
    root.append(c);
    const qs = x => `${x}&from=${a}&to=${b}`;
    c.querySelectorAll('[data-q]').forEach(x => x.onclick = () => subscriberModal(x.dataset.t, qs(x.dataset.q)));
    $('#fr', c).onclick = () => subscriberModal('Free users', 'mode=free');
    $('#gr', c).onclick = guard(async () => { const opts = await planOptions(); formModal('Grant premium', [{k: 'dev', label: 'Device ID'}, {k: 'plan_id', label: 'Plan', type: 'select', options: opts}, {k: 'days', label: 'Days', type: 'number', def: 30}], {},
      async o => { await post(`/premium/${o.dev.trim().toLowerCase()}/grant`, {days: +o.days, plan_id: o.plan_id}); toast('Granted', 'ok'); draw(); }); });
  });
  draw();
};

/* ---------- payments (UPI ids + transactions) ---------- */
PAGES.payments = async root => {
  let tab = 'upi', tp = {status: '', upi: '', q: '', page: 1, all: false};
  const draw = guard(async () => {
    root.innerHTML = `<div class="tabs"><button data-t="upi" class="${tab === 'upi' ? 'on' : ''}">UPI IDs</button><button data-t="txn" class="${tab === 'txn' ? 'on' : ''}">Transactions</button></div><div id="pb"></div>`;
    root.querySelectorAll('[data-t]').forEach(b => b.onclick = () => { tab = b.dataset.t; draw(); });
    const box = $('#pb', root); box.append(rangeBar(draw));
    const [a, b] = S.range || [istDate(-6), istDate()];
    if (tab === 'upi') {
      const [rep, list] = await Promise.all([get(`/upi/report?from=${a}&to=${b}`), get('/upi')]);
      const sum = arr => ({gen: arr.reduce((x, r) => x + r.generated, 0), ok: arr.reduce((x, r) => x + r.success, 0), bad: arr.reduce((x, r) => x + r.failed, 0), pend: arr.reduce((x, r) => x + r.pending, 0), amt: arr.reduce((x, r) => x + r.amount, 0)});
      const blocks = [['Today', rep.today], ['Yesterday', rep.yesterday], ['Custom range', rep.range]];
      const c = document.createElement('div');
      c.innerHTML = `<div class="card"><h3>💳 UPI IDs <span class="tag">${list.items.length} total · ${list.items.filter(u => u.active).length} active</span><span class="sp"></span><button class="o" id="au">+ Add UPI ID</button></h3>
        <div class="grid g3">${blocks.map(([n, arr]) => { const s = sum(arr); return `<div class="stat o"><small>${n} · received</small><b>${inr(s.amt)}</b><small style="margin-top:6px">${s.gen} generated · ${s.ok} ok · ${s.bad} failed · ${s.pend} pending</small></div>`; }).join('')}
        ${(() => { const al = {gen: rep.range.reduce((x, r) => x + r.all_generated, 0), ok: rep.range.reduce((x, r) => x + r.all_success, 0), amt: rep.range.reduce((x, r) => x + r.all_amount, 0)}; return `<div class="stat o"><small>All time · received</small><b>${inr(al.amt)}</b><small style="margin-top:6px">${al.gen} generated · ${al.ok} ok</small></div>`; })()}</div></div>
        <div class="card"><h3>Per UPI ID (range ${esc(a)} → ${esc(b)})</h3>${table([['Name', r => `<b>${esc(r.name)}</b>`], ['UPI ID', r => `<span class="mono">${esc(r.upi_id)}</span>`], ['Chat ID', r => `<span class="mono">${esc(r.chat_id)}</span>`],
          ['Generated', r => r.generated], ['Success', r => r.success], ['Failed', r => r.failed], ['Pending', r => r.pending], ['Received (range)', r => `<b>${inr(r.amount)}</b>`], ['Received (all)', r => inr(r.all_amount)],
          ['Status', r => r.active ? '<span class="tag ok">Active</span>' : '<span class="tag bad">Off</span>'], ['', r => `<div class="row" style="flex-wrap:nowrap"><button class="g s" data-tg="${r.id}" data-on="${r.active}">${r.active ? 'Disable' : 'Enable'}</button><button class="g s" data-ed="${r.id}">Edit</button><button class="r s" data-dl="${r.id}">Delete</button></div>`]], rep.range, 'Add your first UPI ID')}</div>`;
      box.append(c);
      const F = [{k: 'name', label: 'Name'}, {k: 'upi_id', label: 'UPI ID', ph: 'name@bank'}, {k: 'chat_id', label: 'Telegram chat ID', hint: 'The receiver must open the bot and send /start to see their chat ID.'}];
      $('#au', c).onclick = () => formModal('Add UPI ID', F, {}, async o => { await post('/upi', o); toast('UPI ID added', 'ok'); draw(); });
      c.querySelectorAll('[data-ed]').forEach(x => x.onclick = () => { const u = list.items.find(i => i.id === x.dataset.ed); formModal('Edit UPI ID', F, u, async o => { await put('/upi/' + u.id, o); draw(); }); });
      c.querySelectorAll('[data-tg]').forEach(x => x.onclick = CHECK(async () => { await put('/upi/' + x.dataset.tg, {active: x.dataset.on !== 'true'}); draw(); }));
      c.querySelectorAll('[data-dl]').forEach(x => x.onclick = CHECK(async () => { if (confirm('Delete this UPI ID? Past transactions stay.')) { await del('/upi/' + x.dataset.dl); draw(); } }));
    } else {
      const [j, up] = await Promise.all([get(`/txns?from=${a}&to=${b}&status=${tp.status}&upi=${tp.upi}&q=${encodeURIComponent(tp.q)}&page=${tp.page}&all=${tp.all ? 1 : 0}`), get('/upi')]);
      const k = j.counts, c = document.createElement('div');
      c.innerHTML = `<div class="card"><h3>🧾 Transactions</h3><div class="grid g4">${stat('Generated', k.total)}${stat('Success', k.success)}${stat('Failed', k.failed)}${stat('Pending', k.pending)}</div>
        <div class="grid g4" style="margin-top:12px">${stat('Amount received', k.amount, {fmtv: inr, o: true})}</div>
        <div class="row" style="margin:14px 0"><select id="fs" style="width:auto"><option value="">All status</option>${['success', 'failed', 'pending'].map(s => `<option ${s === tp.status ? 'selected' : ''}>${s}</option>`).join('')}</select>
        <select id="fu" style="width:auto"><option value="">All UPI IDs</option>${up.items.map(u => `<option value="${u.id}" ${u.id === tp.upi ? 'selected' : ''}>${esc(u.name)} · ${esc(u.upi_id)}</option>`).join('')}</select>
        <input id="fq" placeholder="Txn ID / device / UTR / IP" value="${esc(tp.q)}" style="max-width:240px"><label class="chk" style="display:flex;gap:6px"><input type="checkbox" id="fa" ${tp.all ? 'checked' : ''}> All time</label><button class="o s" id="fg">Filter</button></div>
        ${table([['Txn ID', r => `<span class="mono">${esc(r.txn_id)}</span><div class="mu">${fmt(r.created)}</div>`], ['Device / IP', r => `<a class="mono" data-u="${esc(r.dev)}">${esc(r.dev.slice(0, 10))}…</a><div class="mu">${esc(r.ip)}</div>`], ['Plan', r => esc(r.plan_name)], ['Amount', r => inr(r.amount)],
          ['UPI', r => `${esc(r.upi_name)}<div class="mono mu">${esc(r.upi_id)}</div>`], ['UTR', r => `<span class="mono">${esc(r.utr || '—')}</span>${r.proof ? ' 📎' : ''}`],
          ['Status', r => statusTag(r.status) + (r.fail_reason ? `<div class="mu">${esc(r.fail_reason)}</div>` : '')],
          ['', r => `<div class="row" style="flex-wrap:nowrap">${r.status !== 'success' ? `<button class="s" data-v="${esc(r.txn_id)}">Verify</button>` : ''}${r.status !== 'failed' ? `<button class="r s" data-f="${esc(r.txn_id)}">Fail</button>` : ''}${r.proof_file ? `<button class="g s" data-p="${esc(r.txn_id)}">Proof</button>` : ''}</div>`]], j.items, 'No transactions match')}
        <div class="pager"><button class="g s" id="pv" ${tp.page <= 1 ? 'disabled' : ''}>‹</button><span>${tp.page} / ${Math.max(1, Math.ceil(j.total / j.per))}</span><button class="g s" id="nx" ${tp.page * j.per >= j.total ? 'disabled' : ''}>›</button></div></div>`;
      box.append(c);
      $('#fg', c).onclick = () => { tp = {status: $('#fs', c).value, upi: $('#fu', c).value, q: $('#fq', c).value, page: 1, all: $('#fa', c).checked}; draw(); };
      $('#pv', c).onclick = () => { tp.page--; draw(); }; $('#nx', c).onclick = () => { tp.page++; draw(); };
      c.querySelectorAll('[data-u]').forEach(x => x.onclick = () => userModal(x.dataset.u));
      c.querySelectorAll('[data-v]').forEach(x => x.onclick = CHECK(async () => { if (confirm('Mark as paid and credit premium?')) { const r = await post(`/txns/${x.dataset.v}/verify`); toast('Verified', 'ok'); draw(); } }));
      c.querySelectorAll('[data-f]').forEach(x => x.onclick = () => formModal('Fail transaction', [{k: 'reason', label: 'Reason', def: 'Fake payment proof'}], {}, async o => { await post(`/txns/${x.dataset.f}/fail`, {reason: o.reason}); toast('Marked failed', 'ok'); draw(); }));
      c.querySelectorAll('[data-p]').forEach(x => x.onclick = () => modal('Payment proof ' + x.dataset.p, `<img style="max-width:100%;border-radius:12px" src="${BASE}/txns/${x.dataset.p}/proof" alt="proof">`));
    }
  });
  draw();
};

/* ---------- settings ---------- */
const SECTION_TITLES = {app: 'App & updates', support: 'Customer support', developer: 'Developer details', share: 'Share', legal: 'Terms, Privacy & DMCA', landing: 'Landing page', ads: 'Ads (Start.io)', limits: 'Limits',
  premium: 'Premium plans', payment: 'Payments', security: 'Security', theme: 'Panel theme', maintenance: 'Maintenance mode'};
const LONG = new Set(['message', 'terms_html', 'privacy_html', 'update_message', 'unreachable_message', 'bio', 'text', 'supported_platforms_text']);
PAGES.settings = async root => {
  const j = await get('/settings'); let sec = 'app';
  const draw = () => {
    const cfg = j.config[sec];
    root.innerHTML = `<div class="tabs">${j.sections.map(s => `<button data-s="${s}" class="${s === sec ? 'on' : ''}">${esc(SECTION_TITLES[s] || s)}</button>`).join('')}</div><div class="card"><h3>${esc(SECTION_TITLES[sec] || sec)}</h3><div id="sf"></div><button class="o" id="sv">Save changes</button></div>`;
    const f = $('#sf', root);
    if (sec === 'maintenance') f.innerHTML = `<p class="hint">When ON every app launch shows your message and downloads are blocked. App opens during maintenance are counted on the dashboard.</p>`;
    if (sec === 'premium') {
      f.innerHTML += `<p class="hint">downloads per day / watch per day: <b>0 = unlimited</b>. Every plan is ad-free. Limit the cheapest plan so the unlimited plan looks like the best choice. Badge text (e.g. RECOMMENDED) is shown on the plan card in the app.</p><div id="plans"></div><button class="g s" id="ap">+ Add plan</button><label class="f" style="margin-top:12px">Premium features (one per line)<textarea data-arr="features">${esc((cfg.features || []).join('\n'))}</textarea></label>`;
      const pl = () => { $('#plans', f).innerHTML = cfg.plans.map((p, i) => `<div class="row" style="margin-bottom:8px">${['id', 'name', 'days', 'price', 'badge', 'downloads_per_day', 'watch_per_day'].map(k => `<label class="f" style="margin:0"><span style="font-size:10px">${k.replace(/_/g, ' ')}</span><input data-pi="${i}" data-pk="${k}" value="${esc(p[k] ?? 0)}" placeholder="${k}" style="width:${k === 'name' ? 130 : k.includes('_per_') ? 110 : 85}px" ${k === 'days' || k === 'price' || k.includes('_per_') ? 'type="number"' : ''}></label>`).join('')}<button class="r s" data-rm="${i}">✕</button></div>`).join('');
        f.querySelectorAll('[data-pi]').forEach(e => e.oninput = () => cfg.plans[+e.dataset.pi][e.dataset.pk] = e.type === 'number' ? +e.value : e.value);
        f.querySelectorAll('[data-rm]').forEach(b => b.onclick = () => { cfg.plans.splice(+b.dataset.rm, 1); pl(); }); };
      pl(); $('#ap', f).onclick = () => { cfg.plans.push({id: 'p' + (cfg.plans.length + 1), name: '', days: 30, price: 25, badge: '', downloads_per_day: 0, watch_per_day: 0}); pl(); };
    } else Object.entries(cfg).forEach(([k, v]) => {
      const lab = k.replace(/_/g, ' ');
      if (typeof v === 'boolean') f.insertAdjacentHTML('beforeend', `<label class="f chk"><input type="checkbox" data-k="${k}" ${v ? 'checked' : ''}> ${esc(lab)}</label>`);
      else if (Array.isArray(v)) f.insertAdjacentHTML('beforeend', `<label class="f">${esc(lab)} (one per line)<textarea data-arr="${k}">${esc(v.join('\n'))}</textarea></label>`);
      else if (typeof v === 'number') f.insertAdjacentHTML('beforeend', `<label class="f">${esc(lab)}<input type="number" data-k="${k}" data-n="1" value="${v}"></label>`);
      else if (LONG.has(k) || String(v).length > 90) f.insertAdjacentHTML('beforeend', `<label class="f">${esc(lab)}<textarea data-k="${k}" style="min-height:${k.endsWith('_html') ? 220 : 90}px">${esc(v)}</textarea></label>`);
      else f.insertAdjacentHTML('beforeend', `<label class="f">${esc(lab)}<input data-k="${k}" value="${esc(v)}"></label>`);
    });
    if (sec === 'ads') f.insertAdjacentHTML('afterbegin', '<p class="hint">Only Start.io is supported. Master switch turns every ad off. Premium users never see ads.</p>');
    if (sec === 'limits') f.insertAdjacentHTML('afterbegin', '<p class="hint">Free users: <b>free daily downloads</b> and <b>free daily watch</b> are enforced by the server. When both are used up the app opens the premium purchase screen. Set a number to increase or decrease.</p>');
    if (sec === 'payment') f.insertAdjacentHTML('afterbegin', '<p class="hint">rotation: <b>success</b> = next transaction goes to the UPI that has received the fewest payments; <b>round_robin</b> = strictly rotates every transaction.</p>');
    root.querySelectorAll('[data-s]').forEach(b => b.onclick = () => { sec = b.dataset.s; draw(); });
    $('#sv', root).onclick = guard(async () => {
      const out = JSON.parse(JSON.stringify(cfg));
      f.querySelectorAll('[data-k]').forEach(e => out[e.dataset.k] = e.type === 'checkbox' ? e.checked : e.dataset.n ? +e.value : e.value);
      f.querySelectorAll('[data-arr]').forEach(e => out[e.dataset.arr] = e.value.split('\n').map(x => x.trim()).filter(Boolean));
      const r = await put('/settings/' + sec, out); j.config[sec] = r.section; toast('Saved. Config reloaded in memory.', 'ok'); draw();
    });
  };
  draw();
};

/* ---------- logs ---------- */
PAGES.logs = async root => {
  let kind = 'admin', page = 1;
  const draw = guard(async () => {
    const [a, b] = S.range || [istDate(-6), istDate()];
    const j = await get(`/logs?kind=${kind}&from=${a}&to=${b}&page=${page}&per=50`);
    root.innerHTML = `<div class="tabs"><button data-k="admin" class="${kind === 'admin' ? 'on' : ''}">Admin actions</button><button data-k="login" class="${kind === 'login' ? 'on' : ''}">Login attempts</button></div>`;
    root.append(rangeBar(() => { page = 1; draw(); }));
    const c = document.createElement('div'); c.className = 'card';
    c.innerHTML = (kind === 'admin' ? table([['Time', r => fmt(r.ts)], ['User', r => esc(r.user)], ['IP', r => esc(r.ip)], ['Action', r => `<b>${esc(r.action)}</b>`], ['Detail', r => esc(r.detail)]], j.items, 'No logs')
      : table([['Time', r => fmt(r.ts)], ['Result', r => r.ok ? '<span class="tag ok">success</span>' : '<span class="tag bad">failed</span>'], ['User tried', r => esc(r.user)], ['IP', r => esc(r.ip)], ['Fingerprint', r => `<span class="mono">${esc((r.fp || '').slice(0, 16))}</span>`], ['Browser', r => esc((r.ua || '').slice(0, 60))]], j.items, 'No attempts')) +
      `<div class="pager"><button class="g s" id="pv" ${page <= 1 ? 'disabled' : ''}>‹</button><span>${page} / ${Math.max(1, Math.ceil(j.total / j.per))}</span><button class="g s" id="nx" ${page * j.per >= j.total ? 'disabled' : ''}>›</button></div>`;
    root.append(c);
    root.querySelectorAll('[data-k]').forEach(b => b.onclick = () => { kind = b.dataset.k; page = 1; draw(); });
    $('#pv', c).onclick = () => { page--; draw(); }; $('#nx', c).onclick = () => { page++; draw(); };
  }); draw();
};

boot();
