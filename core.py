import asyncio
import re
import warnings

warnings.filterwarnings("ignore")

import logging
logging.basicConfig(level=logging.CRITICAL)
for n in ["splusthon", "aiohttp", "asyncio", "telegram"]:
    logging.getLogger(n).setLevel(logging.CRITICAL)

from splusthon import SoroushClient
from splusthon.sessions import StringSession
from splusthon.tl.functions.messages import ImportChatInviteRequest

import storage


class TaskState:
    def __init__(self):
        self.running = False
        self.stop_flag = False
        self.progress = 0
        self.total = 0
        self.success = 0
        self.failed = 0
        self.current = ""
        self.kind = ""

    def reset(self, kind, total):
        self.running = True
        self.stop_flag = False
        self.progress = 0
        self.total = total
        self.success = 0
        self.failed = 0
        self.current = ""
        self.kind = kind

    def as_dict(self):
        return {
            "running": self.running, "progress": self.progress, "total": self.total,
            "success": self.success, "failed": self.failed,
            "current": self.current, "kind": self.kind,
        }


state = TaskState()


def log(t, level="info"):
    storage.push_log(t, level)


def stop_current_task():
    if state.running:
        state.stop_flag = True
        log("⏹ درخواست توقف ثبت شد...", "warn")
        return True
    return False


# ----------------- SESSION MAKER -----------------
async def make_session(phone, code=None, phone_code_hash=None, password=None, client=None):
    """در حالت‌های مختلف فراخوانی می‌شود. اگر client داده شود ادامه می‌دهیم."""
    raise NotImplementedError("Session maker از طریق ربات انجام می‌شود.")


# ----------------- CHECKER -----------------
async def _check_one(session_str, timeout=10):
    client = SoroushClient(StringSession(session_str),
                           connection_retries=1, retry_delay=1, timeout=timeout)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return None
        me = await client.get_me()
        return {
            "session": session_str,
            "id": getattr(me, "id", None),
            "first_name": getattr(me, "first_name", "") or "",
            "last_name": getattr(me, "last_name", "") or "",
            "username": getattr(me, "username", "") or None,
            "phone": getattr(me, "phone", "") or None,
        }
    except Exception:
        return None
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
        await asyncio.sleep(0.05)


async def task_check_sessions():
    sessions = storage.load_sessions()
    if not sessions:
        log("هیچ سشنی برای بررسی وجود ندارد.", "warn")
        return {"ok": False, "msg": "no sessions"}
    state.reset("check", len(sessions))
    log(f"🔎 شروع بررسی {len(sessions)} سشن...")
    healthy = []
    try:
        for i, s in enumerate(sessions, 1):
            if state.stop_flag:
                break
            state.current = f"اکانت {i}/{len(sessions)}"
            info = await _check_one(s)
            if info:
                healthy.append(info)
                state.success += 1
                full = f"{info['first_name']} {info['last_name']}".strip() or "بدون نام"
                log(f"✅ [{i}/{len(sessions)}] {full} | ID: {info['id']}", "success")
            else:
                state.failed += 1
                log(f"❌ [{i}/{len(sessions)}] نامعتبر/منقضی", "error")
            state.progress = i
        storage.save_healthy(healthy)
        log(f"پایان بررسی | سالم: {state.success} | خراب: {state.failed}", "success")
        return {"ok": True, "healthy": len(healthy), "failed": state.failed}
    finally:
        state.running = False
        state.current = ""


# ----------------- SENDER -----------------
async def _send_with_account(session_str, message, delete_mode, delay):
    client = SoroushClient(StringSession(session_str),
                           connection_retries=1, retry_delay=1, timeout=10)
    sent_count = 0
    try:
        await client.connect()
        if not await client.is_user_authorized():
            log("سشن نامعتبر", "error")
            return 0, False
        me = await client.get_me()
        log(f"👤 متصل شد: {getattr(me, 'first_name', 'کاربر')}")
        dialogs = await client.get_dialogs()
        log(f"🔍 {len(dialogs)} گفتگو یافت شد")
        for d in dialogs:
            if state.stop_flag:
                break
            title = getattr(d, "title", None) or getattr(d, "name", None) or "گفتگو"
            try:
                msg = await client.send_message(d.id, message)
                sent_count += 1
                if delete_mode == "1":
                    await client.delete_messages(d.id, [msg.id], revoke=False)
                await asyncio.sleep(delay)
            except Exception as e:
                log(f"⚠️ خطا در ارسال به {title}: {e}", "error")
                await asyncio.sleep(1)
        return sent_count, True
    except Exception as e:
        log(f"❌ خطای اکانت: {e}", "error")
        return sent_count, False
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
        await asyncio.sleep(0.05)


async def task_send_messages(message, delete_mode="2", delay=2.0):
    sessions = storage.load_sessions()
    if not sessions:
        log("هیچ سشنی برای ارسال وجود ندارد.", "warn")
        return {"ok": False, "msg": "no sessions"}
    state.reset("send", len(sessions))
    log(f"🚀 شروع ارسال پیام به {len(sessions)} اکانت...")
    total_sent = 0
    try:
        for i, s in enumerate(sessions, 1):
            if state.stop_flag:
                break
            state.current = f"اکانت {i}/{len(sessions)}"
            sent, ok = await _send_with_account(s, message, delete_mode, delay)
            total_sent += sent
            if ok:
                state.success += 1
            else:
                state.failed += 1
            state.progress = i
            if i < len(sessions):
                await asyncio.sleep(2)
        log(f"پایان ارسال | مجموع پیام‌های موفق: {total_sent}", "success")
        return {"ok": True, "sent": total_sent, "accounts": len(sessions)}
    finally:
        state.running = False
        state.current = ""


# ----------------- FORWARDER -----------------
async def _forward_with_account(session_str, channel_id, message_id, delete_mode, delay):
    client = SoroushClient(StringSession(session_str))
    count = 0
    try:
        await client.connect()
        me = await client.get_me()
        log(f"✅ متصل شد: {getattr(me, 'first_name', 'کاربر')}", "success")
        dialogs = await client.get_dialogs()
        log(f"🔍 {len(dialogs)} گفتگو یافت شد...")
        for d in dialogs:
            if state.stop_flag:
                break
            title = getattr(d, "title", None) or getattr(d, "name", None) or "چت"
            try:
                sent = await client.forward_messages(entity=d.id, messages=message_id, from_peer=channel_id)
                count += 1
                log(f"🚀 به '{title}' فوروارد شد.", "success")
                if delete_mode == "1":
                    try:
                        msg_id = sent.id if hasattr(sent, "id") else sent[0].id
                        await client.delete_messages(d.id, [msg_id], revoke=False)
                        log("   🗑️ حذف شد.", "warn")
                    except Exception:
                        pass
                await asyncio.sleep(delay)
            except Exception as e:
                log(f"⚠️ خطا به {title}: {e}", "error")
        return count, True
    except Exception as e:
        log(f"❌ خطای اکانت: {e}", "error")
        return count, False
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
        await asyncio.sleep(0.05)


async def task_forward(channel_id, message_id, delete_mode="2", delay=1.0):
    sessions = storage.load_sessions()
    if not sessions:
        log("هیچ سشنی وجود ندارد.", "warn")
        return {"ok": False, "msg": "no sessions"}
    state.reset("forward", len(sessions))
    log(f"📢 شروع فوروارد از {channel_id} / پیام {message_id} با {len(sessions)} اکانت...")
    total = 0
    try:
        for i, s in enumerate(sessions, 1):
            if state.stop_flag:
                break
            state.current = f"اکانت {i}/{len(sessions)}"
            c, ok = await _forward_with_account(s, channel_id, message_id, delete_mode, delay)
            total += c
            if ok:
                state.success += 1
            else:
                state.failed += 1
            state.progress = i
            if i < len(sessions):
                await asyncio.sleep(2)
        log(f"پایان فوروارد | مجموع: {total}", "success")
        return {"ok": True, "forwarded": total}
    finally:
        state.running = False
        state.current = ""


# ----------------- JOINER -----------------
async def _scrape_links(client, channels, limit=50):
    hashes = []
    for ch in channels:
        ch = ch.strip()
        if not ch:
            continue
        log(f"🔍 اسکن لینکدونی: {ch}")
        try:
            messages = await client.get_messages(ch, limit=limit)
            cnt = 0
            for m in messages:
                if getattr(m, "text", None):
                    found = re.findall(r"splus\.ir/(?:join|joingroup)/\+?([A-Za-z0-9_-]+)", m.text)
                    hashes.extend(found)
                    cnt += len(found)
            log(f"   ↳ {cnt} لینک از {ch}", "success")
        except Exception as e:
            log(f"   ❌ خطا در {ch}: {e}", "error")
    return list(dict.fromkeys(hashes))


async def _join_hash(client, link_hash):
    if hasattr(client, "join_chat"):
        try:
            return await client.join_chat(f"https://splus.ir/join/{link_hash}")
        except Exception:
            pass
    return await client(ImportChatInviteRequest(hash=link_hash))


async def _join_with_account(session_str, hashes, delay, join_timeout=8):
    client = SoroushClient(StringSession(session_str))
    success = 0
    valid = False
    try:
        await asyncio.wait_for(client.connect(), timeout=12)
        if not await client.is_user_authorized():
            log("❌ سشن نامعتبر", "error")
            return False, 0
        valid = True
        me = await client.get_me()
        title = f"{getattr(me, 'first_name', '')} {getattr(me, 'last_name', '')}".strip() or str(me.id)
        log(f"✔ وارد شد: {title}", "success")
        for idx, h in enumerate(hashes, 1):
            if state.stop_flag:
                break
            try:
                await asyncio.wait_for(_join_hash(client, h), timeout=join_timeout)
                success += 1
                log(f"   [{idx}/{len(hashes)}] ✅ جوین شد: {h}", "success")
            except asyncio.TimeoutError:
                log(f"   [{idx}/{len(hashes)}] ⚠️ timeout: {h}", "warn")
            except Exception as ex:
                log(f"   [{idx}/{len(hashes)}] ⚠️ ناموفق {h}: {ex}", "warn")
            if idx < len(hashes) and delay > 0:
                await asyncio.sleep(delay)
        return valid, success
    except Exception as e:
        log(f"❌ خطای اکانت: {e}", "error")
        return valid, success
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def task_join(link_donors, delay=2.0, scrape_limit=50):
    sessions = storage.load_sessions()
    if not sessions:
        log("هیچ سشنی وجود ندارد.", "warn")
        return {"ok": False, "msg": "no sessions"}
    if not link_donors:
        log("هیچ لینکدونی وارد نشده.", "error")
        return {"ok": False, "msg": "no donors"}

    state.reset("join", len(sessions))
    log("🔎 در حال استخراج لینک‌ها با سشن اول...")
    first = SoroushClient(StringSession(sessions[0]))
    hashes = []
    try:
        await first.connect()
        if await first.is_user_authorized():
            hashes = await _scrape_links(first, link_donors, limit=scrape_limit)
        else:
            log("سشن اول نامعتبر است.", "error")
            state.running = False
            return {"ok": False, "msg": "first session invalid"}
    except Exception as e:
        log(f"خطای اسکن: {e}", "error")
        state.running = False
        return {"ok": False, "msg": str(e)}
    finally:
        try:
            await first.disconnect()
        except Exception:
            pass

    if not hashes:
        log("هیچ لینکی یافت نشد.", "warn")
        state.running = False
        return {"ok": False, "msg": "no links"}

    log(f"🎯 {len(hashes)} لینک استخراج شد. شروع پردازش اکانت‌ها...")
    total_joins = 0
    healthy = []
    try:
        for i, s in enumerate(sessions, 1):
            if state.stop_flag:
                break
            state.current = f"اکانت {i}/{len(sessions)}"
            ok, cnt = await _join_with_account(s, hashes, delay)
            total_joins += cnt
            if ok:
                healthy.append(s)
                state.success += 1
            else:
                state.failed += 1
            state.progress = i
        storage.save_healthy(healthy)
        log(f"پایان جوین | مجموع: {total_joins} | سالم: {len(healthy)}", "success")
        return {"ok": True, "joins": total_joins, "healthy": len(healthy)}
    finally:
        state.running = False
        state.current = ""
