import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters, ConversationHandler
)

from config import BOT_TOKEN, ADMIN_IDS
import storage
import core

# conversation states
ASK_PHONE, ASK_CODE, ASK_PASSWORD = range(3)


def admin_only(func):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        if ADMIN_IDS and uid not in ADMIN_IDS:
            await update.effective_message.reply_text("⛔️ شما دسترسی ندارید.")
            return
        return await func(update, ctx)
    return wrapper


def kb_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 وضعیت", callback_data="st"),
         InlineKeyboardButton("🔎 چکر", callback_data="check")],
        [InlineKeyboardButton("📨 سندر", callback_data="send"),
         InlineKeyboardButton("📢 فوروارد", callback_data="forward")],
        [InlineKeyboardButton("➕ جوینر", callback_data="join"),
         InlineKeyboardButton("🧾 لاگ‌ها", callback_data="logs")],
        [InlineKeyboardButton("🔑 ساخت سشن", callback_data="mk"),
         InlineKeyboardButton("📁 تعداد سشن", callback_data="cnt")],
    ])


@admin_only
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎛 *پنل مدیریت ربات*\nاز دکمه‌های زیر استفاده کنید:",
        reply_markup=kb_main(), parse_mode="Markdown"
    )


@admin_only
async def cb_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data

    if d == "st":
        s = core.state.as_dict()
        txt = (f"📊 وضعیت:\n"
               f"نوع: {s['kind'] or '-'}\n"
               f"در حال اجرا: {'بله' if s['running'] else 'خیر'}\n"
               f"پیشرفت: {s['progress']}/{s['total']}\n"
               f"موفق: {s['success']} | ناموفق: {s['failed']}\n"
               f"فعلی: {s['current'] or '-'}")
        await q.edit_message_text(txt, reply_markup=kb_main())
    elif d == "cnt":
        n = len(storage.load_sessions())
        await q.edit_message_text(f"📁 تعداد سشن‌ها: {n}", reply_markup=kb_main())
    elif d == "check":
        import runner
        runner.runner.submit(core.task_check_sessions())
        await q.edit_message_text("🔎 چکر در حال اجرا... برای مشاهده از «لاگ‌ها» استفاده کنید.",
                                  reply_markup=kb_main())
    elif d == "logs":
        logs, _ = storage.get_logs(0)
        tail = logs[-15:]
        txt = "\n".join(f"[{x['t'][-8:]}] {x['text']}" for x in tail) or "خالی"
        if len(txt) > 3500:
            txt = txt[-3500:]
        await q.edit_message_text(f"🧾 آخرین لاگ‌ها:\n```\n{txt}\n```",
                                  parse_mode="Markdown", reply_markup=kb_main())
    elif d == "send":
        await q.edit_message_text("✍️ متن پیام را ارسال کنید.\n(برای انصراف /cancel)")
        ctx.user_data["mode"] = "send"
    elif d == "forward":
        await q.edit_message_text("📢 فرمت: `channel_id message_id`\nمثال: `Spotifym 90`",
                                  parse_mode="Markdown")
        ctx.user_data["mode"] = "forward"
    elif d == "join":
        await q.edit_message_text("➕ لینکدونی‌ها را با کاما جدا کنید:\nمثال: `ch1,ch2,ch3`")
        ctx.user_data["mode"] = "join"
    elif d == "mk":
        await q.edit_message_text("📱 شماره موبایل با کد کشور:")
        ctx.user_data["mode"] = "mk_phone"


@admin_only
async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    mode = ctx.user_data.get("mode")
    text = (update.message.text or "").strip()
    import runner

    if text == "/cancel":
        ctx.user_data.clear()
        await update.message.reply_text("لغو شد.", reply_markup=kb_main())
        return

    if mode == "send":
        ctx.user_data.clear()
        runner.runner.submit(core.task_send_messages(text, "2", 2))
        await update.message.reply_text("📨 ارسال شروع شد. لاگ‌ها را ببینید.", reply_markup=kb_main())
    elif mode == "forward":
        parts = text.split()
        if len(parts) != 2 or not parts[1].isdigit():
            await update.message.reply_text("❌ فرمت اشتباه. مثال: `Spotifym 90`", parse_mode="Markdown")
            return
        ctx.user_data.clear()
        runner.runner.submit(core.task_forward(parts[0], int(parts[1]), "2", 1.0))
        await update.message.reply_text("📢 فوروارد شروع شد.", reply_markup=kb_main())
    elif mode == "join":
        donors = [x.strip() for x in text.split(",") if x.strip()]
        ctx.user_data.clear()
        runner.runner.submit(core.task_join(donors, 2.0, 50))
        await update.message.reply_text("➕ جوینر شروع شد.", reply_markup=kb_main())
    else:
        # ممکن است کاربر رشته سشن بفرستد
        if len(text) > 100:
            added, total = storage.add_sessions([text])
            await update.message.reply_text(f"✅ {added} سشن اضافه شد. مجموع: {total}",
                                            reply_markup=kb_main())
        else:
            await update.message.reply_text("❓ دستور نامشخص.", reply_markup=kb_main())


# ---------- session maker flow ----------
@admin_only
async def mk_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["mode"] = None
    ctx.user_data["mk_phone"] = update.message.text.strip()
    await update.message.reply_text("📨 کد تایید را وارد کنید.")
    ctx.user_data["mode"] = "mk_code"


@admin_only
async def mk_code_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    mode = ctx.user_data.get("mode")
    if mode != "mk_code":
        return
    phone = ctx.user_data.get("mk_phone")
    code = update.message.text.strip()

    from splusthon import SoroushClient
    from splusthon.sessions import StringSession

    try:
        client = SoroushClient(StringSession())
        await client.connect()
        sent = await client.send_code_request(phone)
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=sent.phone_code_hash)
        except Exception as e:
            if "password" in str(e).lower() or "2fa" in str(e).lower():
                ctx.user_data["mk_client"] = client
                ctx.user_data["mode"] = "mk_pass"
                await update.message.reply_text("🔐 رمز دو مرحله‌ای را وارد کنید.")
                return
            raise
        session_str = client.session.save()
        await client.disconnect()
        storage.add_sessions([session_str])
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ سشن ساخته و ذخیره شد:\n`{session_str[:80]}...`",
                                        parse_mode="Markdown", reply_markup=kb_main())
    except Exception as e:
        ctx.user_data.clear()
        await update.message.reply_text(f"❌ خطا: {e}", reply_markup=kb_main())


async def build_and_run():
    if not BOT_TOKEN:
        print("[bot] BOT_TOKEN تنظیم نشده، ربات اجرا نمی‌شود.")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    # order matters: text handler only AFTER start command
    # We'll manually route based on user_data
    async def router(update, ctx):
        mode = ctx.user_data.get("mode")
        if mode == "mk_phone":
            return await mk_phone(update, ctx)
        if mode == "mk_code":
            return await mk_code_handler(update, ctx)
        if mode == "mk_pass":
            return await mk_pass_handler(update, ctx)
        return await on_text(update, ctx)

    @admin_only
    async def mk_pass_handler(update, ctx):
        client = ctx.user_data.get("mk_client")
        try:
            await client.sign_in(password=update.message.text.strip())
            session_str = client.session.save()
            await client.disconnect()
            storage.add_sessions([session_str])
            ctx.user_data.clear()
            await update.message.reply_text(f"✅ سشن با 2FA ذخیره شد.",
                                            reply_markup=kb_main())
        except Exception as e:
            ctx.user_data.clear()
            await update.message.reply_text(f"❌ خطا: {e}", reply_markup=kb_main())

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(cb_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, router))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    print("[bot] شروع به کار کرد.")
    # keep alive forever
    await asyncio.Event().wait()
