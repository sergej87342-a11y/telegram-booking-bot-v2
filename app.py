import json
import os
import re
from filelock import FileLock

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests


HERE = os.path.dirname(os.path.abspath(__file__))
SLOTS_PATH = os.path.join(HERE, "slots.json")
BOOKINGS_PATH = os.path.join(HERE, "bookings.json")
_SLOTS_LOCK = FileLock(SLOTS_PATH + ".lock")
_BOOKINGS_LOCK = FileLock(BOOKINGS_PATH + ".lock")

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, ngrok-skip-browser-warning"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


# ===== helpers =====
_PHONE_RE = re.compile(r"^[\d\s\+\-\(\)]{7,20}$")


def _is_valid_phone(text):
    return bool(_PHONE_RE.match(text or ""))


def _norm(value):
    return str(value or "").strip().lower()


def _load_json_list(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("slots", "bookings", "items", "data"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def _save_json_list(path, items):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_slots():
    return _load_json_list(SLOTS_PATH)


def save_slots(items):
    with _SLOTS_LOCK:
        _save_json_list(SLOTS_PATH, items)


def load_bookings():
    return _load_json_list(BOOKINGS_PATH)


def save_bookings(items):
    with _BOOKINGS_LOCK:
        _save_json_list(BOOKINGS_PATH, items)


# ===== Telegram =====
def notify_admin(text):
    if not BOT_TOKEN or not ADMIN_CHAT_ID:
        print("⚠ BOT_TOKEN или ADMIN_CHAT_ID не задан", flush=True)
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(
            url,
            json={"chat_id": ADMIN_CHAT_ID, "text": text},
            timeout=10,
        )
        return r.ok
    except Exception as e:
        print(f"notify error: {e}", flush=True)
        return False


# ===== ROUTES =====

# 👉 ГЛАВНАЯ СТРАНИЦА (сайт)
@app.route("/", methods=["GET"])
def index():
    return send_from_directory(HERE, "index.html")


# 👉 API информация
@app.route("/api", methods=["GET"])
def api_info():
    return jsonify({
        "name": "TelegramBot Booking API",
        "endpoints": {
            "GET /slots": "вернуть свободные слоты",
            "POST /booking": "создать запись"
        }
    })


# 👉 слоты
@app.route("/slots", methods=["GET"])
def get_slots():
    slots = load_slots()
    return jsonify([s for s in slots if s.get("status") == "free"])


# 👉 запись
@app.route("/booking", methods=["POST"])
def post_booking():
    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip()
    service = (data.get("service") or "").strip()
    date = (data.get("date") or "").strip()
    time = (data.get("time") or "").strip()

    if not all([name, phone, service, date, time]):
        return jsonify({"ok": False, "error": "Заполни все поля"}), 400

    if not _is_valid_phone(phone):
        return jsonify({"ok": False, "error": "Телефон неверный"}), 400

    slots = load_slots()
    target = None

    for s in slots:
        if (_norm(s.get("date")) == _norm(date)
            and _norm(s.get("time")) == _norm(time)
            and _norm(s.get("service")) == _norm(service)
            and s.get("status") == "free"):
            target = s
            break

    if not target:
        return jsonify({"ok": False, "error": "Слот занят"}), 409

    # бронируем
    target["status"] = "booked"
    save_slots(slots)

    bookings = load_bookings()
    bookings.append({
        "client_name": name,
        "service": service,
        "date": date,
        "time": time,
        "phone": phone,
        "source": "web"
    })
    save_bookings(bookings)

    notify_admin(f"Новая запись:\n{name} {phone}\n{service} {date} {time}")

    return jsonify({"ok": True})


# ===== RUN =====
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))

    print("API STARTING", flush=True)
    print(f"PORT: {port}", flush=True)

    app.run(host="0.0.0.0", port=port)