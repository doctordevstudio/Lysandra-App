# Security model

| Layer | What it does |
|---|---|
| Signed + encrypted API | AES-256-GCM body, HMAC-SHA256 over method/path/time/nonce/device/APK-cert/body, ±5 min clock window, one-time nonces (replay protection) |
| Obfuscated client secrets | URL + secret stored as masked, shuffled chunks (`Secrets.kt`), never plain strings; R8 minify + log stripping in release |
| Server-side enforcement | Daily limits, plan limits, premium, blocked domains, VPN/proxy/datacenter IP checks, maintenance, minimum version are all decided by the server. Download links are only returned by `/authorize` after the limit check, so patching the app cannot unlock anything |
| Device id | SHA-256(ANDROID_ID, package); premium is bound to it |
| Fraud controls | one UTR / screenshot hash can be used once, 12-digit UTR, image validated, per-device txn limits, `/fail` revokes premium |
| Admin panel | single session, CSRF token, SameSite=Strict HttpOnly cookie, 15 min idle, 3 failed logins lock browser/IP fingerprint 24 h, audit log, CSP, hidden path |
| Cloudflare option | `ORIGIN_SECRET` rejects traffic that did not pass Cloudflare |

Honest limits: an APK can always be reverse engineered. The design makes cheating pointless (everything valuable is server
side) and makes tampering expensive, but no client-side check is unbreakable. Play Integrity is not used because the app is
distributed outside the Play Store.
