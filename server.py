import os
import sys
import json
import base64
import datetime
import threading
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
app = Flask(__name__, static_folder=BASE_DIR)
CORS(app)

SESSION_FILE = os.path.join(BASE_DIR, ".choice_session.json")
DEFAULT_BASE_URL = BASE_URL_OMNE

# In-memory session store & client
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
        with open(SESSION_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Failed to save session to file: {e}")

def load_session_from_file():
    if not os.path.exists(SESSION_FILE):
        return False
    try:
        with open(SESSION_FILE, "r") as f:
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

# Load existing active session if available
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
    return send_from_directory(BASE_DIR, "KKunal_GROT_Last_SquareOff_v7.html")

@app.route("/<path:path>")
def serve_static(path):
    return send_from_directory(BASE_DIR, path)

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
    return jsonify({
        "status": "success",
        "logged_in": creds["logged_in"],
        "vendor_id": creds["vendor_id"],
        "mobile_no": creds["mobile_no"],
        "has_session": bool(creds["session_id"]),
        "base_url": creds["base_url"],
        "client_ip": client_ip,
        "last_otp": auth_state.get("last_otp", "")
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
    otp = data.get("otp", "").strip() or data.get("totp", "").strip() or auth_state.get("last_otp", "")
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
        return jsonify({"status": "error", "message": "Mobile number, Vendor ID, and API Key are all required"}), 400

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
    """Fuzzy search scrips across master or fallback list"""
    query = request.args.get("query", "").strip().lower()
    segment = request.args.get("segment", "").strip()

    results = []
    
    # 1. Search dynamically from Choice ScripMaster if loaded
    if scrip_master and scrip_master.is_loaded and query:
        matches = scrip_master.search(query)
        for m in matches[:30]:
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
        for s in DEFAULT_SCRIPS:
            if segment and str(s.get("segment_id")) != segment:
                continue
            if not query or query in s["symbol"].lower() or query in s["name"].lower():
                results.append(s)

    return jsonify({
        "status": "success",
        "count": len(results),
        "results": results[:30]
    })

def parse_date_to_1980_seconds(date_val: str) -> int:
    """Calculates seconds since 1980-01-01 00:00:00 as required by Choice Historical API"""
    epoch_1980 = datetime.datetime(1980, 1, 1)
    date_str = str(date_val).strip()
    try:
        if " " in date_str:
            dt = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        else:
            dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        return int((dt - epoch_1980).total_seconds())
    except Exception:
        # Default fallback
        dt = datetime.datetime.now()
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

    # If ChoiceClient SDK instance can be initialized
    if HAS_CHOICE_PKG and creds.get("vendor_id") and creds.get("api_key"):
        try:
            client = ChoiceClient(
                vendor_id=creds["vendor_id"],
                api_key=creds["api_key"],
                base_url=creds["base_url"]
            )
            if creds.get("session_id"):
                client.session_id = creds["session_id"]
            if creds.get("access_token"):
                client.access_token = creds["access_token"]
            
            df = client.historical.get_historical_data(
                segment_id=segment_id,
                token=int(token),
                from_date=from_date,
                to_date=to_date,
                resolution=interval
            )
            if not df.empty and "Time" in df.columns:
                bars = []
                for _, row in df.iterrows():
                    dt_val = row["Time"]
                    dt_str = dt_val.strftime("%Y-%m-%d %H:%M:%S") if hasattr(dt_val, "strftime") else str(dt_val)
                    bars.append({
                        "dt": dt_str,
                        "o": float(row.get("Open", 0)),
                        "h": float(row.get("High", 0)),
                        "l": float(row.get("Low", 0)),
                        "c": float(row.get("Close", 0)),
                        "v": float(row.get("Volume", 0))
                    })
                return jsonify({
                    "status": "success",
                    "count": len(bars),
                    "bars": bars
                })
        except Exception as e:
            print(f"choice_client historical call exception: {e}, attempting direct HTTP request...")

    # Direct HTTP Request with 1980 epoch dates
    from_sec = parse_date_to_1980_seconds(from_date)
    to_sec = parse_date_to_1980_seconds(to_date)

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

