# Lysandra Backend

Multi-user video-info-fetch API: YouTube (via yt-dlp + proxy rotation), Terabox
(dummy stub -- see below), and a yt-dlp fallback covering 1000+ other sites.
Built for Render's free tier, with Firebase Realtime Database for config/logs.

## Architecture

```
Android App  --(AES-GCM encrypted URL + HMAC-signed request)-->  FastAPI backend
                                                                       |
                                                        verify signature + replay + app identity
                                                                       |
                                                              decrypt URL, validate (SSRF guard)
                                                                       |
                                                       check /config/blocked_domains (in-memory)
                                                                       |
                        -----------------------------------------------------------------
                        |                         |                                     |
                 YoutubeExtractor           TeraboxExtractor                   GenericYtDlpExtractor
                 (yt-dlp + proxies)         (dummy -- plug in later)           (yt-dlp, 1000+ sites)
                        -----------------------------------------------------------------
                                                                       |
                                                          log event -> Firebase RTDB
                                                                       |
                                                              return VideoInfo JSON
```

Config (ad unit IDs, blocked domains, feature flags, maintenance mode...) lives in
Firebase under `/config` and is loaded into an **in-memory cache at startup**,
refreshed every `CONFIG_REFRESH_SECONDS` (default 60s), and also refreshable
instantly by the admin panel calling `POST /internal/reload-config` with the
`X-Admin-Token` header right after a settings save. No request handler ever
blocks on a database read.

## Setup

```bash
cp .env.example .env     # fill in every value
pip install -r requirements.txt
openssl rand -base64 32  # -> AES_KEY_B64
openssl rand -hex 32     # -> HMAC_SECRET
uvicorn app.main:app --reload --port 8000
```

### Firebase

1. Firebase Console -> Project Settings -> Service Accounts -> Generate new private key.
2. Paste the JSON into `FIREBASE_SERVICE_ACCOUNT_JSON` (one line) or save it as a
   file and point `FIREBASE_SERVICE_ACCOUNT_FILE` at it.
3. Set `FIREBASE_DB_URL` to your RTDB URL.
4. Your app and admin panel **never** see the DB URL or credentials -- they only
   ever talk to this backend's own `/api/v1/*` routes. Even with RTDB rules set
   to `read: true, write: true` (as you described), nothing public can reach the
   DB directly unless something else links to it -- worth locking rules down to
   `"auth != null"` anyway, since the Admin SDK bypasses rules entirely and this
   backend is now your only writer/reader.

### Deploy to Render (free tier)

1. Push this repo to GitHub.
2. New -> Web Service -> connect the repo. Render will read `render.yaml`
   automatically (or set build/start commands manually as shown in it).
3. Add every `sync: false` env var in the Render dashboard (never commit real
   secrets).
4. Put the Render URL behind Cloudflare (see security.md section below) --
   don't point the app at `*.onrender.com` directly in production.

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
embedded obfuscated in the app (never as a plain string constant -- see the
Android-side security notes once that phase is built). Python reference for
generating a matching payload during testing:

```python
from app.security import encrypt_payload, sign
import time, uuid, json

body = json.dumps({"payload": encrypt_payload("https://example.com/video"), "device_id": "test-device"})
ts = str(int(time.time())); nonce = str(uuid.uuid4())
signature = sign(body + "." + ts + "." + nonce)
```

Response: `VideoInfo` JSON (`title`, `thumbnail`, `duration_seconds`, `uploader`,
`formats: [{quality, ext, filesize_bytes, url, type}]`).

## Additional app-facing endpoints (added to support the admin panel)

All signed the same way as `/api/v1/fetch` (X-Timestamp/X-Nonce/X-Signature + app-identity headers):

- `GET /api/v1/notifications?cursor=` -- paginated (20/page), newest first
- `POST /api/v1/notifications/seen` / `/clicked` -- `{device_id, notification_id}`
- `GET /api/v1/carousel` / `GET /api/v1/dialogs` -- enabled items, sorted by `sort_order`
- `POST /api/v1/carousel/seen` / `/clicked`, `/api/v1/dialogs/seen` / `/clicked` -- `{device_id, item_id}`
- `POST /api/v1/ads/event` -- `{device_id, ad_type, platform, action, page}`, logs every ad
  impression/watch for the admin dashboard breakdown (Start.io vs Monetag, by fetch/watch/download)
- `GET /api/v1/config` now also takes an `X-Device-Id` header, used only to log a maintenance-mode
  hit when `maintenance_mode` is on (for the admin panel's "users who hit maintenance" stat)

View/click tracking on notifications/dialogs/carousel is dedup'd per-device automatically
(`app/utils/engagement.py`) -- repeat views/clicks from the same device don't double-count,
matching the admin panel spec.

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
   No other file needs to change.

## Security: what's implemented, and honest limits

- **Anti-replay**: timestamp window + one-time nonce cache. A captured request
  can't be resent.
- **Request signing**: HMAC over the body, rejects anyone without the shared secret.
- **App identity check**: package name + signing-certificate hash headers,
  checked against known-good values -- a resigned/modified APK fails this.
- **SSRF guard** (`app/utils/url_safety.py`): blocks private/loopback/link-local
  IPs and non-http(s) schemes before any extractor touches a user-supplied URL.
  This is the #1 real vulnerability class for a "paste any URL" API (OWASP A10).
- **Rate limiting**: 60 req/min/IP via slowapi (tune in `main.py`).
- **No stack traces leaked**: generic 500s in production.
- **Docs/OpenAPI disabled** in prod so the API surface isn't self-documenting
  to anyone poking at it.

**What this does *not* do**: guarantee the API can never be called outside the
app. A sufficiently motivated reverse engineer can extract the HMAC secret and
AES key from a running APK (it has to be present in the app to work) and
replicate a valid signature. This is true of literally any app shipping its
own symmetric secret -- there is no purely client-side cryptographic scheme
that fully prevents it. The real fix, when you're ready, is **Google Play
Integrity API**: the server asks Google to attest that the request really
came from your unmodified, Play-distributed APK, cryptographically, outside
your control. The hook for it is already in `security.py::verify_play_integrity`
-- wire it up once the app has a Play Store listing (it also works for
internal/side-loaded distribution via the "standard" Integrity API tier).

## OWASP Top 10 coverage notes

- A01 Broken access control: admin-only routes require `X-Admin-Token`; public
  routes require a valid signature.
- A02 Crypto failures: AES-256-GCM (authenticated encryption) + HMAC-SHA256,
  keys from env only.
- A03 Injection: no raw SQL/shell; all Firebase access via the Admin SDK's
  typed path references.
- A05 Security misconfig: docs disabled, generic error responses, CORS locked
  to the admin panel's own origin.
- A07 Auth failures: see admin-panel phase for login lockout (3 failed attempts
  -> 24h fingerprint lock) and single-session-with-15-min-expiry.
- A09 Logging: every fetch/block event + device IP history is logged to RTDB.
- A10 SSRF: `url_safety.py`, described above.

## Scaling note

The nonce replay cache and config cache are in-process memory, which is fine
for Render's free single-instance plan. If you ever move to multiple
instances/autoscaling, swap `TTLCache` for Redis (e.g. Upstash's free tier)
so replay protection and config stay consistent across instances.
