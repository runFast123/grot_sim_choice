import os
import json
import base64
import datetime
import threading
import html as html_lib
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
CORS(app)

SESSION_FILE = os.path.join(BASE_DIR, ".choice_session.json")
SECRETS_FILE = os.path.join(BASE_DIR, "secrets.json")
DEFAULT_BASE_URL = BASE_URL_OMNE

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
    "base_url": os.environ.get("CHOICE_BASE_URL", DEFAULT_BASE_URL),
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
    {"symbol": "LT", "name": "Larsen & Toubro Ltd", "segment_id": 1, "token": 11483, "exchange": "NSE-CM", "type": "EQUITY", "lot": 1},
    {"symbol": "CRUDEOIL", "name": "Crude Oil Commodity", "segment_id": 5, "token": 100000, "exchange": "MCX", "type": "COMMODITY", "lot": 100},
    {"symbol": "GOLD", "name": "Gold Commodity", "segment_id": 5, "token": 100001, "exchange": "MCX", "type": "COMMODITY", "lot": 100},
    {"symbol": "SILVER", "name": "Silver Commodity", "segment_id": 5, "token": 100002, "exchange": "MCX", "type": "COMMODITY", "lot": 30}
]

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
    base_url = str(base_url).strip().rstrip("/") if base_url else DEFAULT_BASE_URL

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

def save_session_to_file():
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

def load_session_from_file():
    if not os.path.exists(SESSION_FILE):
        return False
    try:
        # utf-8-sig tolerates a byte-order mark written by Windows editors
        with open(SESSION_FILE, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        if data.get("date") == datetime.date.today().isoformat() and data.get("session_id"):
            auth_state["vendor_id"] = data.get("vendor_id", "")
            auth_state["api_key"] = data.get("api_key", "")
            auth_state["session_id"] = data.get("session_id", "")
            auth_state["access_token"] = data.get("access_token", "")
            auth_state["mobile_no"] = data.get("mobile_no", "")
            auth_state["base_url"] = data.get("base_url", DEFAULT_BASE_URL)
            auth_state["logged_in"] = bool(auth_state["session_id"])
            init_choice_client()
            return True
    except Exception as e:
        print(f"Failed to load session from file: {e}")
    return False

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
        for key in ("vendor_id", "api_key", "mobile_no", "base_url"):
            value = str(data.get(key, "") or "").strip()
            if value and not auth_state.get(key):
                auth_state[key] = value
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

# Load stored secrets, then any still-valid session for today
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
 <input id="api_key" name="api_key" type="password" value="{api_key}" placeholder="Your Choice API key" autocomplete="off" required>
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
    return BOOTSTRAP_PAGE.format(
        message=message_html,
        vendor_id=html_lib.escape(auth_state.get("vendor_id", "")),
        api_key=html_lib.escape(auth_state.get("api_key", "")),
        mobile_no=html_lib.escape(auth_state.get("mobile_no", "")),
        omne=BASE_URL_OMNE,
        finx=BASE_URL_FINX,
        sel_omne=" selected" if base == BASE_URL_OMNE else "",
        sel_finx=" selected" if base == BASE_URL_FINX else ""
    )

@app.route("/admin/bootstrap", methods=["GET", "POST"])
def admin_bootstrap():
    """Enter the Choice credentials that the server keeps on its own side."""
    if request.method == "GET":
        return render_bootstrap_page()

    data = request.get_json(silent=True) or request.form or {}
    vendor_id = str(data.get("vendor_id", "")).strip()
    api_key = str(data.get("api_key", "")).strip()
    mobile_no = str(data.get("mobile_no", "")).strip()
    base_url = str(data.get("base_url", "")).strip().rstrip("/") or DEFAULT_BASE_URL

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
                auth_state["last_otp"] = str(otp)
                return jsonify({
                    "status": "success",
                    "otp": str(otp),
                    "message": f"OTP successfully retrieved via GetClientLoginTOTP: {otp}",
                    "vendor_id": vendor_id,
                    "mobile_no": mobile_no,
                    "raw_login": resp1_json,
                    "raw_otp": resp2_json
                })
            else:
                return jsonify({
                    "status": "error",
                    "message": f"GetClientLoginTOTP returned no OTP: {resp2_json.get('Message') or resp2.text}",
                    "raw": resp2_json
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

                return jsonify({
                    "status": "success",
                    "message": "Choice 2FA authentication verified successfully!",
                    "session_id": str(session_id),
                    "access_token": str(access_token),
                    "vendor_id": vendor_id,
                    "api_key": api_key,
                    "mobile_no": mobile_no,
                    "base_url": base_url,
                    "logged_in": True,
                    "data": resp_json
                })
            else:
                return jsonify({
                    "status": "error",
                    "message": f"ValidateTOTP failed: {resp_json.get('Message') or resp_json}",
                    "raw": resp_json
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

@app.route("/api/auth/login_auto", methods=["POST"])
def auth_login_auto():
    """
    One-click automated full login:
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
            "message": "Server has no Choice credentials yet. Open /admin/bootstrap to store your Client ID, API Key and mobile number (or set CHOICE_VENDOR_ID / CHOICE_API_KEY / CHOICE_MOBILE)."
        }), 400

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

            return jsonify({
                "status": "success",
                "message": f"Choice 1-Click Login successful! SessionId: {sess_id[:10]}...",
                "session_id": str(sess_id),
                "access_token": auth_state["access_token"],
                "vendor_id": vendor_id,
                "api_key": api_key,
                "mobile_no": mobile_no,
                "base_url": base_url,
                "logged_in": True
            })
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
            return jsonify({"status": "error", "message": f"Could not get OTP from Choice: {r2_data.get('Message') or r2.text}"}), 400

        # Step 3: ValidateTOTP
        r3 = requests.post(f"{base_url}/api/OpenAPIV1/ValidateTOTP", json={"MobileNo": encoded_mobile, "OTP": str(otp)}, headers=headers, timeout=15)
        r3_data = r3.json() if r3.status_code == 200 else {}
        
        res_data = r3_data.get("Response", {})
        session_id = res_data.get("SessionId") if isinstance(res_data, dict) else res_data
        if not session_id:
            return jsonify({"status": "error", "message": f"ValidateTOTP failed: {r3_data.get('Message') or r3.text}"}), 400

        access_token = res_data.get("AccessToken", api_key) if isinstance(res_data, dict) else api_key

        auth_state["session_id"] = str(session_id)
        auth_state["access_token"] = str(access_token)
        auth_state["logged_in"] = True
        auth_state["last_otp"] = str(otp)

        init_choice_client()
        save_session_to_file()

        return jsonify({
            "status": "success",
            "message": f"Choice 1-Click Login successful! (OTP: {otp})",
            "session_id": str(session_id),
            "access_token": str(access_token),
            "vendor_id": vendor_id,
            "api_key": api_key,
            "mobile_no": mobile_no,
            "base_url": base_url,
            "logged_in": True
        })
    except Exception as e:
        return jsonify({"status": "error", "message": f"Auto-login failed: {str(e)}"}), 500

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
    
    return jsonify({
        "status": "success",
        "message": "Session credentials saved successfully.",
        "vendor_id": vendor_id,
        "api_key": api_key,
        "session_id": session_id,
        "base_url": base_url,
        "logged_in": True
    })

@app.route("/api/scrip/search", methods=["GET"])
def search_scrip():
    """Fuzzy search scrips across master (Supports Names & Tokens)"""
    query = request.args.get("query", "").strip().upper()
    segment = request.args.get("segment", "").strip()

    results = []
    
    # 1. Search dynamically from Choice ScripMaster
    if query and getattr(scrip_master, "is_loaded", False):
        matches = []
        for row in getattr(scrip_master, "all_rows", []):
            d_symbol = row.get('Symbol', '').strip().upper()
            d_sec_desc = row.get('SecDesc', '').strip().upper()
            d_token = row.get('Token', '').strip()
            
            # Allow searching by exact token number, or substring of symbol/description
            if query in d_symbol or query in d_sec_desc or query == d_token or query in d_token:
                matches.append(row)
                if len(matches) >= 30: # Limit to top 30 results for speed
                    break

        for m in matches:
            try:
                results.append({
                    "symbol": m.get("Symbol"),
                    "name": m.get("SecDesc"),
                    "segment_id": int(m.get("Segment") or 1),
                    "token": int(m.get("Token")),
                    "exchange": m.get("Exchange"),
                    "type": m.get("Series", "EQUITY"),
                    "lot": int(m.get("MarketLot") or 1)
                })
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

