# Lysandra Server

One FastAPI service, one process, one Firebase client: the app-facing API
(`/api/v1/*`, talked to by the Android app) and the admin panel (`/api/admin/*`
+ its HTML pages) used to be two separate Render services in two separate
folders -- they're merged here into a single deployable project at the repo
root, per request. Nothing about either side's behavior changed in the
merge except where noted in "What changed in the merge" at the bottom.

## Architecture

```
Android App  --(AES-GCM encrypted URL + HMAC-signed request)-->  /api/v1/*  --\
                                                                               |
Admin browser --(session cookie, same origin)-----------------> /api/admin/* -+--> one FastAPI app
                                                                               |     one Firebase client
                                                                               |     one in-memory config cache
                                                                  Firebase RTDB (shared)
```

Config (ad unit IDs, blocked domains, feature flags, maintenance mode...) lives in
Firebase under `/config` and is loaded into an **in-memory cache at startup**,
refreshed every `CONFIG_REFRESH_SECONDS` (default 60s), and refreshed
**immediately, in-process** whenever the admin panel saves Settings -- no
network round-trip, since it's all one process now.

## Setup

```bash
cp .env.example .env     # fill in every value
pip install -r requirements.txt
openssl rand -base64 32  # -> AES_KEY_B64
openssl rand -hex 32     # -> HMAC_SECRET
openssl rand -hex 32     # -> SESSION_SECRET
uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000` -> redirects to `/login` for the admin panel.
The Android app talks to the same base URL's `/api/v1/*` routes.

### Firebase

1. Firebase Console -> Project Settings -> Service Accounts -> Generate new private key.
2. Paste the JSON into `FIREBASE_SERVICE_ACCOUNT_JSON` (one line) or save it as a
   file and point `FIREBASE_SERVICE_ACCOUNT_FILE` at it.
3. Set `FIREBASE_DB_URL` to your RTDB URL.
4. The Android app and the admin panel's browser-side JS **never** see the DB
   URL or credentials -- they only ever talk to this one service's own
   `/api/v1/*` / `/api/admin/*` routes. Even with RTDB rules set to
   `read: true, write: true`, nothing public can reach the DB directly --
   worth locking rules down to `"auth != null"` anyway, since the Admin SDK
   bypasses rules entirely and this service is now your only writer/reader.

### Deploy to Render (free tier) -- now just ONE service

1. Push this repo to GitHub (everything at the repo root -- no subfolders to point at).
2. New -> Web Service -> connect the repo. Render will read `render.yaml`
   automatically (or set build/start commands manually as shown in it).
3. Add every `sync: false` env var in the Render dashboard, including
   `ADMIN_USERNAME` / `ADMIN_PASSWORD` (these *are* your admin login --
   nothing else to run or create).
4. Put the Render URL behind Cloudflare -- don't point the app at
   `*.onrender.com` directly in production.

## Request format (what the Android app must send)

`POST /api/v1/fetch`

Headers:
```
Content-Type: application/json
X-Timestamp: <unix seconds, int>
X-Nonce: <random UUID, unique per request>
X-Signature: hex(HMAC_SHA256(HMAC_SECRET, body + "." + X-Timestamp + "." + X-Nonce))
X-Package-Name: com.drdev.hamza
X-Cert-SHA256: <sha256 of the app's own signing cert, lowercase hex>
```

Body:
```json
{
  "payload": "<base64(AES-256-GCM(nonce=12B) encrypted raw URL)>",
  "device_id": "<stable per-install UUID>"
}
```

AES key and HMAC secret are the same `AES_KEY_B64` / `HMAC_SECRET` from `.env`,
embedded obfuscated in the app (see the Android project's
`security/ObfuscatedStrings.kt` and its Colab build script, which patches
these in from the same values). Python reference for generating a matching
payload during testing:

```python
from app.security import encrypt_payload, sign
import time, uuid, json

body = json.dumps({"payload": encrypt_payload("https://example.com/video"), "device_id": "test-device"})
ts = str(int(time.time())); nonce = str(uuid.uuid4())
signature = sign(body + "." + ts + "." + nonce)
```

Response: `VideoInfo` JSON (`title`, `thumbnail`, `duration_seconds`, `uploader`,
`formats: [{quality, ext, filesize_bytes, url, type}]`).

## All app-facing endpoints (`/api/v1/*`)

All signed the same way as `/api/v1/fetch` (X-Timestamp/X-Nonce/X-Signature + app-identity headers):

- `POST /api/v1/fetch` -- the core video-info lookup
- `GET /api/v1/config` -- app-launch config (ad IDs, feature flags, maintenance mode...); takes an `X-Device-Id` header, used only to log a maintenance-mode hit when `maintenance_mode` is on
- `GET /api/v1/notifications?cursor=` -- paginated (20/page), newest first
- `POST /api/v1/notifications/seen` / `/clicked` -- `{device_id, notification_id}`
- `GET /api/v1/carousel` / `GET /api/v1/dialogs` -- enabled items, sorted by `sort_order`
- `POST /api/v1/carousel/seen` / `/clicked`, `/api/v1/dialogs/seen` / `/clicked` -- `{device_id, item_id}`
- `GET /api/v1/platforms` -- the Apps-tab platform grid
- `POST /api/v1/ads/event` -- `{device_id, ad_type, platform, action, page}`, logs every ad
  impression/watch for the admin dashboard breakdown (Start.io vs Monetag, by fetch/watch/download)

View/click tracking on notifications/dialogs/carousel is dedup'd per-device automatically
(`app/utils/engagement.py`) -- repeat views/clicks from the same device don't double-count.

## Adding a new custom domain extractor

1. Create `app/extractors/mysite.py`:
   ```python
   from app.extractors.base import BaseExtractor, VideoInfo, FormatInfo

   class MySiteExtractor(BaseExtractor):
       name = "mysite"
       def can_handle(self, domain: str) -> bool:
           return domain in {"mysite.com"}
       async def extract(self, url: str) -> VideoInfo:
           # call MySite's API / scrape the page, build formats, return VideoInfo
           ...
   ```
2. Register it in `app/extractors/__init__.py`, **above** `GenericYtDlpExtractor()`:
   ```python
   REGISTRY = [YoutubeExtractor(), TeraboxExtractor(), MySiteExtractor(), GenericYtDlpExtractor()]
   ```
3. That's it -- `/api/v1/fetch` will route that domain to it automatically.

## Admin panel (`/api/admin/*` + HTML pages)

**Auth**: credentials are the raw `ADMIN_USERNAME` / `ADMIN_PASSWORD` env
vars, compared with a constant-time check (no hashing, no stored account).
One active session per username (a new login invalidates the previous one),
15-minute *sliding* expiry, httpOnly+SameSite=Strict cookies, and a
custom-header check as lightweight CSRF mitigation. 3 failed logins -> that
device's fingerprint is locked for 24 hours.

**Dashboard**: Today / Yesterday / All-time / Custom-range toggle drives one
summary call returning new users, total users, yesterday-active-today,
fetch success/failed, blocked-domain hits, maintenance hits, and the full
ads breakdown. Every number is clickable into a paginated "who did this"
list (date-scoped -- see "Drilldown pagination" below). Top-50-by-fetch-count
table with each user's ad-watch counts.

**Notifications / Dialog / Carousel**: full CRUD, enable/disable, per-item
view/click totals with dedup, a "viewed by / clicked by" paginated list per
item, date-range click/view summaries. Dialog and Carousel support
`sort_order` with auto-shift on insert.

**Block**: paste one or many domains with a message shown to anyone who
hits them; per-date paginated list of who got blocked.

**Settings**: Start.io/Monetag credentials + toggles, theme (day default),
Terms/Privacy HTML, support/developer contact + bio, version/update link,
YouTube proxy list, maintenance mode. Saving pushes to Firebase and calls
`config_cache.refresh()` directly (in-process) so changes go live immediately.

All admin actions are logged to `/admin_logs/<date>` for your own audit trail.

### Drilldown pagination: a deliberate simplification

Every "click a number, see the users" list is scoped to **one specific
date** (its own date-picker inside the modal). Dashboard *totals* correctly
sum across Today / Yesterday / All-time / any custom range -- only the
detailed list-of-users view is per-day, because the backend logs events
nested as `/logs/<category>/<date>/<push_id>`, which makes per-day
pagination cheap but makes flattening-and-paginating across an arbitrary
multi-week range expensive on Firebase RTDB's query model. The clean fix,
if you want true cross-date scrolling later, is also writing a flat
`/logs/<category>/<push_id>` copy indexed with `.indexOn: "ts"` and querying
that with `order_by_child('ts').start_at(...).end_at(...)` instead.

### Firebase rules

```json
{
  "rules": {
    "stats": { "user_fetch_count": { ".indexOn": ".value" } }
  }
}
```
(`order_by_key()` calls used everywhere else don't need an explicit index.)

### Theming

Day mode is the default on first load; the moon/sun button in the topbar
flips to night and remembers the choice per-browser via `localStorage`. The
palette echoes the app icon: orange-to-blue flame gradient as the accent,
deep navy for the dark theme. Fully responsive -- a hamburger menu opens the
sidebar on phones, tables scroll horizontally instead of breaking layout.

## Security: what's implemented, and honest limits

- **Anti-replay**: timestamp window + one-time nonce cache.
- **Request signing**: HMAC over the body, rejects anyone without the shared secret.
- **App identity check**: package name + signing-certificate hash headers.
- **SSRF guard** (`app/utils/url_safety.py`): blocks private/loopback/link-local
  IPs and non-http(s) schemes before any extractor touches a user-supplied URL
  (the #1 real vulnerability class for a "paste any URL" API, OWASP A10).
- **Rate limiting**: 60 req/min/IP via slowapi.
- **No stack traces leaked**: generic 500s in production.
- **Docs/OpenAPI disabled** in prod.

**What this does *not* do**: guarantee the app-facing API can never be called
outside the app. A sufficiently motivated reverse engineer can extract the
HMAC secret and AES key from a running APK and replicate a valid signature --
true of any app shipping its own symmetric secret. The real fix, Google Play
Integrity API, is deliberately **not used here** (by request, mainly its
free-tier request-volume cap); the hook for it still exists in
`security.py::verify_play_integrity` if that changes later.

## OWASP Top 10 coverage notes

- A01 Broken access control: admin routes require a valid session; app routes require a valid signature.
- A02 Crypto failures: AES-256-GCM + HMAC-SHA256, keys from env only.
- A03 Injection: no raw SQL/shell; all Firebase access via the Admin SDK's typed path references.
- A05 Security misconfig: docs disabled, generic error responses, no unnecessary CORS.
- A07 Auth failures: admin login lockout (3 fails -> 24h fingerprint lock), single-session-with-15-min-sliding-expiry.
- A09 Logging: every fetch/block/admin-action event logged to RTDB.
- A10 SSRF: `url_safety.py`.

## Scaling note

The nonce replay cache and config cache are in-process memory, fine for
Render's free single-instance plan. Moving to multiple instances/autoscaling
would need the `TTLCache` swapped for Redis (e.g. Upstash's free tier) so
replay protection and config stay consistent across instances.

## What changed in the merge (from the two-folder version)

- `lysandra-backend/app/` + `lysandra-admin/app/` -> one `app/` package.
  Admin-only route files got an `admin_` prefix to avoid name collisions
  with the app-facing ones (e.g. both had a `notifications.py` -- the admin
  one is now `admin_notifications.py`); admin's `security.py` (sessions/
  lockout) is now `admin_security.py` so it doesn't collide with the
  app-facing crypto `security.py`.
- The admin panel's Settings-save used to POST to the backend's
  `/internal/reload-config` over HTTP, authenticated with a shared
  `ADMIN_RELOAD_TOKEN`. That whole mechanism is gone -- it's a direct
  in-process function call now (`config_cache.refresh()`), which is both
  simpler and strictly more reliable (no network hop that could fail).
  `MAIN_BACKEND_RELOAD_URL`, `MAIN_BACKEND_ADMIN_TOKEN`, and
  `ADMIN_RELOAD_TOKEN` are gone from `.env` accordingly.
- `httpx` and `bcrypt` are no longer dependencies (both were only used by
  things removed above/earlier).
- **Found and fixed while merging**: the admin-only version registered its
  `/healthz` route *after* the `/{page}` catch-all route that serves admin
  HTML pages. Starlette matches routes in registration order, so `/healthz`
  requests were actually being swallowed by the catch-all and returning 404
  instead of `{"status": "ok"}` -- a real bug in the two-service version,
  fixed here by registering `/healthz` first.
- One `render.yaml`, one `requirements.txt`, one `.env.example`, deployed as
  one Render web service instead of two.
