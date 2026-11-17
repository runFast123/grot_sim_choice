import os
import json
import base64
import datetime
import re
import threading
import html as html_lib
from urllib.parse import urlparse
import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

# Try importing the official choice_api / kkunal package
try:
    from choice_api import ChoiceClient, BASE_URL_OMNE, BASE_URL_FINX, ScripMaster
    HAS_CHOICE_PKG = True
except ImportError:
    HAS_CHOICE_PKG = False
    BASE_URL_OMNE = "https://finxomne.choiceindia.com"
    BASE_URL_FINX = "https://finx.choiceindia.com"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_FILE = "index.html"
app = Flask(__name__, static_folder=BASE_DIR)

# The front end is served from this same Flask app, so it never needs CORS.
# Opening CORS to every origin let any web page the user visited call this
# server through their browser and read the credentials it returned. Extra
# origins can be allowed explicitly with CORS_ORIGINS="https://a.example,...".
CORS_ORIGINS = [o.strip().rstrip("/") for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
if CORS_ORIGINS:
    CORS(app, origins=CORS_ORIGINS)

SESSION_FILE = os.path.join(BASE_DIR, ".choice_session.json")
SECRETS_FILE = os.path.join(BASE_DIR, "secrets.json")
DEFAULT_BASE_URL = BASE_URL_OMNE

# Credentials are only ever sent to Choice's own gateways. Accepting any
# caller-supplied base_url let a request redirect the stored VendorId and API
# key to a server of the caller's choosing.
ALLOWED_BASE_URLS = (BASE_URL_OMNE.rstrip("/"), BASE_URL_FINX.rstrip("/"))

def normalize_base_url(value):
    """Return value if it is a known Choice gateway, else the default gateway."""
    candidate = str(value or "").strip().rstrip("/")
    return candidate if candidate in ALLOWED_BASE_URLS else DEFAULT_BASE_URL

LOOPBACK_ADDRS = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}

def is_loopback_request():
    """True when the TCP peer is this machine (proxy headers are ignored on purpose)."""
    if os.environ.get("ALLOW_REMOTE_ADMIN", "").strip() == "1":
        return True
    return (request.remote_addr or "") in LOOPBACK_ADDRS

@app.before_request
def block_cross_site_writes():
    """
    Refuse state-changing requests that a browser sent on behalf of another
    site (CSRF). Closing CORS stops other sites reading responses, but a plain
    cross-site form POST could still trigger a login or overwrite the stored
    credentials without this check.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return None
    origin = request.headers.get("Origin", "").strip()
    if origin and origin != "null":
        if urlparse(origin).netloc == request.host or origin.rstrip("/") in CORS_ORIGINS:
            return None
        return jsonify({"status": "error", "message": "Cross-origin request refused"}), 403
    if origin == "null" or request.headers.get("Sec-Fetch-Site", "") == "cross-site":
        return jsonify({"status": "error", "message": "Cross-origin request refused"}), 403
    return None

# Only these files may be served by the static catch-all route. Everything else
# (server.py, secrets.json, .choice_session.json, *.log, ...) stays private.
PUBLIC_STATIC_EXTENSIONS = {".html", ".css", ".js", ".mjs", ".map", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".woff", ".woff2", ".ttf", ".csv"}
PRIVATE_STATIC_NAMES = {"secrets.json", "server.py", "requirements.txt", "vercel.json"}

# In-memory session store & client
scrip_master = None
choice_client = None
auth_state = {
    "logged_in": False,
    "vendor_id": os.environ.get("CHOICE_VENDOR_ID", ""),
    "api_key": os.environ.get("CHOICE_API_KEY", ""),
    "session_id": os.environ.get("CHOICE_SESSION_ID", ""),
    "access_token": os.environ.get("CHOICE_ACCESS_TOKEN", ""),
    "mobile_no": os.environ.get("CHOICE_MOBILE", ""),
    "base_url": os.environ.get("CHOICE_BASE_URL", BASE_URL_OMNE),
    "last_otp": "",
    "user_details": {}
}

# Popular presets for quick symbol selection
DEFAULT_SCRIPS = [
    {"symbol": "NIFTY 50", "name": "Nifty 50 Index", "segment_id": 1, "token": 26000, "exchange": "NSE-CM", "type": "INDEX", "lot": 1},
    {"symbol": "BANKNIFTY", "name": "Nifty Bank Index", "segment_id": 1, "token": 26009, "exchange": "NSE-CM", "type": "INDEX", "lot": 1},
    {"symbol": "FINNIFTY", "name": "Nifty Financial Services", "segment_id": 1, "token": 26037, "exchange": "NSE-CM", "type": "INDEX", "lot": 1},
    {"symbol": "MIDCPNIFTY", "name": "Nifty Midcap Select", "segment_id": 1, "token": 26074, "exchange": "NSE-CM", "type": "INDEX", "lot": 1},
    {"symbol": "SENSEX", "name": "BSE Sensex Index", "segment_id": 3, "token": 1, "exchange": "BSE-CM", "type": "INDEX", "lot": 1},
    {"symbol": "RELIANCE", "name": "Reliance Industries Ltd", "segment_id": 1, "token": 2885, "exchange": "NSE-CM", "type": "EQUITY", "lot": 1},
    {"symbol": "TCS", "name": "Tata Consultancy Services", "segment_id": 1, "token": 11536, "exchange": "NSE-CM", "type": "EQUITY", "lot": 1},
    {"symbol": "HDFCBANK", "name": "HDFC Bank Ltd", "segment_id": 1, "token": 1333, "exchange": "NSE-CM", "type": "EQUITY", "lot": 1},
    {"symbol": "ICICIBANK", "name": "ICICI Bank Ltd", "segment_id": 1, "token": 4963, "exchange": "NSE-CM", "type": "EQUITY", "lot": 1},
    {"symbol": "INFY", "name": "Infosys Ltd", "segment_id": 1, "token": 1594, "exchange": "NSE-CM", "type": "EQUITY", "lot": 1},
    {"symbol": "SBIN", "name": "State Bank of India", "segment_id": 1, "token": 3045, "exchange": "NSE-CM", "type": "EQUITY", "lot": 1},
    {"symbol": "TATAMOTORS", "name": "Tata Motors Ltd", "segment_id": 1, "token": 3456, "exchange": "NSE-CM", "type": "EQUITY", "lot": 1},
    {"symbol": "AXISBANK", "name": "Axis Bank Ltd", "segment_id": 1, "token": 5900, "exchange": "NSE-CM", "type": "EQUITY", "lot": 1},
    {"symbol": "KOTAKBANK", "name": "Kotak Mahindra Bank", "segment_id": 1, "token": 1922, "exchange": "NSE-CM", "type": "EQUITY", "lot": 1},
    {"symbol": "LT", "name": "Larsen & Toubro Ltd", "segment_id": 1, "token": 11483, "exchange": "NSE-CM", "type": "EQUITY", "lot": 1}
]
# MCX commodities (GOLD, SILVER, CRUDEOIL, ...) are not listed here: every
# futures expiry has its own token, so a fixed token goes stale within a month.
# /api/scrip/resolve picks the nearest live contract from the scrip master.

MCX_SEGMENT = "5"
MCX_FUTURES_SYMBOLS = {"GOLD", "GOLDM", "GOLDTEN", "GOLDPETAL", "GOLDGUINEA",
                       "SILVER", "SILVERM", "SILVERMIC", "SILVER100",
                       "CRUDEOIL", "CRUDEOILM", "NATURALGAS", "NATGASMINI", "COPPER", "ZINC"}
OPTION_INSTRUMENTS = {"OPTFUT", "OPTIDX", "OPTSTK", "OPTCUR", "OPTBLN"}
UNIT_IN_GRAMS = {"GRMS": 1.0, "GRAMS": 1.0, "GMS": 1.0, "KGS": 1000.0, "KG": 1000.0}

def parse_expiry(value):
    """Scrip master expiries look like '04DEC26'. Returns a date or None."""
    text = str(value or "").strip().upper()
    if not text:
        return None
    for fmt in ("%d%b%y", "%d%b%Y"):
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None

def _parse_unit(text):
    """'10  GRMS ' -> (10.0, 'GRMS'); 'KGS  ' -> (1.0, 'KGS')."""
    match = re.match(r"\s*([\d.]+)?\s*([A-Za-z]+)", str(text or ""))
    if not match:
        return None, ""
    return float(match.group(1) or 1), match.group(2).upper()

def contract_multiplier(row):
    """
    Rupees of P&L per one-rupee move for one lot. MCX quotes GOLD per 10 g but
    trades it in 1 kg lots, so one lot moves 100x the quoted price; SILVER is
    quoted per kg in 30 kg lots, so 30x. MarketLot alone (1 for GOLD) would
    understate gold P&L a hundredfold.
    """
    try:
        lot = float(row.get("MarketLot") or 1)
    except (TypeError, ValueError):
        lot = 1.0
    price_qty, price_unit = _parse_unit(row.get("PriceUnit"))
    _, qty_unit = _parse_unit(row.get("QtyUnit"))
    if not price_qty or not price_unit or not qty_unit:
        return max(1, int(round(lot)))
    if price_unit in UNIT_IN_GRAMS and qty_unit in UNIT_IN_GRAMS:
        mult = lot * UNIT_IN_GRAMS[qty_unit] / (price_qty * UNIT_IN_GRAMS[price_unit])
    elif price_unit == qty_unit:
        mult = lot / price_qty
    else:
        mult = lot
    return max(1, int(round(mult)))

def scrip_row_to_result(row):
    expiry = parse_expiry(row.get("Expiry"))
    instrument = str(row.get("Instrument") or "").strip()
    return {
        "symbol": str(row.get("Symbol") or "").strip(),
        "name": str(row.get("SecName") or row.get("SecDesc") or "").strip(),
        "segment_id": int(row.get("Segment") or 1),
        "token": int(row.get("Token")),
        "exchange": str(row.get("Exchange") or "").strip(),
        "type": instrument or str(row.get("Series") or "EQUITY").strip(),
        "expiry": expiry.isoformat() if expiry else "",
        "lot": contract_multiplier(row)
    }

def nearest_future(symbol, segment=MCX_SEGMENT, today=None, rows=None):
    """The live futures contract for symbol with the closest expiry, or None."""
    today = today or datetime.date.today()
    rows = rows if rows is not None else getattr(scrip_master, "all_rows", [])
    symbol = str(symbol or "").strip().upper()
    best, best_expiry = None, None
    for row in rows:
        if str(row.get("Segment", "")).strip() != segment:
            continue
        if str(row.get("Symbol", "")).strip().upper() != symbol:
            continue
        if not str(row.get("Instrument", "")).strip().upper().startswith("FUT"):
            continue
        expiry = parse_expiry(row.get("Expiry"))
        if not expiry or expiry < today:
            continue
        if best_expiry is None or expiry < best_expiry:
            best, best_expiry = row, expiry
    return best

def encode_mobile(mobile_no: str) -> str:
    return base64.b64encode(str(mobile_no).strip().encode('utf-8')).decode('utf-8')

def extract_credentials(req_data=None, req_obj=None):
    """
    Extracts Choice credentials from multiple sources:
    1. Request JSON payload
    2. Request HTTP headers (X-Vendor-Id, X-Api-Key, X-Session-Id, etc.)
    3. Environment variables (CHOICE_VENDOR_ID, CHOICE_API_KEY, etc.)
    4. In-memory auth_state & session file fallback
    """
    data = req_data or {}
    headers = req_obj.headers if req_obj else {}

    vendor_id = (
        data.get("vendor_id")
        or headers.get("X-Vendor-Id")
        or headers.get("VendorId")
        or os.environ.get("CHOICE_VENDOR_ID", "")
        or auth_state.get("vendor_id", "")
    )
    if vendor_id:
        vendor_id = str(vendor_id).strip()

    api_key = (
        data.get("api_key")
        or headers.get("X-Api-Key")
        or headers.get("X-Bearer")
        or headers.get("Bearer")
        or os.environ.get("CHOICE_API_KEY", "")
        or auth_state.get("api_key", "")
    )
    if api_key:
        api_key = str(api_key).strip()

    session_id = (
        data.get("session_id")
        or headers.get("X-Session-Id")
        or os.environ.get("CHOICE_SESSION_ID", "")
        or auth_state.get("session_id", "")
    )
    if not session_id and headers.get("Authorization"):
        auth_hdr = headers.get("Authorization", "").strip()
        if auth_hdr.lower().startswith("sessionid "):
            session_id = auth_hdr[10:].strip()
        elif auth_hdr.lower().startswith("bearer "):
            if not api_key:
                api_key = auth_hdr[7:].strip()
        else:
            session_id = auth_hdr
    if session_id:
        session_id = str(session_id).strip()

    access_token = (
        data.get("access_token")
        or headers.get("X-Access-Token")
        or auth_state.get("access_token", "")
        or api_key
    )

    mobile_no = (
        data.get("mobile_no")
        or headers.get("X-Mobile-No")
        or os.environ.get("CHOICE_MOBILE", "")
        or auth_state.get("mobile_no", "")
    )
    if mobile_no:
        mobile_no = str(mobile_no).strip()

    base_url = (
        data.get("base_url")
        or headers.get("X-Base-Url")
        or os.environ.get("CHOICE_BASE_URL", "")
        or auth_state.get("base_url", DEFAULT_BASE_URL)
    )
    base_url = normalize_base_url(base_url)

    return {
        "vendor_id": vendor_id or "",
        "api_key": api_key or "",
        "session_id": session_id or "",
        "access_token": access_token or "",
        "mobile_no": mobile_no or "",
        "base_url": base_url or DEFAULT_BASE_URL,
        "logged_in": bool(session_id and vendor_id)
    }

def get_headers(creds=None, req_obj=None):
    c = creds or auth_state
    headers = {
        "Content-Type": "application/json"
    }
    if c.get("vendor_id"):
        headers["VendorId"] = str(c["vendor_id"]).strip()
    if c.get("api_key"):
        headers["Bearer"] = str(c["api_key"]).strip()
    if c.get("session_id"):
        sess = str(c["session_id"]).strip()
        headers["Authorization"] = f"SessionId {sess}"

    # Forward client IP headers so Choice gateway can verify the user's declared Static IP
    if req_obj:
        client_ip = (
            req_obj.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or req_obj.headers.get("X-Real-IP", "").strip()
            or req_obj.headers.get("CF-Connecting-IP", "").strip()
            or getattr(req_obj, "remote_addr", "")
        )
        if client_ip:
            headers["X-Forwarded-For"] = client_ip
            headers["X-Real-IP"] = client_ip
            headers["Client-IP"] = client_ip
    return headers

def init_choice_client():
    global choice_client
    if HAS_CHOICE_PKG and auth_state["vendor_id"] and auth_state["api_key"]:
        try:
            choice_client = ChoiceClient(
                vendor_id=auth_state["vendor_id"],
                api_key=auth_state["api_key"],
                base_url=auth_state["base_url"]
            )
            if auth_state["session_id"]:
                choice_client.session_id = auth_state["session_id"]
            if auth_state["access_token"]:
                choice_client.access_token = auth_state["access_token"]
        except Exception as e:
            print(f"Error initializing ChoiceClient: {e}")

# Credentials have two different lifetimes and must be treated separately:
#   LONG_LIVED  issued once in the Choice portal, valid until you change them
#   DAILY       issued by ValidateTOTP, dead after the trading day
LONG_LIVED_KEYS = ("vendor_id", "api_key", "mobile_no", "base_url")

def fill_missing_credentials(data, keys=LONG_LIVED_KEYS):
    """
    Copy stored values into auth_state without clobbering a higher-priority
    source. Environment variables load first and always win, then secrets.json,
    then the session file.
    """
    env_base = os.environ.get("CHOICE_BASE_URL", "").strip()
    filled = False
    for key in keys:
        value = str(data.get(key, "") or "").strip()
        if not value:
            continue
        if key == "base_url":
            value = normalize_base_url(value)
        current = str(auth_state.get(key) or "").strip()
        # base_url is seeded with a default, so an untouched default counts as unset
        if key == "base_url" and not env_base and current == DEFAULT_BASE_URL:
            current = ""
        if not current:
            auth_state[key] = value
            filled = True
    return filled

def save_session_to_file():
    """Persist the daily session, and mirror the long-lived credentials so a
    date rollover cannot strand the user without an API key."""
    try:
        data = {
            "date": datetime.date.today().isoformat(),
            "vendor_id": auth_state["vendor_id"],
            "api_key": auth_state["api_key"],
            "session_id": auth_state["session_id"],
            "access_token": auth_state["access_token"],
            "mobile_no": auth_state["mobile_no"],
            "base_url": auth_state["base_url"]
        }
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Failed to save session to file: {e}")

    if auth_state.get("vendor_id") and auth_state.get("api_key"):
        try:
            save_secrets_to_file(
                auth_state["vendor_id"],
                auth_state["api_key"],
                auth_state.get("mobile_no", ""),
                auth_state.get("base_url", DEFAULT_BASE_URL)
            )
        except Exception as e:
            # Read-only filesystem (Vercel). Env vars are the supported path there.
            print(f"Could not mirror credentials to secrets.json: {e}")

def load_session_from_file():
    """
    Restore auth state from the cached session file.

    The file mixes both lifetimes. The long-lived credentials are recovered
    unconditionally -- gating them on the date stamp meant every calendar
    rollover threw away a perfectly valid API key and forced a full re-bootstrap
    before the user could even reach the login button. Only session_id and
    access_token are date-gated, because Choice really does expire those daily.
    """
    if not os.path.exists(SESSION_FILE):
        return False
    try:
        # utf-8-sig tolerates a byte-order mark written by Windows editors
        with open(SESSION_FILE, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Failed to load session from file: {e}")
        return False
    if not isinstance(data, dict):
        return False

    fill_missing_credentials(data)

    session_is_today = (
        data.get("date") == datetime.date.today().isoformat()
        and bool(data.get("session_id"))
    )
    if session_is_today:
        auth_state["session_id"] = str(data.get("session_id", "") or "")
        auth_state["access_token"] = str(data.get("access_token", "") or "")
        auth_state["logged_in"] = bool(auth_state["session_id"])

    init_choice_client()
    return session_is_today

def load_secrets_from_file():
    """
    Load long-lived Choice credentials (vendor id / api key / mobile) written by
    the /admin/bootstrap route. Environment variables always win over this file.
    """
    if not os.path.exists(SECRETS_FILE):
        return False
    try:
        with open(SECRETS_FILE, "r", encoding="utf-8-sig") as f:
            content = f.read().strip()
        data = json.loads(content) if content else {}
        if not isinstance(data, dict):
            return False
        fill_missing_credentials(data)
        return True
    except Exception as e:
        print(f"Failed to load secrets.json: {e}")
    return False

def save_secrets_to_file(vendor_id, api_key, mobile_no, base_url):
    data = {
        "vendor_id": vendor_id,
        "api_key": api_key,
        "mobile_no": mobile_no,
        "base_url": base_url
    }
    with open(SECRETS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# Env vars are already in auth_state. Layer secrets.json under them, then the
# session file -- which also carries long-lived credentials for anyone who
# logged in before /admin/bootstrap existed.
load_secrets_from_file()
load_session_from_file()

# Asynchronously load Choice Scrip Master
def load_scrip_master_async():
    global scrip_master
    if HAS_CHOICE_PKG:
        try:
            print("Background: Fetching Choice Scrip Master CSV...")
            scrip_master = ScripMaster()
            scrip_master.fetch()
            print("Background: Choice Scrip Master loaded successfully.")
        except Exception as e:
            print(f"Background: Scrip Master fetch warning: {e}")

threading.Thread(target=load_scrip_master_async, daemon=True).start()

@app.route("/")
def serve_index():
    return send_from_directory(BASE_DIR, INDEX_FILE)

@app.route("/<path:path>")
def serve_static(path):
    """Serve front-end assets only. Never expose source, secrets or session files."""
    name = os.path.basename(path)
    ext = os.path.splitext(name)[1].lower()
    if name.startswith(".") or name in PRIVATE_STATIC_NAMES or ext not in PUBLIC_STATIC_EXTENSIONS:
        return jsonify({"status": "error", "message": "Not found"}), 404
    return send_from_directory(BASE_DIR, path)

BOOTSTRAP_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Configure server secrets · GROT Scalper</title>
<style>
 body{{margin:0;background:#F1F5F9;color:#0F172A;font:14px/1.55 'Segoe UI',system-ui,sans-serif;display:flex;justify-content:center;padding:32px 16px}}
 .card{{background:#fff;border:1px solid #E2E8F0;border-radius:12px;padding:24px;max-width:520px;width:100%;box-shadow:0 10px 15px -3px rgba(0,0,0,.08)}}
 h1{{margin:0 0 4px;font-size:19px}}
 p.lead{{margin:0 0 18px;color:#475569;font-size:13px}}
 label{{display:block;margin:12px 0 4px;font-size:12px;font-weight:700;color:#475569}}
 input,select{{width:100%;padding:9px 10px;border:1px solid #E2E8F0;border-radius:6px;font:inherit;background:#F8FAFC;color:#0F172A}}
 button{{margin-top:18px;width:100%;padding:11px;border:0;border-radius:8px;background:#0153B8;color:#fff;font-weight:700;font-size:14px;cursor:pointer}}
 .msg{{margin-bottom:14px;padding:10px 12px;border-radius:8px;font-size:12.5px}}
 .ok{{background:rgba(5,150,105,.08);border:1px solid rgba(5,150,105,.22);color:#059669}}
 .warn{{background:rgba(217,119,6,.08);border:1px solid rgba(217,119,6,.22);color:#B45309}}
 a{{color:#0153B8}}
</style></head><body><div class="card">
<h1>Configure server secrets</h1>
<p class="lead">Stored in <code>secrets.json</code> next to <code>server.py</code> and never sent to the browser.
Environment variables (<code>CHOICE_VENDOR_ID</code>, <code>CHOICE_API_KEY</code>, <code>CHOICE_MOBILE</code>) take priority over this file
and are the only option on read-only hosts such as Vercel.</p>
{message}
<form method="post">
 <label for="vendor_id">Client ID / Vendor ID</label>
 <input id="vendor_id" name="vendor_id" value="{vendor_id}" placeholder="e.g. M12345" autocomplete="off" required>
 <label for="api_key">API Key (Bearer)</label>
 <input id="api_key" name="api_key" type="password" value="" placeholder="{api_key_placeholder}" autocomplete="off"{api_key_required}>
 <label for="mobile_no">Registered mobile number</label>
 <input id="mobile_no" name="mobile_no" value="{mobile_no}" placeholder="e.g. 9876543210" autocomplete="off" required>
 <label for="base_url">Gateway</label>
 <select id="base_url" name="base_url">
  <option value="{omne}"{sel_omne}>finxomne.choiceindia.com</option>
  <option value="{finx}"{sel_finx}>finx.choiceindia.com</option>
 </select>
 <button type="submit">Save secrets</button>
</form>
<p class="lead" style="margin:16px 0 0"><a href="/">&larr; Back to the simulator</a></p>
</div></body></html>"""

def render_bootstrap_page(message_html=""):
    base = auth_state.get("base_url") or DEFAULT_BASE_URL
    # The stored API key is never written into the page; leaving the field
    # blank on submit keeps the key that is already stored.
    has_key = bool(auth_state.get("api_key"))
    return BOOTSTRAP_PAGE.format(
        message=message_html,
        vendor_id=html_lib.escape(auth_state.get("vendor_id", "")),
        api_key_placeholder="Stored - leave blank to keep it" if has_key else "Your Choice API key",
        api_key_required="" if has_key else " required",
        mobile_no=html_lib.escape(auth_state.get("mobile_no", "")),
        omne=BASE_URL_OMNE,
        finx=BASE_URL_FINX,
        sel_omne=" selected" if base == BASE_URL_OMNE else "",
        sel_finx=" selected" if base == BASE_URL_FINX else ""
    )

REMOTE_BOOTSTRAP_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Server secrets · GROT Scalper</title>
<style>
 body{margin:0;background:#F1F5F9;color:#0F172A;font:14px/1.6 'Segoe UI',system-ui,sans-serif;display:flex;justify-content:center;padding:32px 16px}
 .card{background:#fff;border:1px solid #E2E8F0;border-radius:12px;padding:24px;max-width:560px;width:100%;box-shadow:0 10px 15px -3px rgba(0,0,0,.08)}
 h1{margin:0 0 8px;font-size:19px}
 p,li{color:#334155;font-size:13.5px}
 code{background:#F1F5F9;border:1px solid #E2E8F0;border-radius:4px;padding:1px 5px;font-size:12.5px}
 ol{padding-left:20px}
 a{color:#0153B8}
</style></head><body><div class="card">
<h1>Credentials can't be set from this browser</h1>
<p>For safety, this page only accepts credentials from the computer the server runs on.
Otherwise anyone who can open this site could replace your Choice login.</p>
<p><b>Hosted on Vercel?</b> Set them as environment variables instead:</p>
<ol>
 <li>Vercel → this project → <b>Settings → Environment Variables</b></li>
 <li>Add <code>CHOICE_VENDOR_ID</code>, <code>CHOICE_API_KEY</code>, <code>CHOICE_MOBILE</code>
     (optional <code>CHOICE_BASE_URL</code>)</li>
 <li>Tick <b>Production</b> and <b>Preview</b>, save, then redeploy</li>
</ol>
<p><b>Running it yourself?</b> Open <code>http://localhost:5000/admin/bootstrap</code> on that computer.</p>
<p><a href="/">&larr; Back to the simulator</a></p>
</div></body></html>"""

def render_remote_bootstrap_page():
    return REMOTE_BOOTSTRAP_PAGE

@app.route("/admin/bootstrap", methods=["GET", "POST"])
def admin_bootstrap():
    """Enter the Choice credentials that the server keeps on its own side."""
    # Only the machine running the server may view or change its credentials.
    # Hosted deployments use environment variables instead (see README).
    if not is_loopback_request():
        if request.method == "GET" and not request.is_json:
            # A person following the login modal's link: explain what to do
            # instead of showing raw JSON.
            return render_remote_bootstrap_page(), 403
        return jsonify({
            "status": "error",
            "message": "/admin/bootstrap is only available from the machine running the server. "
                       "Set CHOICE_VENDOR_ID / CHOICE_API_KEY / CHOICE_MOBILE instead, "
                       "or set ALLOW_REMOTE_ADMIN=1 if you understand the risk."
        }), 403

    if request.method == "GET":
        return render_bootstrap_page()

    data = request.get_json(silent=True) or request.form or {}
    vendor_id = str(data.get("vendor_id", "")).strip()
    api_key = str(data.get("api_key", "")).strip() or str(auth_state.get("api_key", "") or "").strip()
    mobile_no = str(data.get("mobile_no", "")).strip()
    base_url = normalize_base_url(data.get("base_url", ""))

    if not vendor_id or not api_key or not mobile_no:
        msg = '<div class="msg warn">Client ID, API Key and mobile number are all required.</div>'
        return render_bootstrap_page(msg), 400

    auth_state["vendor_id"] = vendor_id
    auth_state["api_key"] = api_key
    auth_state["mobile_no"] = mobile_no
    auth_state["base_url"] = base_url
    init_choice_client()

    try:
        save_secrets_to_file(vendor_id, api_key, mobile_no, base_url)
        msg = '<div class="msg ok">Saved. Go back to the simulator and press <b>1-Click Login</b>.</div>'
    except Exception as e:
        msg = (f'<div class="msg warn">Held in memory for this process only &mdash; '
               f'secrets.json could not be written ({html_lib.escape(str(e))}). '
               f'On Vercel use environment variables instead.</div>')

    if request.is_json:
        return jsonify({"status": "success", "message": "Secrets stored", "vendor_id": vendor_id})
    return render_bootstrap_page(msg)

@app.route("/api/auth/status", methods=["GET", "POST"])
def auth_status():
    data = request.get_json(silent=True) or {}
    creds = extract_credentials(data, request)
    client_ip = (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.headers.get("X-Real-IP", "").strip()
        or request.headers.get("CF-Connecting-IP", "").strip()
        or request.remote_addr
        or ""
    )
    # This endpoint is unauthenticated, so it reports state as booleans only.
    # It must never carry the api key, session id, access token, the live OTP,
    # or the registered mobile number. auth_validate still reads last_otp from
    # auth_state server-side; it just is not published here.
    return jsonify({
        "status": "success",
        "logged_in": creds["logged_in"],
        "vendor_id": creds["vendor_id"],
        "has_session": bool(creds["session_id"]),
        "has_credentials": bool(creds["vendor_id"] and creds["api_key"] and creds["mobile_no"]),
        # Whether the login form may save credentials (only on the server's own machine)
        "can_save": is_loopback_request(),
        "base_url": creds["base_url"],
        "client_ip": client_ip
    })

@app.route("/api/client_ip", methods=["GET"])
def get_client_ip():
    client_ip = (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.headers.get("X-Real-IP", "").strip()
        or request.headers.get("CF-Connecting-IP", "").strip()
        or request.remote_addr
        or ""
    )
    return jsonify({"status": "success", "ip": client_ip})

@app.route("/api/auth/get_client_otp", methods=["POST"])
def auth_get_client_otp():
    """
    Executes:
    1. LoginTOTP (initiate login challenge)
    2. GetClientLoginTOTP (retrieve the actual OTP generated by Choice)
    """
    data = request.get_json(silent=True) or {}
    creds = extract_credentials(data, request)
    mobile_no = creds["mobile_no"]
    vendor_id = creds["vendor_id"]
    api_key = creds["api_key"]
    base_url = creds["base_url"]

    if not mobile_no:
        return jsonify({"status": "error", "message": "Registered mobile number is required"}), 400
    if not vendor_id:
        return jsonify({"status": "error", "message": "Vendor ID / Client ID is required"}), 400
    if not api_key:
        return jsonify({"status": "error", "message": "API Key / Bearer token is required"}), 400

    auth_state["mobile_no"] = mobile_no
    auth_state["vendor_id"] = vendor_id
    auth_state["api_key"] = api_key
    auth_state["base_url"] = base_url

    encoded_mobile = encode_mobile(mobile_no)
    headers = {
        "VendorId": vendor_id,
        "Bearer": api_key,
        "Content-Type": "application/json"
    }

    # Step 1: LoginTOTP
    url_login = f"{base_url}/api/OpenAPIV1/LoginTOTP"
    payload = {"MobileNo": encoded_mobile}
    
    try:
        resp1 = requests.post(url_login, json=payload, headers=headers, timeout=15)
        resp1_json = resp1.json() if resp1.status_code == 200 else {}
    except Exception as e:
        resp1_json = {"Error": str(e)}

    # Step 2: GetClientLoginTOTP (Fetches the generated OTP)
    url_get_otp = f"{base_url}/api/OpenAPIV1/GetClientLoginTOTP"
    try:
        resp2 = requests.post(url_get_otp, json=payload, headers=headers, timeout=15)
        if resp2.status_code == 200:
            resp2_json = resp2.json()
            otp = resp2_json.get("Response")
            if otp:
                # The OTP stays on the server; /api/auth/validate reads it from
                # auth_state, so it never needs to travel to the browser.
                auth_state["last_otp"] = str(otp)
                return jsonify({
                    "status": "success",
                    "message": "OTP retrieved via GetClientLoginTOTP. Call /api/auth/validate to finish login.",
                    "vendor_id": vendor_id
                })
            else:
                return jsonify({
                    "status": "error",
                    "message": f"GetClientLoginTOTP returned no OTP: {resp2_json.get('Message') or resp2.text}"
                }), 400
        else:
            return jsonify({
                "status": "error",
                "message": f"GetClientLoginTOTP HTTP {resp2.status_code}: {resp2.text}"
            }), resp2.status_code
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to call GetClientLoginTOTP: {str(e)}"
        }), 500

def login_success_payload(message, vendor_id, base_url):
    """
    What a successful login tells the browser. The session id, access token,
    API key, OTP and mobile number stay server-side: the browser never uses
    them, and returning them is what made them stealable.
    """
    return {
        "status": "success",
        "message": message,
        "vendor_id": vendor_id,
        "base_url": base_url,
        "logged_in": True
    }

@app.route("/api/auth/validate", methods=["POST"])
def auth_validate():
    """
    Executes ValidateTOTP to verify OTP and obtain SessionId and AccessToken
    """
    data = request.get_json(silent=True) or {}
    creds = extract_credentials(data, request)
    otp = str(data.get("otp") or data.get("totp") or auth_state.get("last_otp") or "").strip()
    mobile_no = creds["mobile_no"]
    vendor_id = creds["vendor_id"]
    api_key = creds["api_key"]
    base_url = creds["base_url"]

    if not otp:
        return jsonify({"status": "error", "message": "OTP code is required"}), 400
    if not mobile_no:
        return jsonify({"status": "error", "message": "Mobile number is required"}), 400
    if not vendor_id or not api_key:
        return jsonify({"status": "error", "message": "Vendor ID and API Key are required"}), 400

    encoded_mobile = encode_mobile(mobile_no)
    auth_state["mobile_no"] = mobile_no
    auth_state["vendor_id"] = vendor_id
    auth_state["api_key"] = api_key
    auth_state["base_url"] = base_url

    url_validate = f"{base_url}/api/OpenAPIV1/ValidateTOTP"
    payload = {
        "MobileNo": encoded_mobile,
        "OTP": str(otp)
    }
    headers = {
        "VendorId": vendor_id,
        "Bearer": api_key,
        "Content-Type": "application/json"
    }

    try:
        resp = requests.post(url_validate, json=payload, headers=headers, timeout=15)
        if resp.status_code == 200:
            resp_json = resp.json()
            if resp_json.get("Status") == "Success" or resp_json.get("Response"):
                res_data = resp_json.get("Response", {})
                if isinstance(res_data, str):
                    session_id = res_data
                    access_token = api_key
                elif isinstance(res_data, dict):
                    session_id = res_data.get("SessionId") or res_data.get("session_id")
                    access_token = res_data.get("AccessToken") or api_key
                else:
                    session_id = f"sess_{int(datetime.datetime.now().timestamp())}"
                    access_token = api_key

                auth_state["session_id"] = str(session_id)
                auth_state["access_token"] = str(access_token)
                auth_state["logged_in"] = True
                auth_state["user_details"] = resp_json

                init_choice_client()
                save_session_to_file()

                return jsonify(login_success_payload("Choice 2FA authentication verified successfully!", vendor_id, base_url))
            else:
                return jsonify({
                    "status": "error",
                    "message": f"ValidateTOTP failed: {resp_json.get('Message') or 'no session returned'}"
                }), 400
        else:
            return jsonify({
                "status": "error",
                "message": f"ValidateTOTP HTTP {resp.status_code}: {resp.text}"
            }), resp.status_code
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"ValidateTOTP connection failed: {str(e)}"
        }), 500

NEEDS_CREDENTIALS_MESSAGE = "Enter your Choice Client ID, API key and registered mobile number to log in."
HOSTED_CREDENTIALS_MESSAGE = (
    "This hosted copy has no Choice credentials. Add CHOICE_VENDOR_ID, CHOICE_API_KEY and "
    "CHOICE_MOBILE in Vercel > Settings > Environment Variables, or run the app on your own computer."
)

@app.route("/api/auth/connect", methods=["POST"])
def auth_connect():
    """
    The single login action used by the app.

    With no body it logs in using the credentials the server already holds
    (this is what runs automatically when the page opens). With client ID /
    API key / mobile in the body it first saves them on this computer, then
    logs in, so first-time setup is one form and one click. Saving is
    local-only for the same reason /admin/bootstrap is.
    """
    data = request.get_json(silent=True) or {}
    supplied = {k: str(data.get(k, "") or "").strip() for k in ("vendor_id", "api_key", "mobile_no")}

    if any(supplied.values()):
        if not is_loopback_request():
            return jsonify({"status": "error", "message": HOSTED_CREDENTIALS_MESSAGE}), 403
        # A blank field keeps what is stored, so changing one value is easy
        vendor_id = supplied["vendor_id"] or str(auth_state.get("vendor_id") or "").strip()
        api_key = supplied["api_key"] or str(auth_state.get("api_key") or "").strip()
        mobile_no = supplied["mobile_no"] or str(auth_state.get("mobile_no") or "").strip()
        if not (vendor_id and api_key and mobile_no):
            return jsonify({"status": "error", "needs_credentials": True, "message": NEEDS_CREDENTIALS_MESSAGE}), 400
        changed = (vendor_id, api_key, mobile_no) != (auth_state.get("vendor_id"), auth_state.get("api_key"), auth_state.get("mobile_no"))
        auth_state["vendor_id"], auth_state["api_key"], auth_state["mobile_no"] = vendor_id, api_key, mobile_no
        if changed:
            # New credentials invalidate any session issued for the old ones
            auth_state["session_id"] = ""
            auth_state["access_token"] = ""
            auth_state["logged_in"] = False
        try:
            save_secrets_to_file(vendor_id, api_key, mobile_no, auth_state.get("base_url") or DEFAULT_BASE_URL)
        except Exception as e:
            print(f"Could not save secrets.json: {e}")

    vendor_id = str(auth_state.get("vendor_id") or "").strip()
    api_key = str(auth_state.get("api_key") or "").strip()
    mobile_no = str(auth_state.get("mobile_no") or "").strip()
    if not (vendor_id and api_key and mobile_no):
        return jsonify({
            "status": "error",
            "needs_credentials": True,
            "can_save": is_loopback_request(),
            "message": NEEDS_CREDENTIALS_MESSAGE if is_loopback_request() else HOSTED_CREDENTIALS_MESSAGE
        }), 400

    payload, status = perform_choice_login(vendor_id, api_key, mobile_no, normalize_base_url(auth_state.get("base_url")))
    return jsonify(payload), status

@app.route("/api/auth/login_auto", methods=["POST"])
def auth_login_auto():
    """
    One-click automated full login (kept for existing callers):
    1. LoginTOTP
    2. GetClientLoginTOTP (retrieve OTP)
    3. ValidateTOTP (exchange OTP for SessionId)
    """
    data = request.get_json(silent=True) or {}
    creds = extract_credentials(data, request)
    mobile_no = creds["mobile_no"]
    vendor_id = creds["vendor_id"]
    api_key = creds["api_key"]
    base_url = creds["base_url"]

    if not mobile_no or not vendor_id or not api_key:
        return jsonify({
            "status": "error",
            "needs_bootstrap": True,
            "needs_credentials": True,
            "message": NEEDS_CREDENTIALS_MESSAGE
        }), 400

    payload, status = perform_choice_login(vendor_id, api_key, mobile_no, base_url)
    return jsonify(payload), status

def perform_choice_login(vendor_id, api_key, mobile_no, base_url):
    """Run Choice's TOTP login and store the session. Returns (payload, http_status)."""
    auth_state["mobile_no"] = mobile_no
    auth_state["vendor_id"] = vendor_id
    auth_state["api_key"] = api_key
    auth_state["base_url"] = base_url

    # Use ChoiceClient if available
    if HAS_CHOICE_PKG:
        try:
            client = ChoiceClient(vendor_id=vendor_id, api_key=api_key, base_url=base_url)
            sess_id = client.login(mobile_no)
            
            auth_state["session_id"] = str(client.session_id)
            auth_state["access_token"] = str(client.access_token or api_key)
            auth_state["logged_in"] = True
            
            global choice_client
            choice_client = client
            save_session_to_file()

            return login_success_payload("Logged in to Choice.", vendor_id, base_url), 200
        except Exception:
            pass # Fallback to manual requests below

    # Fallback to direct requests
    encoded_mobile = encode_mobile(mobile_no)
    headers = {"VendorId": vendor_id, "Bearer": api_key, "Content-Type": "application/json"}
    
    try:
        # Step 1: LoginTOTP
        requests.post(f"{base_url}/api/OpenAPIV1/LoginTOTP", json={"MobileNo": encoded_mobile}, headers=headers, timeout=15)
        # Step 2: GetClientLoginTOTP
        r2 = requests.post(f"{base_url}/api/OpenAPIV1/GetClientLoginTOTP", json={"MobileNo": encoded_mobile}, headers=headers, timeout=15)
        r2_data = r2.json() if r2.status_code == 200 else {}
        otp = r2_data.get("Response")
        if not otp:
            return {"status": "error", "message": f"Choice did not accept these credentials: {r2_data.get('Message') or r2.text or 'no OTP returned'}. Check the Client ID, API key and mobile number."}, 400

        # Step 3: ValidateTOTP
        r3 = requests.post(f"{base_url}/api/OpenAPIV1/ValidateTOTP", json={"MobileNo": encoded_mobile, "OTP": str(otp)}, headers=headers, timeout=15)
        r3_data = r3.json() if r3.status_code == 200 else {}
        
        res_data = r3_data.get("Response", {})
        session_id = res_data.get("SessionId") if isinstance(res_data, dict) else res_data
        if not session_id:
            return {"status": "error", "message": f"Choice login failed: {r3_data.get('Message') or r3.text or 'no session returned'}"}, 400

        access_token = res_data.get("AccessToken", api_key) if isinstance(res_data, dict) else api_key

        auth_state["session_id"] = str(session_id)
        auth_state["access_token"] = str(access_token)
        auth_state["logged_in"] = True
        auth_state["last_otp"] = str(otp)

        init_choice_client()
        save_session_to_file()

        return login_success_payload("Logged in to Choice.", vendor_id, base_url), 200
    except Exception as e:
        return {"status": "error", "message": f"Could not reach Choice to log in: {str(e)}"}, 502

@app.route("/api/auth/manual", methods=["POST"])
def auth_manual():
    """Directly configure VendorId, ApiKey and SessionId"""
    data = request.get_json(silent=True) or {}
    creds = extract_credentials(data, request)
    vendor_id = creds["vendor_id"]
    api_key = creds["api_key"]
    session_id = creds["session_id"]
    base_url = creds["base_url"]
    
    if not vendor_id or not session_id:
        return jsonify({"status": "error", "message": "VendorId and SessionId are required"}), 400
        
    auth_state["vendor_id"] = vendor_id
    auth_state["api_key"] = api_key
    auth_state["session_id"] = session_id
    auth_state["base_url"] = base_url
    auth_state["logged_in"] = True
    
    init_choice_client()
    save_session_to_file()
    
    return jsonify(login_success_payload("Session credentials saved successfully.", vendor_id, base_url))

@app.route("/api/scrip/search", methods=["GET"])
def search_scrip():
    """Fuzzy search scrips across master (Supports Names & Tokens)"""
    query = request.args.get("query", "").strip().upper()
    segment = request.args.get("segment", "").strip()

    results = []
    today = datetime.date.today()
    wants_options = bool(re.search(r"\d|CE$|PE$", query))

    # 1. Search dynamically from Choice ScripMaster
    if query and getattr(scrip_master, "is_loaded", False):
        scored = []
        for row in getattr(scrip_master, "all_rows", []):
            d_symbol = row.get('Symbol', '').strip().upper()
            d_sec_desc = row.get('SecDesc', '').strip().upper()
            d_token = row.get('Token', '').strip()
            if not (query in d_symbol or query in d_sec_desc or query == d_token or query in d_token):
                continue
            if segment and row.get('Segment', '').strip() != segment:
                continue
            instrument = row.get('Instrument', '').strip().upper()
            is_option = instrument in OPTION_INSTRUMENTS
            # "GOLD" matches ~12,000 option rows; hide them unless the query
            # names a strike, an expiry or CE/PE.
            if is_option and not wants_options:
                continue
            expiry = parse_expiry(row.get('Expiry'))
            if expiry and expiry < today:
                continue
            # Exact symbol first, then tradable futures/cash, then spot reference
            # rates (MCXSPOT/NCDEXSPOT), then options; nearest expiry first
            is_spot = row.get('Exchange', '').strip().upper().endswith('SPOT')
            scored.append((
                0 if d_symbol == query or d_token == query else 1,
                2 if is_option else (1 if is_spot else 0),
                expiry or datetime.date.min,
                d_symbol,
                row
            ))
        scored.sort(key=lambda item: item[:4])

        for *_, row in scored[:30]:
            try:
                results.append(scrip_row_to_result(row))
            except Exception:
                continue

    # 2. Add / fallback to preset scrips
    if not results:
        query_lower = query.lower()
        for s in DEFAULT_SCRIPS:
            if segment and str(s.get("segment_id")) != segment:
                continue
            if not query_lower or query_lower in s["symbol"].lower() or query_lower in s["name"].lower() or query_lower in str(s["token"]):
                results.append(s)

    return jsonify({
        "status": "success",
        "count": len(results),
        "results": results[:30]
    })

@app.route("/api/scrip/resolve", methods=["GET"])
def resolve_scrip():
    """
    Resolve a commodity name (GOLD, SILVER, ...) to its nearest live MCX
    futures contract, with the lot multiplier the simulator needs.
    """
    symbol = request.args.get("symbol", "").strip().upper()
    if not symbol:
        return jsonify({"status": "error", "message": "symbol is required"}), 400
    if not getattr(scrip_master, "is_loaded", False):
        return jsonify({
            "status": "error",
            "loading": True,
            "message": "Choice contract list is still downloading (about 22 MB). Try again in a minute."
        }), 503
    row = nearest_future(symbol)
    if not row:
        return jsonify({"status": "error", "message": f"No live MCX futures contract found for {symbol}."}), 404
    return jsonify({"status": "success", "result": scrip_row_to_result(row)})

def parse_date_to_1980_seconds(date_val: str, is_end: bool = False) -> int:
    """Calculates seconds since 1980-01-01 00:00:00 as required by Choice Historical API"""
    epoch_1980 = datetime.datetime(1980, 1, 1)
    date_str = str(date_val).strip()
    try:
        if " " in date_str:
            dt = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        else:
            dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            if is_end:
                dt = dt.replace(hour=23, minute=59, second=59)
        return int((dt - epoch_1980).total_seconds())
    except Exception:
        # Default fallback
        dt = datetime.datetime.now()
        if is_end:
            dt = dt.replace(hour=23, minute=59, second=59)
        return int((dt - epoch_1980).total_seconds())

@app.route("/api/historical", methods=["POST"])
def get_historical_candles():
    """
    Fetch historical candlestick data from Choice OpenAPI /api/OpenGraph/ChartData
    Standardizes output to [{ dt: 'YYYY-MM-DD HH:MM:SS', o, h, l, c, v }]
    """
    data = request.get_json(silent=True) or {}
    creds = extract_credentials(data, request)
    segment_id = int(data.get("segment_id", 1))
    token = data.get("token")
    from_date = data.get("from_date", "").strip()
    to_date = data.get("to_date", "").strip()
    interval = str(data.get("interval", "1")).strip()

    if not token:
        return jsonify({"status": "error", "message": "Scrip token is required"}), 400

    if not creds.get("vendor_id"):
        return jsonify({
            "status": "error",
            "message": "Choice Client ID / Vendor ID is missing. Please click '🔑 Login / Settings' in the top bar to log in or enter your Choice credentials."
        }), 401

    if not creds.get("session_id") and not creds.get("api_key"):
        return jsonify({
            "status": "error",
            "message": "Active Choice Session ID is missing. Please click '🔑 Login / Settings' to authenticate or paste your active Session ID."
        }), 401

    # Direct HTTP Request with 1980 epoch dates
    from_sec = parse_date_to_1980_seconds(from_date, is_end=False)
    to_sec = parse_date_to_1980_seconds(to_date, is_end=True)

    primary_url = f"{creds['base_url']}/api/OpenGraph/ChartData"
    alt_base = "https://finx.choiceindia.com" if "finxomne" in creds['base_url'] else "https://finxomne.choiceindia.com"
    alt_url = f"{alt_base}/api/OpenGraph/ChartData"

    payload = {
        "SegmentId": segment_id,
        "Token": int(token),
        "FromDate": from_sec,
        "ToDate": to_sec,
        "Interval": interval
    }

    req_headers = get_headers(creds, req_obj=request)
    urls_to_try = [primary_url, alt_url]
    last_resp_text = ""
    last_status = 500

    for current_url in urls_to_try:
        try:
            resp = requests.post(current_url, json=payload, headers=req_headers, timeout=30)
            last_status = resp.status_code
            last_resp_text = resp.text

            if resp.status_code == 200:
                res_json = resp.json()
                if res_json.get("Status") == "Success":
                    chart_resp = res_json.get("Response", {})
                    history = chart_resp.get("lstChartHistory", [])
                    divisor = float(chart_resp.get("PriceDivisor", 1) or 1)
                    epoch_1980 = datetime.datetime(1980, 1, 1)

                    bars = []
                    for row in history:
                        parts = str(row).split(",")
                        if len(parts) >= 6:
                            sec_offset = int(parts[0])
                            dt_obj = epoch_1980 + datetime.timedelta(seconds=sec_offset)
                            bars.append({
                                "dt": dt_obj.strftime("%Y-%m-%d %H:%M:%S"),
                                "o": float(parts[1]) / divisor,
                                "h": float(parts[2]) / divisor,
                                "l": float(parts[3]) / divisor,
                                "c": float(parts[4]) / divisor,
                                "v": float(parts[5])
                            })

                    if bars:
                        return jsonify({
                            "status": "success",
                            "count": len(bars),
                            "bars": bars,
                            "gateway": current_url
                        })
                    else:
                        is_avail = chart_resp.get("IsDataAvailable", False)
                        return jsonify({
                            "status": "error",
                            "message": f"Choice OpenAPI connected successfully, but returned no candles for Token {token} on Segment {segment_id} (IsDataAvailable={is_avail}).\n\nTips:\n• For NIFTY 50 Index use Token: 26000 (Segment: 1)\n• For BANKNIFTY Index use Token: 26009 (Segment: 1)\n• For SENSEX Index use Token: 1 (Segment: 3)\n• For stocks, search by name in the Symbol box.\n• Ensure the selected date range contains active market trading days.",
                            "raw": res_json
                        }), 404
        except Exception as e:
            last_resp_text = str(e)
            continue

    client_ip = (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.headers.get("X-Real-IP", "").strip()
        or request.remote_addr
        or ""
    )

    if last_status == 401:
        return jsonify({
            "status": "error",
            "message": f"Choice API 401 Unauthorized: {last_resp_text}. (Client IP: {client_ip}). Please check that your Choice Portal API Key has your static IP registered or allows your IP.",
            "client_ip": client_ip,
            "tried_gateways": urls_to_try
        }), 401

    return jsonify({
        "status": "error",
        "message": f"Choice API Error (HTTP {last_status}): {last_resp_text}",
        "client_ip": client_ip
    }), last_status

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("=" * 65)
    print(f"  GROT Dynamic Ladder Simulator Server running on http://localhost:{port}")
    print(f"  Choice SDK: {'Loaded (kkunal-1.2.0)' if HAS_CHOICE_PKG else 'Fallback HTTP'}")
    print(f"  Session Status: {'Active Logged In' if auth_state['logged_in'] else 'Login Required'}")
    print("=" * 65)
    app.run(host="0.0.0.0", port=port, debug=False)

