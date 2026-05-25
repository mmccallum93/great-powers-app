"""
Great Powers Game — Vercel cloud entry point.

  /          — public leaderboard + country purchase tabs (templates/index.html)
  /teacher   — teacher control panel (templates/teacher.html)
  /api/*     — JSON API

Game state lives in Vercel Blob as game/state.json.
"""

import os
import json
import copy
from pathlib import Path
from flask import Flask, render_template, jsonify, request
from werkzeug.security import generate_password_hash, check_password_hash
import requests

BASE_DIR = Path(__file__).resolve().parent.parent

app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))


# ─────────────────────────────────────────────
# Security headers
# ─────────────────────────────────────────────

_SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options":    "nosniff",
    "X-Frame-Options":           "DENY",
    "Referrer-Policy":           "strict-origin-when-cross-origin",
    "Permissions-Policy":        "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    ),
}


@app.after_request
def _apply_security_headers(response):
    for key, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(key, value)
    return response


# ─────────────────────────────────────────────
# Blob storage  (direct HTTP — no SDK)
# Token format: vercel_blob_rw_{storeId}_{rest}
# ─────────────────────────────────────────────

_BLOB_API = "https://vercel.com/api/blob"


def _blob_token():
    return os.environ.get("BLOB_READ_WRITE_TOKEN", "")


def _blob_headers(extra=None):
    h = {"authorization": f"Bearer {_blob_token()}", "x-api-version": "11"}
    if extra:
        h.update(extra)
    return h


def _store_id():
    tok = _blob_token()
    parts = tok.split("_")
    return parts[3] if len(parts) > 3 else ""


def _blob_read(pathname):
    store = _store_id()
    if not store:
        return None
    url = f"https://{store}.private.blob.vercel-storage.com/{pathname}"
    r = requests.get(url, headers={"authorization": f"Bearer {_blob_token()}"}, timeout=15)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def _blob_write(pathname, data):
    body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    r = requests.put(
        _BLOB_API,
        params={"pathname": pathname},
        data=body,
        headers=_blob_headers({
            "x-vercel-blob-access": "private",
            "x-content-type":       "application/json",
            "x-allow-overwrite":    "1",
            "x-add-random-suffix":  "0",
        }),
        timeout=15,
    )
    if not r.ok:
        raise RuntimeError(f"Blob write failed ({r.status_code}): {r.text}")


# ─────────────────────────────────────────────
# Game state
# ─────────────────────────────────────────────

_STATE_PATH = "game/state.json"

_DEFAULT_COUNTRIES = [
    {"id": "russia",  "name": "Russia",         "color": "#b03a2e"},
    {"id": "germany", "name": "Germany",         "color": "#1a5276"},
    {"id": "austria", "name": "Austria-Hungary", "color": "#d4ac0d"},
    {"id": "britain", "name": "Britain",         "color": "#6c3483"},
    {"id": "ottoman", "name": "Ottomans",        "color": "#148f77"},
    {"id": "usa",     "name": "USA",             "color": "#2e86c1"},
    {"id": "italy",   "name": "Italy",           "color": "#1e8449"},
    {"id": "france",  "name": "France",          "color": "#e67e22"},
    {"id": "japan",   "name": "Japan",           "color": "#cb4335"},
]


def _empty_country(cid, name, color):
    return {
        "id": cid, "name": name, "color": color,
        "army": 2, "navy": 1, "industry": 2, "colonies": 2,
        "password_hash": "",
        "purchases_submitted": False,
        "pending_purchase": None,
    }


def load_state():
    state = _blob_read(_STATE_PATH)
    if state is None:
        return {
            "initialized": False,
            "year": 1900,
            "phase": "purchase",
            "teacher_password_hash": "",
            "countries": [_empty_country(c["id"], c["name"], c["color"]) for c in _DEFAULT_COUNTRIES],
            "pending_wars": [],
        }
    return state


def save_state(state):
    _blob_write(_STATE_PATH, state)


def _econ_points(c):
    return c["industry"] + c["colonies"]


def _military_power(c):
    return c["army"] + c["navy"] / 2


def _victory_points(c):
    return _econ_points(c) + _military_power(c)


def _public_state(state):
    s = copy.deepcopy(state)
    s.pop("teacher_password_hash", None)
    for c in s.get("countries", []):
        c.pop("password_hash", None)
        c.pop("pending_purchase", None)
        c["econ_points"]     = _econ_points(c)
        c["military_power"]  = _military_power(c)
        c["victory_points"]  = _victory_points(c)
    return s


def _check_teacher_pw(state, pw):
    h = state.get("teacher_password_hash", "")
    return bool(h) and check_password_hash(h, pw)


def _check_country_pw(country, pw):
    h = country.get("password_hash", "")
    return bool(h) and check_password_hash(h, pw)


# ─────────────────────────────────────────────
# Routes — pages
# ─────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/teacher")
def teacher():
    return render_template("teacher.html")


# ─────────────────────────────────────────────
# Routes — public API
# ─────────────────────────────────────────────

@app.route("/api/state")
def api_state():
    state = load_state()
    return jsonify(_public_state(state))


@app.route("/api/auth/country", methods=["POST"])
def api_auth_country():
    data = request.json or {}
    state = load_state()
    country = next((c for c in state["countries"] if c["id"] == data.get("country_id")), None)
    if not country:
        return jsonify({"ok": False, "error": "Country not found"}), 404
    if not country.get("password_hash"):
        return jsonify({"ok": False, "error": "Game not set up yet"})
    if check_password_hash(country["password_hash"], data.get("password", "")):
        return jsonify({"ok": True, "name": country["name"]})
    return jsonify({"ok": False, "error": "Wrong password"})


@app.route("/api/auth/teacher", methods=["POST"])
def api_auth_teacher():
    data = request.json or {}
    state = load_state()
    if not state.get("teacher_password_hash"):
        return jsonify({"ok": False, "error": "Game not set up yet"})
    if check_password_hash(state["teacher_password_hash"], data.get("password", "")):
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Wrong password"})


@app.route("/api/purchase", methods=["POST"])
def api_purchase():
    data = request.json or {}
    state = load_state()
    country = next((c for c in state["countries"] if c["id"] == data.get("country_id")), None)
    if not country:
        return jsonify({"error": "Country not found"}), 404
    if not _check_country_pw(country, data.get("password", "")):
        return jsonify({"error": "Wrong password"}), 403
    if country.get("purchases_submitted"):
        return jsonify({"error": "Already submitted this turn"}), 400

    army     = max(0, int(data.get("army", 0)))
    navy     = max(0, int(data.get("navy", 0)))
    industry = max(0, int(data.get("industry", 0)))
    colonies = max(0, int(data.get("colonies", 0)))

    # Enforce industry cap
    industry = min(industry, max(0, 500 - country["industry"]))

    cost      = army + navy + (industry * 2) + colonies
    available = _econ_points(country)
    if cost > available:
        return jsonify({"error": f"Cost {cost} exceeds available economic points ({available})"}), 400

    country["pending_purchase"] = {
        "army": army, "navy": navy, "industry": industry, "colonies": colonies,
        "declare_war_on": data.get("declare_war_on", "").strip(),
    }
    country["purchases_submitted"] = True
    save_state(state)
    return jsonify({"ok": True})


# ─────────────────────────────────────────────
# Routes — teacher API
# ─────────────────────────────────────────────

@app.route("/api/teacher/state")
def api_teacher_state():
    pw = request.args.get("pw", "")
    state = load_state()
    if not _check_teacher_pw(state, pw):
        return jsonify({"error": "Wrong password"}), 403
    s = _public_state(state)
    for i, c in enumerate(s["countries"]):
        orig = state["countries"][i]
        c["purchases_submitted"] = orig.get("purchases_submitted", False)
        c["pending_purchase"]    = orig.get("pending_purchase")
    return jsonify(s)


@app.route("/api/teacher/setup", methods=["POST"])
def api_teacher_setup():
    data = request.json or {}
    state = load_state()

    existing_hash = state.get("teacher_password_hash", "")
    if existing_hash:
        if not check_password_hash(existing_hash, data.get("current_password", "")):
            return jsonify({"error": "Wrong current teacher password"}), 403

    new_pw = data.get("teacher_password", "")
    if not new_pw:
        return jsonify({"error": "Teacher password is required"}), 400

    countries_data = data.get("countries", [])
    if not (2 <= len(countries_data) <= 9):
        return jsonify({"error": "Must provide between 2 and 9 countries"}), 400

    new_state = {
        "initialized": True,
        "year": max(1, int(data.get("year", 1900))),
        "phase": "purchase",
        "teacher_password_hash": generate_password_hash(new_pw),
        "countries": [],
        "pending_wars": [],
    }

    for i, cd in enumerate(countries_data):
        pw = cd.get("password", "")
        new_state["countries"].append({
            "id":            _DEFAULT_COUNTRIES[i]["id"],
            "name":          cd.get("name", _DEFAULT_COUNTRIES[i]["name"]) or _DEFAULT_COUNTRIES[i]["name"],
            "color":         cd.get("color", _DEFAULT_COUNTRIES[i]["color"]) or _DEFAULT_COUNTRIES[i]["color"],
            "army":          max(0, int(cd.get("army", 2))),
            "navy":          max(0, int(cd.get("navy", 1))),
            "industry":      max(0, min(500, int(cd.get("industry", 2)))),
            "colonies":      max(0, int(cd.get("colonies", 2))),
            "password_hash": generate_password_hash(pw) if pw else "",
            "purchases_submitted": False,
            "pending_purchase":    None,
        })

    save_state(new_state)
    return jsonify({"ok": True})


@app.route("/api/teacher/advance-turn", methods=["POST"])
def api_teacher_advance_turn():
    data = request.json or {}
    state = load_state()
    if not _check_teacher_pw(state, data.get("teacher_password", "")):
        return jsonify({"error": "Wrong password"}), 403

    unsubmitted = [c["name"] for c in state["countries"] if not c.get("purchases_submitted")]
    if unsubmitted:
        return jsonify({"error": f"Waiting on: {', '.join(unsubmitted)}"}), 400

    wars_declared = []
    for country in state["countries"]:
        p = country.get("pending_purchase") or {}
        country["army"]     += p.get("army", 0)
        country["navy"]     += p.get("navy", 0)
        country["industry"]  = min(500, country["industry"] + p.get("industry", 0))
        country["colonies"] += p.get("colonies", 0)

        war_target = p.get("declare_war_on", "").strip()
        if war_target:
            wars_declared.append({
                "attacker": country["name"],
                "target":   war_target,
            })

        country["pending_purchase"]    = None
        country["purchases_submitted"] = False

    state["year"] += 1
    state["pending_wars"].extend(wars_declared)
    save_state(state)
    return jsonify({"ok": True, "year": state["year"], "wars_declared": wars_declared})


@app.route("/api/teacher/resolve-war", methods=["POST"])
def api_teacher_resolve_war():
    data = request.json or {}
    state = load_state()
    if not _check_teacher_pw(state, data.get("teacher_password", "")):
        return jsonify({"error": "Wrong password"}), 403

    side_a_ids = data.get("side_a", [])
    side_b_ids = data.get("side_b", [])
    die_rolls  = data.get("die_rolls", {})  # {country_id: 1-6}

    if not side_a_ids or not side_b_ids:
        return jsonify({"error": "Both sides must have at least one country"}), 400
    if not die_rolls:
        return jsonify({"error": "Die rolls are required"}), 400

    cmap = {c["id"]: c for c in state["countries"]}

    def side_power(ids):
        return sum(_military_power(cmap[cid]) for cid in ids if cid in cmap)

    a_power = side_power(side_a_ids)
    b_power = side_power(side_b_ids)

    if a_power >= b_power:
        winner_ids, loser_ids = side_a_ids, side_b_ids
        winner_side = "a"
    else:
        winner_ids, loser_ids = side_b_ids, side_a_ids
        winner_side = "b"

    WINNER_LOSS = {1: 0.50, 2: 0.40, 3: 0.30, 4: 0.20, 5: 0.10, 6: 0.00}
    LOSER_LOSS  = {1: 0.70, 2: 0.60, 3: 0.50, 4: 0.40, 5: 0.30, 6: 0.20}

    total_colonies_won = 0

    for cid in winner_ids:
        c = cmap.get(cid)
        if not c:
            continue
        roll     = max(1, min(6, int(die_rolls.get(cid, 3))))
        loss_pct = WINNER_LOSS[roll]
        c["army"] = max(0, c["army"] - int(c["army"] * loss_pct))
        c["navy"] = max(0, c["navy"] - int(c["navy"] * loss_pct))

    for cid in loser_ids:
        c = cmap.get(cid)
        if not c:
            continue
        roll      = max(1, min(6, int(die_rolls.get(cid, 3))))
        loss_pct  = LOSER_LOSS[roll]
        lost_cols = int(c["colonies"] * loss_pct)
        c["army"]     = max(0, c["army"]     - int(c["army"]     * loss_pct))
        c["navy"]     = max(0, c["navy"]     - int(c["navy"]     * loss_pct))
        c["colonies"] = max(0, c["colonies"] - lost_cols)
        total_colonies_won += lost_cols

    if winner_ids and total_colonies_won > 0:
        largest = max(winner_ids, key=lambda cid: _military_power(cmap[cid]) if cid in cmap else 0)
        if largest in cmap:
            cmap[largest]["colonies"] += total_colonies_won

    state["pending_wars"] = []
    save_state(state)

    return jsonify({
        "ok":                   True,
        "winner_side":          winner_side,
        "side_a_power":         a_power,
        "side_b_power":         b_power,
        "die_rolls":            die_rolls,
        "colonies_transferred": total_colonies_won,
    })


@app.route("/api/teacher/clear-wars", methods=["POST"])
def api_teacher_clear_wars():
    data = request.json or {}
    state = load_state()
    if not _check_teacher_pw(state, data.get("teacher_password", "")):
        return jsonify({"error": "Wrong password"}), 403
    state["pending_wars"] = []
    save_state(state)
    return jsonify({"ok": True})


@app.route("/api/teacher/reset", methods=["POST"])
def api_teacher_reset():
    data = request.json or {}
    state = load_state()
    if not _check_teacher_pw(state, data.get("teacher_password", "")):
        return jsonify({"error": "Wrong password"}), 403
    for c in state["countries"]:
        c["army"]     = 2
        c["navy"]     = 1
        c["industry"] = 2
        c["colonies"] = 2
        c["purchases_submitted"] = False
        c["pending_purchase"]    = None
    state["year"]         = 1900
    state["phase"]        = "purchase"
    state["pending_wars"] = []
    save_state(state)
    return jsonify({"ok": True})
