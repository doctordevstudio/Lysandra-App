# "Google Play Protect says this app may be fake / harmful" – what is going on and what to do

**Honest summary:** no app can switch Play Protect off, and no code change can *guarantee* a clean install for an APK that is
distributed outside the Play Store. Play Protect judges every sideloaded APK with cloud machine-learning and a reputation
score for the signing key + package name. A **new, unknown signing key + new package** is the single biggest reason for the
warning. What you can control:

## Done in this version (code)
* Removed every storage / media permission (the Status Saver is gone). The only permission left for old phones is
  `WRITE_EXTERNAL_STORAGE` for Android 9 and below.
* Removed unused Firebase AI / App Check debug libraries (less code, fewer manifest entries).
* Removed `Runtime.exec("which su")` and `/proc/self/maps` scanning from the security checks – process execution and
  memory-map reading are classic "malware-like" signals. Root / hook detection now only checks files and class names.
* Softened R8: no `-repackageclasses`, no `-overloadaggressively` (those make an APK look like packed malware). Logs are still stripped.
* `networkSecurityConfig` trusts only system CAs (no user-installed CAs).

## You must do (cannot be done in code)
1. **Always install the RELEASE APK signed with your own keystore.** Never share a debug-signed build. Keep the same
   `lysandra-release.jks` forever – reputation belongs to that key. (`buildapk.py` handles this.)
2. **Serve the APK from your own HTTPS domain** with the proper content type. The landing page `/download` does that
   (`application/vnd.android.package-archive`, `Content-Disposition: attachment`). Do not link to file-sharing sites.
3. **Submit the APK to Play Protect once:** install it, open *Play Store → profile → Play Protect → ⚙ → Improve harmful app
   detection* and when the “App scan recommended” card appears tap **Scan app** / *Send for scanning*. Repeat for each new
   version. Reputation builds as more people install the same signed APK without problems.
4. Keep the version stable for a while: constantly re-signing / renaming the package resets reputation.
5. Ad SDKs raise the heuristic score. Start.io is allowed by Google but any ad SDK can add to the risk.
6. The real fix for “installs happily like other apps” is **publishing on Google Play** (or another verified store), or
   completing Google's **developer verification** for sideloaded apps where it applies. Google has been tightening the
   rules for apps from unverified developers.

The landing page FAQ already tells users how to proceed: *More details → Install anyway*, or *Scan app* first.
