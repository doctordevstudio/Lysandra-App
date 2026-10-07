# Lysandra Admin Panel

FastAPI + vanilla HTML/CSS/JS admin panel for the Lysandra video downloader.
Deploys as its own Render service, reading/writing the same Firebase project
as the main backend.

## Setup

```bash
cp .env.example .env            # fill in every value, including ADMIN_USERNAME / ADMIN_PASSWORD
pip install -r requirements.txt
openssl rand -hex 32            # -> SESSION_SECRET
uvicorn app.main:app --reload --port 8001
```

Open `http://localhost:8001` -> redirects to `/login`.

`MAIN_BACKEND_RELOAD_URL` / `MAIN_BACKEND_ADMIN_TOKEN` must point at the main
backend's `/internal/reload-config` and match its `ADMIN_RELOAD_TOKEN` --
this is what makes a Settings save go live immediately instead of waiting
for the main backend's periodic refresh.

## What's implemented

**Auth**: credentials are the raw `ADMIN_USERNAME` / `ADMIN_PASSWORD` env
vars, compared with a constant-time check (no hashing, no stored account,
no setup script -- set the two env vars and log in). One active
session per username (a new login invalidates the previous one), 15-minute
*sliding* expiry (every authenticated action resets the clock, per spec),
httpOnly+SameSite=Strict cookies, and a custom-header check as lightweight
CSRF mitigation. 3 failed logins -> that device's fingerprint is locked for
24 hours (independent of IP, independent of which account was targeted).

**Dashboard**: Today / Yesterday / All-time / Custom-range toggle drives one
summary call returning new users, total users, yesterday-active-today,
fetch success/failed, blocked-domain hits, maintenance hits, and the full
ads breakdown (ad type × platform × triggering action). Every number is
clickable and opens a paginated "who did this" list (date-scoped -- see
"Drilldown pagination" below for why). Top-50-by-fetch-count table with
each user's interstitial/rewarded watch counts, powered by Firebase's
native `order_by_value` + `limit_to_last` (no full-table scan).

**Notifications / Dialog / Carousel**: full CRUD, enable/disable, per-item
view/click totals with dedup (a device's repeat view/click never
double-counts), a "viewed by / clicked by" paginated list per item, and a
date-range click/view summary across all items. Dialog and Carousel also
support `sort_order` with auto-shift (inserting at position N pushes
everything at N and above up by one, per spec).

**Block**: paste one or many domains (newline or comma separated) with a
single message shown to users who hit any of them; per-date paginated list
of who got blocked; total-hits card for the selected range.

**Settings**: every editable value from the spec in one page -- Start.io
and Monetag credentials + enable switches, carousel/dialog master toggles,
theme default (day, per spec) + whether users may switch it, Terms/Privacy
HTML, support/developer contact + bio, latest version + update-channel URL,
and the YouTube proxy list. Saving pushes to Firebase and immediately pokes
the main backend to reload its config cache. Maintenance mode is also edited
here; its usage stats live on the Dashboard (so admins see maintenance hits
alongside everything else) rather than a separate page.

All admin actions (logins, saves, deletes...) are logged to
`/admin_logs/<date>` for your own audit trail.

## Drilldown pagination: a deliberate simplification

Every "click a number, see the users" list is scoped to **one specific
date** (shown with its own date-picker inside the modal, defaulting to the
most relevant day for whatever range you had selected). Dashboard *totals*
correctly sum across Today / Yesterday / All-time / any custom range --
only the detailed list-of-users view is per-day. This is because the main
backend logs events nested as `/logs/<category>/<date>/<push_id>`, which
makes per-day pagination O(1)-ish but makes flattening-and-paginating
*across* an arbitrary multi-week range expensive on Firebase RTDB's query
model. If you later want true cross-date scrolling in one list, the clean
fix is to also write a flat `/logs/<category>/<push_id>` copy (same event,
indexed with `.indexOn: "ts"`) and query that with
`order_by_child('ts').start_at(...).end_at(...)` instead -- noted here so
future-you doesn't have to rediscover this tradeoff.

## Firebase rules

Set up `.indexOn` for anything queried by child key, at minimum:
```json
{
  "rules": {
    "stats": { "user_fetch_count": { ".indexOn": ".value" } }
  }
}
```
(`order_by_key()` calls used everywhere else don't need an explicit index.)

## Deploy to Render (free tier)

Same pattern as the main backend: push to GitHub, connect via `render.yaml`,
fill in the `sync: false` env vars in the dashboard -- including
`ADMIN_USERNAME` and `ADMIN_PASSWORD`, which *are* your login, directly.
Nothing else to run or create.

## Theming

Day mode is the default on first load (per spec); the moon/sun button in the
topbar flips to night and remembers the choice per-browser via
`localStorage`. The palette intentionally echoes the app icon: orange-to-blue
flame gradient as the accent, deep navy for the dark theme.
