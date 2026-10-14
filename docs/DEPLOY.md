# Deploy Lysandra backend on Render (free) + Firebase + Cloudflare + Telegram

## 1. Firebase Realtime Database
1. Create a project, enable **Realtime Database**, copy its URL (`https://xxxx-default-rtdb.firebaseio.com`).
2. Rules (as you asked, the *server* is the only client that knows the URL, it is never sent to the app):
   ```json
   { "rules": { ".read": true, ".write": true } }
   ```
   Tip: the URL is secret-by-obscurity. For stronger protection set rules to `false`, create a
   database secret and put it in `FIREBASE_DB_SECRET` – the server appends it as `?auth=`.

## 2. Telegram bot
1. Create a bot with @BotFather -> `TELEGRAM_BOT_TOKEN`.
2. Send `/start` to your bot -> it replies with your **chat id** -> `TELEGRAM_ADMIN_CHAT_ID`.
3. Every UPI receiver must open the bot and send `/start` too (they read their own chat id and give it to you).
4. Commands (admin + the UPI owner of that transaction only):
   `/verify LYS1234567890`, `/fail LYS1234567890 reason`, `/pending`, `/status LYS...`.
   Proof messages also carry a **Verify** button.
5. The webhook is set automatically at start-up from `PUBLIC_URL` + `TELEGRAM_WEBHOOK_SECRET`.

## 3. Render
1. Push the `backend/` folder to GitHub, create **New > Blueprint** (uses `render.yaml`) or a *Web Service*:
   build `pip install -r requirements.txt`, start
   `gunicorn wsgi:app --worker-class gthread --workers 1 --threads 24 --timeout 90 --bind 0.0.0.0:$PORT`.
   **Keep one worker** (nonce cache, admin session and config cache live in memory).
2. Environment variables: see `.env.example`. Minimum: `FIREBASE_DB_URL`, `APP_SECRET`, `ADMIN_USER`, `ADMIN_PASSWORD`,
   `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_CHAT_ID`, `TELEGRAM_WEBHOOK_SECRET`, `PUBLIC_URL`.
   `APP_SECRET` must equal the secret inside the APK: use the one in `GENERATED_APP_SECRET.txt`
   (it matches the `Secrets.kt` already inside the Android project) or generate a new pair with
   `python tools/gen_secrets.py https://lysandraapp.onrender.com ../android/app/src/main/java/com/drdev/hamza/net/Secrets.kt`.
3. Free instances sleep after 15 min idle. Add an UptimeRobot monitor on `https://lysandraapp.onrender.com/healthz`
   (every 5 min) so payments / Telegram webhooks are never delayed. Expiry of transactions & subscriptions is also
   evaluated lazily on every request, so nothing is lost if the instance sleeps.
4. Admin panel: `https://lysandraapp.onrender.com/lysandra-admin` (path = `ADMIN_PATH`). One active session,
   15 min idle logout, 3 wrong passwords lock that device fingerprint / browser / IP for 24 h.

## 4. Cloudflare (free) in front of Render
* Proxy the domain (orange cloud). Turn on *Bot Fight Mode*, add a rate-limit rule on `/api/` (e.g. 120 req/min/IP).
* Add a **Transform Rule > Modify Request Header**: set `X-Origin-Secret: <random>` and put the same value in
  `ORIGIN_SECRET`. Direct hits on `onrender.com` without the header get 403, so Cloudflare protections cannot be bypassed.
* If you keep using the plain `onrender.com` URL leave `ORIGIN_SECRET` empty.

## 5. Android signing certificate check (anti-tamper)
Get your release certificate hash: `keytool -list -v -keystore your.jks | grep SHA256` and put it (lowercase, no colons)
in `ALLOWED_APK_SHA256`. The app sends its certificate hash with every signed request, so a re-signed / modded APK is rejected.

## 6. YouTube
YouTube blocks datacenter IPs. Put residential / ISP proxies in `YOUTUBE_PROXIES` (comma separated, rotated per request)
and optionally `YT_COOKIES` (Netscape cookie file text). Because googlevideo links are locked to the IP that resolved them,
YouTube files are streamed through `/api/v1/relay` using the same proxy (Render free has a monthly bandwidth quota – watch it).
