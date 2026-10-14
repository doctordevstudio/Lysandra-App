"""Telegram bot: notifications to admin + UPI owner and the /verify, /fail commands."""
import html
import json

import requests

from .util import fmt_ist

API = "https://api.telegram.org"


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=False)


class Telegram:
    def __init__(self, ctx):
        self.ctx = ctx
        self.s = requests.Session()

    @property
    def token(self):
        return self.ctx.settings.telegram_bot_token

    @property
    def enabled(self):
        return bool(self.token)

    def api(self, method, data=None, files=None):
        if not self.enabled:
            return None
        try:
            r = self.s.post(f"{API}/bot{self.token}/{method}", data=data, files=files, timeout=20)
            j = r.json()
            if not j.get("ok"):
                self.ctx.log.warning("telegram %s failed: %s", method, str(j)[:200])
            return j
        except Exception as e:
            self.ctx.log.warning("telegram %s error: %s", method, e.__class__.__name__)
            return None

    def send(self, chat_id, text, buttons=None):
        if not chat_id:
            return None
        data = {"chat_id": chat_id, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": "true"}
        if buttons:
            data["reply_markup"] = json.dumps({"inline_keyboard": buttons})
        return self.api("sendMessage", data)

    def send_photo(self, chat_id, image_bytes, caption="", buttons=None, name="proof.jpg"):
        if not chat_id:
            return None
        data = {"chat_id": chat_id, "caption": caption[:1000], "parse_mode": "HTML"}
        if buttons:
            data["reply_markup"] = json.dumps({"inline_keyboard": buttons})
        return self.api("sendPhoto", data, files={"photo": (name, image_bytes)})

    def file_bytes(self, file_id):
        j = self.api("getFile", {"file_id": file_id})
        if not j or not j.get("ok"):
            return None
        try:
            r = self.s.get(f"{API}/file/bot{self.token}/{j['result']['file_path']}", timeout=20)
            return r.content if r.ok else None
        except Exception:
            return None

    def set_webhook(self):
        s = self.ctx.settings
        if not (self.enabled and s.public_url and s.telegram_webhook_secret):
            return False
        j = self.api("setWebhook", {"url": f"{s.public_url}/tg/{s.telegram_webhook_secret}",
                                    "secret_token": s.telegram_webhook_secret,
                                    "allowed_updates": json.dumps(["message", "callback_query"]),
                                    "drop_pending_updates": "false"})
        return bool(j and j.get("ok"))

    # ----------------------------------------------------------- recipients
    def recipients(self, txn):
        out = []
        for c in (self.ctx.settings.telegram_admin_chat_id, str(txn.get("chat_id") or "")):
            if c and c not in out:
                out.append(c)
        return out

    def notify_created(self, txn):
        for chat in self.recipients(txn):
            is_admin = chat == self.ctx.settings.telegram_admin_chat_id
            lines = ["🧾 <b>New transaction</b>", f"Txn ID: <code>{esc(txn['txn_id'])}</code>",
                     f"Plan: {esc(txn['plan_name'])}  •  Amount: <b>₹{txn['amount']}</b>",
                     f"UPI: <code>{esc(txn['upi_id'])}</code> ({esc(txn['upi_name'])})",
                     f"Valid for {txn['expiry_min']} minutes"]
            if is_admin:
                lines += [f"Device: <code>{esc(txn['dev'][:12])}…</code>", f"IP: {esc(txn['ip'])}"]
            self.send(chat, "\n".join(lines))

    def notify_proof(self, txn, image_bytes, qr_png):
        cap = "\n".join(["📎 <b>Payment proof submitted</b>", f"Txn ID: <code>{esc(txn['txn_id'])}</code>",
                         f"UTR: <code>{esc(txn['utr'])}</code>", f"Amount: <b>₹{txn['amount']}</b> ({esc(txn['plan_name'])})",
                         f"UPI: <code>{esc(txn['upi_id'])}</code>", "",
                         f"If the money is received send:\n<code>/verify {esc(txn['txn_id'])}</code>",
                         f"If it is fake send:\n<code>/fail {esc(txn['txn_id'])} reason</code>"])
        btn = [[{"text": "✅ Verify payment", "callback_data": f"v|{txn['txn_id']}"}]]
        file_id = None
        for chat in self.recipients(txn):
            res = self.send_photo(chat, image_bytes, cap, buttons=btn)
            try:
                if not file_id and res and res.get("ok"):
                    file_id = res["result"]["photo"][-1]["file_id"]
            except Exception:
                pass
            if qr_png:
                self.send_photo(chat, qr_png, f"QR for <code>{esc(txn['txn_id'])}</code> • ₹{txn['amount']} → "
                                              f"<code>{esc(txn['upi_id'])}</code>", name="qr.png")
        return file_id

    # ----------------------------------------------------------- incoming updates
    def handle_update(self, upd):
        pay = self.ctx.payments
        if "callback_query" in upd:
            cq = upd["callback_query"]
            chat = str(cq.get("message", {}).get("chat", {}).get("id", ""))
            data = cq.get("data", "")
            self.api("answerCallbackQuery", {"callback_query_id": cq.get("id", "")})
            if data.startswith("v|"):
                self._reply(chat, pay.verify(data[2:], chat))
            return
        msg = upd.get("message") or {}
        chat = str(msg.get("chat", {}).get("id", ""))
        text = (msg.get("text") or "").strip()
        if not chat or not text.startswith("/"):
            return
        parts = text.split(None, 2)
        cmd = parts[0].split("@")[0].lower()
        if cmd in ("/start", "/id", "/help"):
            self.send(chat, "👋 <b>Lysandra payments bot</b>\nYour chat ID: <code>%s</code>\n\n"
                            "Give this chat ID to the admin so you can be added as a UPI receiver.\n\n"
                            "<b>Commands</b>\n/verify <code>TXNID</code> – confirm money received\n"
                            "/fail <code>TXNID reason</code> – reject a fake payment\n"
                            "/pending – your pending payments\n/status <code>TXNID</code>" % esc(chat))
        elif cmd == "/verify" and len(parts) >= 2:
            self._reply(chat, pay.verify(parts[1].upper(), chat))
        elif cmd == "/fail" and len(parts) >= 2:
            self._reply(chat, pay.fail(parts[1].upper(), parts[2] if len(parts) > 2 else "", chat))
        elif cmd == "/pending":
            self._reply(chat, pay.pending_text(chat))
        elif cmd == "/status" and len(parts) >= 2:
            self._reply(chat, pay.status_text(parts[1].upper(), chat))
        elif cmd in ("/verify", "/fail"):
            self.send(chat, f"Usage: <code>{cmd} TXNID{' reason' if cmd == '/fail' else ''}</code>")

    def _reply(self, chat, res):
        self.send(chat, res.get("text", ""))
        for other, text in res.get("also", []):
            if other and other != chat:
                self.send(other, text)
