"""Default app configuration. Everything here is editable from the admin panel
(Settings) and is stored in Firebase under `config`; these values are only used
to seed a fresh database and to fill any missing key."""

TERMS_HTML = """<h2>Terms &amp; Conditions</h2>
<p>By using Lysandra you confirm that you are 18 years or older and that you will only download content you own or have permission to download.</p>
<ul><li>You are responsible for the content you download and how you use it.</li>
<li>Lysandra does not host any media; files are fetched from the original websites.</li>
<li>Premium is a digital service tied to your device ID. It is non-transferable.</li>
<li>Payments are verified manually. Fake payment proofs lead to a permanent ban.</li>
<li>We may change or discontinue features at any time.</li></ul>
<p>Contact support from inside the app for any questions.</p>"""

PRIVACY_HTML = """<h2>Privacy Policy</h2>
<p>Lysandra collects only what is required to run the service: an anonymous device identifier, device model, Android version, app version, IP address, and your download activity (links you fetch).</p>
<ul><li>Payment proofs (UTR and screenshot) are used only to verify your payment.</li>
<li>Advertising is served by Start.io which may use an advertising identifier.</li>
<li>We never sell your personal data.</li></ul>
<p>You can request deletion of your data through Customer Support.</p>"""

DMCA_HTML = """<h2>DMCA &amp; Copyright Policy</h2>
<p>Lysandra respects intellectual property. The app is a tool: it does not host, store or upload any media. Videos are fetched from the original websites at the request of the user, or are links added by the Lysandra team to content that is available for public viewing.</p>
<h3>Report infringing content</h3>
<p>If you are a copyright owner (or authorised to act for one) and believe a link listed in Lysandra infringes your rights, send a notice through <b>Customer Support</b> with:</p>
<ul><li>Your name, contact details and proof that you are the rights holder or their agent.</li>
<li>The exact title and where it appears in the app.</li>
<li>A statement that the use is not authorised by the owner, the law or its agent, and that your information is accurate.</li></ul>
<p>Valid notices are acted on promptly: the link is removed from the app and repeat infringers are blocked.</p>
<h3>Users</h3>
<p>You must only download or share content you own or have permission to use. You are responsible for how you use downloaded files.</p>"""

DEFAULT_CONFIG = {
    "app": {
        "name": "Lysandra",
        "tagline": "Ultra Media & Status Downloader",
        "version_code": 1,
        "min_version_code": 1,
        "latest_version_name": "1.0",
        "update_url": "https://t.me/lysandraapp",
        "update_message": "A newer version of Lysandra is available. Please download the latest version from our Telegram channel to continue.",
        "unreachable_message": "Unable to reach Lysandra servers. Please check your internet connection or download the latest version from our Telegram channel.",
        "supported_platforms_text": "YouTube, Instagram, Facebook, TikTok, Twitter/X, Terabox, Pinterest, Reddit, Vimeo and 1000+ more.",
    },
    "support": {
        "title": "Customer Support",
        "message": "Facing a payment, download or premium issue? Our support team replies on Telegram, usually within a few hours.",
        "telegram_url": "https://t.me/drdevsupportbot",
        "channel_url": "https://t.me/lysandraapp",
        "email": "",
        "hours": "10:00 AM - 10:00 PM IST",
    },
    "developer": {
        "name": "Dr. Dev || Dr. Hamza",
        "image_url": "",
        "bio": "My name is Dr. Dev || Dr. Hamza, currently a NEET 1st year dropper student. I know Python, Java, PHP, Kotlin and JS. If you want to hire me for making a Website, App, Telegram Bot or Automation, contact me on Telegram.",
        "rate": "$30/hour",
        "contact_url": "https://t.me/drdevsupportapp",
        "skills": "Python,Java,PHP,Kotlin,JS",
    },
    "share": {
        "app_url": "https://GitHub.com/doctordevstudio/myapp/lysandraapp.apk",
        "text": "Download any video from 1000+ websites with Lysandra - fast, free and simple.",
    },
    "legal": {"terms_html": TERMS_HTML, "privacy_html": PRIVACY_HTML, "dmca_html": DMCA_HTML},
    "ads": {
        "enabled": True,
        "startio_app_id": "",
        "banner_enabled": True,
        "native_enabled": True,
        "interstitial_enabled": True,
        "rewarded_enabled": True,
        "interstitial_cooldown_sec": 45,
    },
    "limits": {"free_daily_downloads": 2, "free_daily_watch": 5, "fetch_per_minute": 12},
    "premium": {
        "plans": [
            # downloads_per_day / watch_per_day: 0 = unlimited. The 1 Month plan is deliberately limited
            # so that the unlimited 3 Months plan is the obvious best choice.
            {"id": "m1", "name": "1 Month", "days": 30, "price": 25, "badge": "", "downloads_per_day": 10, "watch_per_day": 15},
            {"id": "m3", "name": "3 Months", "days": 90, "price": 49, "badge": "RECOMMENDED", "downloads_per_day": 0, "watch_per_day": 0},
            {"id": "y1", "name": "1 Year", "days": 365, "price": 149, "badge": "BEST VALUE", "downloads_per_day": 0, "watch_per_day": 0},
        ],
        "features": ["Ads free in every plan", "Priority support"],
    },
    "payment": {"txn_expiry_minutes": 10, "submitted_ttl_hours": 24, "max_pending_per_device": 2,
                "max_txn_per_hour": 6, "rotation": "success"},
    "security": {"block_vpn": True, "block_proxy": True, "block_emulator": True,
                 "block_datacenter": True, "block_rooted": False},
    "theme": {"admin_default": "day"},
    "landing": {
        "hero_title": "Download & watch videos from 1000+ websites",
        "hero_subtitle": "Lysandra is a fast, beautiful media downloader and player for Android. Paste a link, pick a quality, and save or stream it with the built-in ExoPlayer.",
        "apk_url": "https://GitHub.com/doctordevstudio/myapp/lysandraapp.apk",
        "version": "1.0", "size": "", "requirements": "Android 7.0 and above",
        "telegram_url": "https://t.me/lysandraapp",
        "features": [
            "Fast downloads|Resumable downloads with pause, resume, speed and time left for every file.",
            "Every quality|Pick Audio + Video, Video only or Audio only. When a site has no combined file Lysandra merges video and audio on your phone.",
            "Built-in player|Smooth ExoPlayer playback for MP4, HLS (.m3u8) and more, with quality selection.",
            "Videos & Movies|Browse Bollywood, Hollywood, Series and Live TV sections curated inside the app.",
            "Premium plans|Remove ads and lift the daily limits with simple UPI payments, activated on your device.",
            "Private & secure|No account needed. Encrypted, signed requests and no hidden permissions.",
        ],
        "steps": [
            "Download the APK|Tap Download APK and allow installation from your browser or file manager when Android asks.",
            "Open Lysandra|Accept the terms on first launch and let the app connect.",
            "Paste a link|Copy a video link, or share it to Lysandra from any app, then tap Fetch.",
            "Choose quality|Pick a quality tab and tap play to watch or download to save.",
        ],
        "faqs": [
            "Is Lysandra free?|Yes. Free users get a daily number of downloads and plays. Premium removes ads and the limits.",
            "Which websites are supported?|YouTube, Instagram, Facebook, TikTok, X/Twitter, Vimeo, Reddit, Pinterest and 1000+ more sites, plus direct MP4 and HLS links.",
            "Android shows a Play Protect warning, is it safe?|Android warns about every app installed outside the Play Store that Google has not scanned yet. Tap More details, then Install anyway. You can also open Play Protect and choose Scan app.",
            "Where are my downloads saved?|In your gallery under Movies/Lysandra (music goes to Music/Lysandra).",
            "Why can't I use a VPN?|VPN and proxy connections are blocked to protect payments and stop abuse of the free limits.",
            "How do I get premium?|Open the menu, tap Go Premium, pick a plan and pay with any UPI app. It activates on your device after verification.",
        ],
        "changelog": "First public release.",
    },
    "maintenance": {"enabled": False, "message": "<h3>We'll be right back</h3><p>Lysandra is under maintenance. Please try again shortly.</p>"},
}

# Which top-level sections may be edited from the admin panel
EDITABLE_SECTIONS = list(DEFAULT_CONFIG.keys())

# Sections the app receives at boot (whitelist – nothing else leaves the server)
APP_SECTIONS = ["app", "support", "developer", "share", "ads", "limits", "premium", "maintenance"]
