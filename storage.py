import json
import threading
from datetime import datetime
from config import SESSIONS_FILE, HEALTHY_FILE

_lock = threading.RLock()
_logs = []
_logs_lock = threading.Lock()
MAX_LOGS = 800


def _norm(item):
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict) and isinstance(item.get("session"), str):
        return item["session"].strip()
    return None


def load_sessions():
    with _lock:
        if not SESSIONS_FILE.exists():
            return []
        try:
            data = json.loads(SESSIONS_FILE.read_text(encoding="utf-8"))
        except Exception:
            try:
                return [l.strip() for l in SESSIONS_FILE.read_text(encoding="utf-8").splitlines()
                        if l.strip() and not l.startswith("#")]
            except Exception:
                return []
        if isinstance(data, list):
            out = []
            for it in data:
                s = _norm(it)
                if s and s not in out:
                    out.append(s)
            return out
        return []


def save_sessions(sessions):
    with _lock:
        SESSIONS_FILE.write_text(
            json.dumps(list(dict.fromkeys(sessions)), ensure_ascii=False, indent=2),
            encoding="utf-8")


def add_sessions(new_sessions):
    with _lock:
        cur = load_sessions()
        seen = set(cur)
        added = 0
        for s in new_sessions:
            s = (s or "").strip()
            if s and s not in seen:
                cur.append(s)
                seen.add(s)
                added += 1
        SESSIONS_FILE.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
        return added, len(cur)


def delete_sessions(indices):
    with _lock:
        cur = load_sessions()
        idx = set(indices)
        new = [s for i, s in enumerate(cur) if i not in idx]
        SESSIONS_FILE.write_text(json.dumps(new, ensure_ascii=False, indent=2), encoding="utf-8")
        return len(cur) - len(new)


def clear_sessions():
    with _lock:
        SESSIONS_FILE.write_text("[]", encoding="utf-8")


def save_healthy(items):
    HEALTHY_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def load_healthy():
    if not HEALTHY_FILE.exists():
        return []
    try:
        return json.loads(HEALTHY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def push_log(text, level="info"):
    entry = {"t": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             "level": level, "text": str(text)}
    with _logs_lock:
        _logs.append(entry)
        if len(_logs) > MAX_LOGS:
            del _logs[:len(_logs) - MAX_LOGS]
    return entry


def get_logs(since=0):
    with _logs_lock:
        return _logs[since:], len(_logs)


def clear_logs():
    with _logs_lock:
        _logs.clear()
