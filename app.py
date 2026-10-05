import asyncio
import json
import functools

from flask import (Flask, render_template, request, jsonify,
                   session as fs, redirect, url_for)

from config import PANEL_PASSWORD, SECRET_KEY, PORT, HOST, BOT_TOKEN
import storage
import core
import runner
import bot

app = Flask(__name__)
app.secret_key = SECRET_KEY


def login_required(f):
    @functools.wraps(f)
    def wrapper(*a, **kw):
        if not fs.get("auth"):
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "msg": "unauthorized"}), 401
            return redirect(url_for("login"))
        return f(*a, **kw)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == PANEL_PASSWORD:
            fs["auth"] = True
            return redirect(url_for("index"))
        return render_template("login.html", error="رمز اشتباه است")
    return render_template("login.html")


@app.route("/logout")
def logout():
    fs.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    return render_template("index.html")


# ---------- API ----------
@app.route("/api/state")
@login_required
def api_state():
    return jsonify({
        "task": core.state.as_dict(),
        "sessions_count": len(storage.load_sessions()),
        "healthy_count": len(storage.load_healthy()),
    })


@app.route("/api/logs")
@login_required
def api_logs():
    since = int(request.args.get("since", 0))
    items, total = storage.get_logs(since)
    return jsonify({"items": items, "total": total})


@app.route("/api/logs/clear", methods=["POST"])
@login_required
def api_logs_clear():
    storage.clear_logs()
    return jsonify({"ok": True})


@app.route("/api/sessions", methods=["GET"])
@login_required
def api_sessions_list():
    sessions = storage.load_sessions()
    out = []
    for i, s in enumerate(sessions):
        out.append({"index": i, "preview": (s[:60] + "...") if len(s) > 60 else s,
                    "length": len(s)})
    return jsonify({"count": len(sessions), "items": out})


@app.route("/api/sessions", methods=["POST"])
@login_required
def api_sessions_add():
    data = request.get_json(force=True)
    raw = (data.get("text") or "").strip()
    if not raw:
        return jsonify({"ok": False, "msg": "empty"})

    new = []
    # Try JSON array
    if raw.startswith("["):
        try:
            arr = json.loads(raw)
            for it in arr:
                if isinstance(it, str):
                    new.append(it)
                elif isinstance(it, dict) and "session" in it:
                    new.append(it["session"])
        except Exception:
            pass
    if not new:
        for line in raw.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                new.append(line)

    added, total = storage.add_sessions(new)
    return jsonify({"ok": True, "added": added, "total": total})


@app.route("/api/sessions", methods=["DELETE"])
@login_required
def api_sessions_delete():
    data = request.get_json(force=True)
    indices = data.get("indices") or []
    n = storage.delete_sessions(indices)
    return jsonify({"ok": True, "removed": n})


@app.route("/api/sessions/clear", methods=["POST"])
@login_required
def api_sessions_clear():
    storage.clear_sessions()
    return jsonify({"ok": True})


@app.route("/api/task/check", methods=["POST"])
@login_required
def api_task_check():
    if core.state.running:
        return jsonify({"ok": False, "msg": "یک تسک دیگر در حال اجراست"})
    runner.runner.submit(core.task_check_sessions())
    return jsonify({"ok": True})


@app.route("/api/task/send", methods=["POST"])
@login_required
def api_task_send():
    if core.state.running:
        return jsonify({"ok": False, "msg": "یک تسک دیگر در حال اجراست"})
    d = request.get_json(force=True)
    msg = (d.get("message") or "").strip()
    if not msg:
        return jsonify({"ok": False, "msg": "پیام خالی است"})
    delete_mode = d.get("delete_mode", "2")
    delay = float(d.get("delay", 2))
    runner.runner.submit(core.task_send_messages(msg, delete_mode, delay))
    return jsonify({"ok": True})


@app.route("/api/task/forward", methods=["POST"])
@login_required
def api_task_forward():
    if core.state.running:
        return jsonify({"ok": False, "msg": "یک تسک دیگر در حال اجراست"})
    d = request.get_json(force=True)
    ch = (d.get("channel") or "").strip()
    mid = d.get("message_id")
    if not ch or not str(mid).isdigit():
        return jsonify({"ok": False, "msg": "ورودی نامعتبر"})
    delete_mode = d.get("delete_mode", "2")
    delay = float(d.get("delay", 1))
    runner.runner.submit(core.task_forward(ch, int(mid), delete_mode, delay))
    return jsonify({"ok": True})


@app.route("/api/task/join", methods=["POST"])
@login_required
def api_task_join():
    if core.state.running:
        return jsonify({"ok": False, "msg": "یک تسک دیگر در حال اجراست"})
    d = request.get_json(force=True)
    donors_raw = d.get("donors") or ""
    donors = [x.strip() for x in donors_raw.replace("\n", ",").split(",") if x.strip()]
    if not donors:
        return jsonify({"ok": False, "msg": "لینکدونی خالی است"})
    delay = float(d.get("delay", 2))
    limit = int(d.get("scrape_limit", 50))
    runner.runner.submit(core.task_join(donors, delay, limit))
    return jsonify({"ok": True})


@app.route("/api/task/stop", methods=["POST"])
@login_required
def api_task_stop():
    ok = core.stop_current_task()
    return jsonify({"ok": ok})


# ---------- BOOTSTRAP ----------
def bootstrap():
    runner.runner.start()
    if BOT_TOKEN:
        runner.runner.submit(bot.build_and_run())
    else:
        print("[app] BOT_TOKEN تنظیم نشده.")


bootstrap()


if __name__ == "__main__":
    print(f"[app] Running on {HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=False, threaded=True)
