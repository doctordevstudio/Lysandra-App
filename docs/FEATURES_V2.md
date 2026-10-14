# What is new in this version (backend + admin panel)

| Area | What |
|---|---|
| Video library | Admin panel → **Videos**: title, description, thumbnail URL, preview URL, duration, tags, video link, extra sources, category, visible toggle, server-side human readable timestamp. List has search, category filter and pagination (12 per page). **Watched & downloaded** tab shows Today / Yesterday / All time / custom range for Videos, Bollywood, Hollywood, Series, Live TV (also shown under *Carousel*). The app list API never returns playable links – they are released only when a user presses Play/Download. |
| Formats | `/fetch` returns Audio + Video (ready files, HLS and **auto-merge** pairs), Video-only and Audio-only with duration and size; best thumbnail/title are picked from yt-dlp. |
| Direct links | `.m3u8`, `.mp4`, `.mkv`, `.mp3`… are described by a built-in direct extractor (HLS master playlists become quality lists). SSRF-safe: private / loopback addresses are refused. |
| Clone protection | App refuses to run in parallel-space / dual-app / work-profile copies and sends a hash of the Widevine device id. Devices sharing that id are **linked to one account**, so a clone shares the original's premium and daily limits. Admin → user → *Unlink*. |
| Users | Dashboard search (device id, IP, model, note) → editor: notes, model/brand, counters, today's usage, own daily limits, subscription (plan/start/expiry), renew, revoke, ban, delete. |
| Rate limiting | Every route is rate limited per IP (`app_api`, `admin_api`, `login`, `site`, `apk`, `assets`, `telegram`, `health`, `relay`) with `429` + `Retry-After`; app endpoints are additionally limited per device. |
| Landing site | `/` landing page (hero, features, how to use, premium, FAQ, download), `/privacy`, `/terms`, `/dmca`, `/support`, `/developer`, `/download` (APK stream), `robots.txt`, `sitemap.xml`. Everything is edited in Admin → Settings → **Landing page** and **Terms, Privacy & DMCA**. |
| DMCA | One more HTML text, shown on the website and inside the app drawer. |

## Admin tips
* Settings → Landing page → `apk_url` is the direct link of your APK (GitHub release, your own storage…). `apk_mode=redirect`
  makes `/download` redirect instead of streaming through Render (saves bandwidth).
* Videos: only add links to content you own or are licensed to distribute. *Hide* or *Delete* removes a title instantly.
* Live TV items are normal library items with category *Live TV* and an `.m3u8` link; they show a LIVE badge.
