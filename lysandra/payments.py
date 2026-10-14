"""Manual UPI payment gateway: transactions, UPI rotation, premium credit."""
import io
import secrets
import threading
import time

from . import qr
from .security import ApiError
from .telegram import esc
from .util import (clamp, date_range, fmt_ist, now_ts, push_id, sha256_hex, today_str, ts_to_date)

PREMIUM_PATH = "premium"


class Payments:
    def __init__(self, ctx):
        self.ctx = ctx
        self.db = ctx.db
        self.lock = threading.RLock()

    # ------------------------------------------------------------ config
    def cfg(self):
        return self.ctx.cfg.get("payment")

    def plans(self):
        return self.ctx.cfg.get("premium", "plans", [])

    def plan(self, plan_id):
        for p in self.plans():
            if p.get("id") == plan_id:
                return p
        return None

    # ------------------------------------------------------------ premium state
    def premium_status(self, dev):
        rec = self.db.get(f"{PREMIUM_PATH}/{dev}")
        now = now_ts()
        if not rec:
            return {"active": False}
        if rec.get("status") == "active" and rec.get("expires", 0) <= now:
            self.db.patch(f"{PREMIUM_PATH}/{dev}", {"status": "expired"})
            self._hist(dev, "expired", rec.get("plan_name", ""))
            rec["status"] = "expired"
        active = rec.get("status") == "active" and rec.get("expires", 0) > now
        return {"active": active, "plan": rec.get("plan_name", ""), "plan_id": rec.get("plan_id", ""), "until": rec.get("expires", 0),
                "started": rec.get("started", 0), "days_left": max(0, (rec.get("expires", 0) - now + 86399) // 86400),
                "status": rec.get("status")}

    def _hist(self, dev, action, detail="", by="system"):
        self.db.put(f"premium_hist/{dev}/{push_id()}", {"ts": now_ts(), "action": action, "detail": detail, "by": by})

    def _sub_event(self, dev, kind, rec, by):
        self.db.put(f"sub_events/{today_str()}/{push_id()}",
                    {"dev": dev, "kind": kind, "plan_id": rec.get("plan_id", ""), "plan_name": rec.get("plan_name", ""),
                     "expires": rec.get("expires", 0), "ts": now_ts(), "by": by})

    def grant(self, dev, days, plan_name, txn_id="", amount=0, by="system", plan_id="", kind="purchase"):
        """Credit premium; extends from the current expiry when already active."""
        with self.lock:
            now = now_ts()
            cur = self.db.get(f"{PREMIUM_PATH}/{dev}") or {}
            base = cur.get("expires", 0) if cur.get("status") == "active" and cur.get("expires", 0) > now else now
            rec = {"plan_id": plan_id, "plan_name": plan_name, "started": cur.get("started", now) if base > now else now,
                   "expires": base + int(days) * 86400, "txn": txn_id, "amount": amount, "status": "active",
                   "updated": now}
            self.db.put(f"{PREMIUM_PATH}/{dev}", rec)
            self._hist(dev, "grant", f"{plan_name} +{days}d txn={txn_id}", by)
            self._sub_event(dev, kind, rec, by)
            return rec

    def edit(self, dev, started=None, expires=None, plan_id=None, by="admin"):
        """Admin: change plan / start / expiry of a subscription (creates it if the device had none)."""
        with self.lock:
            now = now_ts()
            cur = self.db.get(f"{PREMIUM_PATH}/{dev}") or {"started": now, "expires": now, "amount": 0, "txn": ""}
            if plan_id is not None and plan_id != "":
                p = self.plan(plan_id)
                if not p:
                    raise ApiError("bad_plan", "Unknown plan")
                cur["plan_id"], cur["plan_name"] = p["id"], p["name"]
            if started:
                cur["started"] = int(started)
            if expires:
                cur["expires"] = int(expires)
            cur["status"] = "active" if cur.get("expires", 0) > now else "expired"
            cur["updated"] = now
            self.db.put(f"{PREMIUM_PATH}/{dev}", cur)
            self._hist(dev, "edit", f"start={cur.get('started')} exp={cur.get('expires')} plan={cur.get('plan_id')}", by)
            self._sub_event(dev, "edit", cur, by)
            return cur

    def revoke(self, dev, by="system", reason=""):
        cur = self.db.get(f"{PREMIUM_PATH}/{dev}")
        if not cur:
            return False
        self.db.patch(f"{PREMIUM_PATH}/{dev}", {"status": "revoked", "expires": min(cur.get("expires", 0), now_ts()),
                                               "updated": now_ts()})
        self._hist(dev, "revoke", reason, by)
        return True

    def renew(self, dev, days, by="admin"):
        cur = self.db.get(f"{PREMIUM_PATH}/{dev}") or {}
        return self.grant(dev, days, cur.get("plan_name") or "Admin renewal", cur.get("txn", ""),
                          0, by, cur.get("plan_id", ""), kind="renew")

    # ------------------------------------------------------------ transactions
    def _txn_path(self, txn_id):
        d = self.db.get(f"txn_idx/{txn_id}")
        return f"txns/{d}/{txn_id}" if d else None

    def get_txn(self, txn_id):
        p = self._txn_path(txn_id)
        return self.db.get(p) if p else None

    def _save(self, txn):
        self.db.put(f"txns/{txn['date']}/{txn['txn_id']}", txn)

    def _pick_upi(self):
        upis = [{**u, "id": k} for k, u in (self.db.get("upi") or {}).items() if isinstance(u, dict) and u.get("active", True)]
        if not upis:
            return None
        if self.cfg().get("rotation") == "round_robin":
            upis.sort(key=lambda u: u.get("last_assigned", 0))
        else:  # fair share of received payments, then least recently shown
            upis.sort(key=lambda u: (u.get("success_count", 0), u.get("last_assigned", 0)))
        return upis[0]

    def create_txn(self, dev, ip, plan_id):
        plan = self.plan(plan_id)
        if not plan:
            raise ApiError("bad_plan", "Invalid plan selected")
        cfg = self.cfg()
        self.expire_due()
        with self.lock:
            mine = self.my_txns(dev, 30)
            pend = [t for t in mine if t["status"] == "pending" and not t.get("proof")]
            for t in pend:
                if t["plan_id"] == plan_id and t["expires_at"] > now_ts():
                    return self.public_txn(t)  # reuse – avoids txn spam / rotation burn
            if len(pend) >= int(cfg.get("max_pending_per_device", 2)):
                raise ApiError("too_many", "You already have pending payments. Complete or wait for them to expire.")
            hour_ago = now_ts() - 3600
            if len([t for t in mine if t["created"] > hour_ago]) >= int(cfg.get("max_txn_per_hour", 6)):
                raise ApiError("rate", "Too many payment attempts. Please try again later.")
            upi = self._pick_upi()
            if not upi:
                raise ApiError("no_upi", "Payments are temporarily unavailable. Please try again later.")
            for _ in range(10):
                txn_id = "LYS" + "".join(str(secrets.randbelow(10)) for _ in range(10))
                if self.db.get(f"txn_idx/{txn_id}") is None:
                    break
            now = now_ts()
            exp_min = int(cfg.get("txn_expiry_minutes", 10))
            txn = {"txn_id": txn_id, "date": today_str(), "dev": dev, "ip": ip, "plan_id": plan_id,
                   "plan_name": plan["name"], "days": int(plan["days"]), "amount": int(plan["price"]),
                   "upi_key": upi["id"], "upi_id": upi["upi_id"], "upi_name": upi.get("name", ""),
                   "chat_id": str(upi.get("chat_id", "")), "status": "pending", "proof": False,
                   "created": now, "expires_at": now + exp_min * 60, "expiry_min": exp_min}
            self.db.put(f"txn_idx/{txn_id}", txn["date"])
            self.db.put(f"txn_open/{txn_id}", txn["date"])
            self._save(txn)
            self.db.patch(f"upi/{upi['id']}", {"last_assigned": now})
            self.db.increment(f"upi/{upi['id']}/txn_count", 1)
        self.ctx.bg(self.ctx.telegram.notify_created, txn)
        return self.public_txn(txn)

    def public_txn(self, t):
        note = f"Lysandra {t['txn_id']}"
        uri = (f"upi://pay?pa={t['upi_id']}&pn={t['upi_name'].replace(' ', '%20') or 'Lysandra'}"
               f"&am={t['amount']}.00&cu=INR&tn={note.replace(' ', '%20')}")
        return {"txn": t["txn_id"], "amount": t["amount"], "plan": t["plan_name"], "days": t["days"],
                "upi_id": t["upi_id"], "payee": t["upi_name"] or "Lysandra", "note": note, "upi_uri": uri,
                "status": t["status"], "proof": bool(t.get("proof")), "expires_at": t["expires_at"],
                "created": t["created"], "reason": t.get("fail_reason", "")}

    def my_txns(self, dev, limit=20):
        out = []
        for d in (today_str(), today_str(-1)):
            for t in (self.db.get(f"txns/{d}") or {}).values():
                if isinstance(t, dict) and t.get("dev") == dev:
                    out.append(t)
        out.sort(key=lambda t: -t["created"])
        return out[:limit]

    def status(self, dev, txn_id):
        self.expire_due()
        t = self.get_txn(txn_id)
        if not t or t.get("dev") != dev:
            raise ApiError("not_found", "Transaction not found")
        return {"txn": self.public_txn(t), "premium": self.premium_status(dev)}

    # ------------------------------------------------------------ proof
    @staticmethod
    def _check_image(data):
        if len(data) > 2_500_000 or len(data) < 3_000:
            raise ApiError("bad_image", "Screenshot must be a clear image under 2.5 MB")
        if not (data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n"):
            raise ApiError("bad_image", "Only JPG or PNG screenshots are accepted")
        try:
            from PIL import Image
            im = Image.open(io.BytesIO(data))
            im.verify()
            if min(im.size) < 200:
                raise ApiError("bad_image", "Screenshot is too small")
        except ApiError:
            raise
        except Exception:
            raise ApiError("bad_image", "Invalid image file")

    def submit_proof(self, dev, txn_id, utr, image):
        utr = "".join(c for c in str(utr) if c.isdigit())
        if len(utr) != 12:
            raise ApiError("bad_utr", "Enter a valid 12-digit UTR / Reference number")
        self._check_image(image)
        with self.lock:
            t = self.get_txn(txn_id)
            if not t or t.get("dev") != dev:
                raise ApiError("not_found", "Transaction not found")
            self.expire_due()
            t = self.get_txn(txn_id)
            if t["status"] == "success":
                raise ApiError("done", "This payment is already verified")
            if t["status"] != "pending" or t["expires_at"] < now_ts():
                raise ApiError("expired", "This transaction has expired. Please start a new payment.")
            if t.get("proof"):
                raise ApiError("dup", "Proof already submitted. Please wait for verification.")
            other = self.db.get(f"utr_idx/{utr}")
            if other and other != txn_id:
                ot = self.get_txn(other)
                if ot and ot["status"] != "failed":
                    raise ApiError("dup_utr", "This UTR was already used for another payment")
            h = sha256_hex(image)
            other = self.db.get(f"proof_idx/{h}")
            if other and other != txn_id:
                raise ApiError("dup_image", "This screenshot was already used. Upload your own payment screenshot.")
            t.update({"proof": True, "utr": utr, "submitted_at": now_ts(), "proof_hash": h})
            self.db.put(f"utr_idx/{utr}", txn_id)
            self.db.put(f"proof_idx/{h}", txn_id)
            self._save(t)
        self.ctx.bg(self._send_proof, t, image)
        return self.public_txn(t)

    def _send_proof(self, t, image):
        try:
            png = qr.make_png(self.public_txn(t)["upi_uri"], scale=6)
        except Exception:
            png = None
        file_id = self.ctx.telegram.notify_proof(t, image, png)
        if file_id:  # the screenshot lives only in Telegram; keep its id so the admin panel can show it
            self.db.put(f"txns/{t['date']}/{t['txn_id']}/proof_file", file_id)

    def proof_image(self, txn_id):
        t = self.get_txn(txn_id)
        if not t or not t.get("proof_file"):
            return None
        return self.ctx.telegram.file_bytes(t["proof_file"])

    # ------------------------------------------------------------ verify / fail
    def _authorized(self, t, chat):
        admin = self.ctx.settings.telegram_admin_chat_id
        return chat in (admin, str(t.get("chat_id") or ""))

    def verify(self, txn_id, by_chat="admin", by_label=None):
        by = by_label or f"tg:{by_chat}"
        with self.lock:
            t = self.get_txn(txn_id)
            if not t:
                return {"text": f"❌ Transaction <code>{esc(txn_id)}</code> not found."}
            if by_chat != "admin" and not self._authorized(t, by_chat):
                return {"text": "⛔ You are not allowed to verify this transaction."}
            if t["status"] == "success":
                return {"text": f"ℹ️ <code>{esc(txn_id)}</code> is already verified."}
            admin_chat = self.ctx.settings.telegram_admin_chat_id
            if t["status"] == "failed" and by_chat not in ("admin", admin_chat):
                return {"text": f"⛔ <code>{esc(txn_id)}</code> was rejected/expired. Only the admin can re-open it."}
            now = now_ts()
            was_failed = t["status"] == "failed"
            t.update({"status": "success", "verified_at": now, "verified_by": by, "fail_reason": ""})
            self._save(t)
            self.db.delete(f"txn_open/{txn_id}")
            self.db.put(f"earn/{today_str()}/{txn_id}", {"amount": t["amount"], "upi": t["upi_key"], "dev": t["dev"],
                                                         "plan": t["plan_name"], "ts": now})
            self.db.increment(f"upi/{t['upi_key']}/success_count", 1)
            self.db.increment(f"upi/{t['upi_key']}/amount_total", t["amount"])
            if was_failed:
                self.db.increment(f"upi/{t['upi_key']}/failed_count", -1)
            self.grant(t["dev"], t["days"], t["plan_name"], txn_id, t["amount"], by, t["plan_id"])
        text = f"✅ Verified <code>{esc(txn_id)}</code> – {esc(t['plan_name'])} credited (₹{t['amount']})."
        also = [(c, text + f"\nBy: {esc(by)}") for c in self.ctx.telegram.recipients(t)]
        return {"text": text, "also": also}

    def fail(self, txn_id, reason, by_chat="admin", by_label=None):
        by = by_label or f"tg:{by_chat}"
        reason = clamp(reason, 200).strip() or "Rejected by receiver"
        with self.lock:
            t = self.get_txn(txn_id)
            if not t:
                return {"text": f"❌ Transaction <code>{esc(txn_id)}</code> not found."}
            if by_chat != "admin" and not self._authorized(t, by_chat):
                return {"text": "⛔ You are not allowed to fail this transaction."}
            was_success = t["status"] == "success"
            if t["status"] == "failed":
                return {"text": f"ℹ️ <code>{esc(txn_id)}</code> is already failed."}
            t.update({"status": "failed", "fail_reason": reason, "failed_at": now_ts(), "failed_by": by})
            self._save(t)
            self.db.delete(f"txn_open/{txn_id}")
            self.db.increment(f"upi/{t['upi_key']}/failed_count", 1)
            if was_success:
                self.db.increment(f"upi/{t['upi_key']}/success_count", -1)
                self.db.increment(f"upi/{t['upi_key']}/amount_total", -t["amount"])
                for d in date_range(t["date"], today_str(), 30):
                    self.db.delete(f"earn/{d}/{txn_id}")
                self.revoke(t["dev"], by, f"txn {txn_id} failed: {reason}")
        text = f"🚫 <code>{esc(txn_id)}</code> marked FAILED. Reason: {esc(reason)}"
        if was_success:
            text += "\nPremium for this device has been cancelled."
        also = [(c, text + f"\nBy: {esc(by)}") for c in self.ctx.telegram.recipients(t)]
        return {"text": text, "also": also}

    def pending_text(self, chat):
        admin = chat == self.ctx.settings.telegram_admin_chat_id
        rows = []
        for tid in (self.db.get("txn_open", shallow=True) or {}):
            t = self.get_txn(tid)
            if t and t["status"] == "pending" and (admin or str(t.get("chat_id")) == chat):
                rows.append(f"<code>{tid}</code> ₹{t['amount']} {'📎 proof' if t.get('proof') else '⏳ waiting'}")
        return {"text": "Pending payments:\n" + ("\n".join(rows[:30]) if rows else "None 🎉")}

    def status_text(self, txn_id, chat):
        t = self.get_txn(txn_id)
        if not t or not self._authorized(t, chat):
            return {"text": "Not found."}
        return {"text": f"<code>{txn_id}</code>\nStatus: <b>{t['status']}</b>\nAmount: ₹{t['amount']}\n"
                        f"UTR: {esc(t.get('utr', '-'))}\nCreated: {fmt_ist(t['created'])}"}

    # ------------------------------------------------------------ expiry
    def expire_due(self):
        now = now_ts()
        ttl = int(self.cfg().get("submitted_ttl_hours", 24)) * 3600
        open_ids = (self.db.get("txn_open", shallow=True) or {}).keys()
        for tid in list(open_ids):
            t = self.get_txn(tid)
            if not t or t["status"] != "pending":
                self.db.delete(f"txn_open/{tid}")
                continue
            if not t.get("proof") and t["expires_at"] < now:
                reason = f"Payment not completed within {t.get('expiry_min', 10)} minutes"
            elif t.get("proof") and t.get("submitted_at", now) + ttl < now:
                reason = "Not verified by receiver within 24 hours"
            else:
                continue
            t.update({"status": "failed", "fail_reason": reason, "failed_at": now, "failed_by": "auto"})
            self._save(t)
            self.db.delete(f"txn_open/{tid}")
            self.db.increment(f"upi/{t['upi_key']}/failed_count", 1)
            if t.get("utr"):
                self.db.delete(f"utr_idx/{t['utr']}")
            if t.get("proof_hash"):
                self.db.delete(f"proof_idx/{t['proof_hash']}")

    def expire_premiums(self):
        now = now_ts()
        n = 0
        for dev, rec in (self.db.get(PREMIUM_PATH) or {}).items():
            if isinstance(rec, dict) and rec.get("status") == "active" and rec.get("expires", 0) <= now:
                self.db.patch(f"{PREMIUM_PATH}/{dev}", {"status": "expired"})
                self._hist(dev, "expired", rec.get("plan_name", ""))
                n += 1
        return n

    # ------------------------------------------------------------ admin queries
    def txns_range(self, d_from, d_to):
        a, b = min(d_from, d_to), max(d_from, d_to)
        raw = self.db.get("txns", order_by_key=True, start_at=a, end_at=b) or {}
        out = []
        for day in sorted(raw):
            for t in (raw[day] or {}).values():
                if isinstance(t, dict):
                    out.append(t)
        out.sort(key=lambda t: -t["created"])
        return out

    def earnings_range(self, d_from, d_to):
        a, b = min(d_from, d_to), max(d_from, d_to)
        raw = self.db.get("earn", order_by_key=True, start_at=a, end_at=b) or {}
        rows = []
        for day, items in raw.items():
            for tid, e in (items or {}).items():
                rows.append({"txn": tid, "date": day, **e})
        return rows

    def upi_report(self, d_from, d_to):
        txns = self.txns_range(d_from, d_to)
        upis = {k: {**v, "id": k} for k, v in (self.db.get("upi") or {}).items() if isinstance(v, dict)}
        rep = {}
        for k, u in upis.items():
            rep[k] = {"id": k, "name": u.get("name"), "upi_id": u.get("upi_id"), "chat_id": u.get("chat_id"),
                      "active": u.get("active", True), "created": u.get("created"),
                      "generated": 0, "success": 0, "failed": 0, "pending": 0, "amount": 0,
                      "all_success": u.get("success_count", 0), "all_amount": u.get("amount_total", 0),
                      "all_generated": u.get("txn_count", 0)}
        for t in txns:
            r = rep.get(t["upi_key"])
            if not r:
                continue
            r["generated"] += 1
            if t["status"] == "success":
                r["success"] += 1
                r["amount"] += t["amount"]
            elif t["status"] == "failed":
                r["failed"] += 1
            else:
                r["pending"] += 1
        return list(rep.values())
