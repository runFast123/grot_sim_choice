import os
import re
import sys
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Windows consoles default to cp1252, which cannot encode the rupee sign.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from server import app, parse_date_to_1980_seconds, INDEX_FILE, auth_state  # noqa: E402

def audit_html_dom():
    print("==================================================")
    print("1. AUDITING HTML DOM ID CONSISTENCY")
    print("==================================================")
    with open(os.path.join(ROOT, INDEX_FILE), "r", encoding="utf-8") as f:
        html = f.read()

    # Find IDs referenced in JS
    js_refs = set(re.findall(r"\$\(['\"]([a-zA-Z0-9_-]+)['\"]", html))
    # Find IDs defined in HTML elements
    html_ids = set(re.findall(r'id=["\']([a-zA-Z0-9_-]+)["\']', html))

    missing = [r for r in js_refs if r not in html_ids]
    print(f"Referenced DOM IDs in JS: {len(js_refs)}")
    print(f"Declared DOM IDs in HTML: {len(html_ids)}")
    if missing:
        print(f"WARNING: Missing DOM IDs referenced in JS: {missing}")
    else:
        print("PASS: All referenced DOM IDs exist in HTML elements.")
    assert len(missing) == 0, f"Found missing DOM IDs: {missing}"

def audit_simulation_algorithms():
    print("\n==================================================")
    print("2. AUDITING SIMULATION ENGINE & QUANTITATIVE MATH")
    print("==================================================")

    # Test Case A: BUY direction ladder with multiple target hits, resets, gap downs, and max position cap
    candles_buy = [
        {'dt': datetime.datetime(2026, 3, 1, 9, 15), 'o': 100.0, 'h': 101.0, 'l': 98.0, 'c': 99.0, 'v': 1000}, # Hits initial anchor 100
        {'dt': datetime.datetime(2026, 3, 1, 9, 16), 'o': 99.0, 'h': 106.0, 'l': 99.0, 'c': 105.5, 'v': 1200}, # Hits target 100+5 = 105, triggers squareoff, queues next at 105-5=100
        {'dt': datetime.datetime(2026, 3, 1, 9, 17), 'o': 105.0, 'h': 106.0, 'l': 93.0, 'c': 94.0, 'v': 1500}, # Downward move: enters 100, 95
        {'dt': datetime.datetime(2026, 3, 1, 9, 18), 'o': 94.0, 'h': 101.0, 'l': 94.0, 'c': 100.5, 'v': 1100}, # Rebound: hits target for 95 (100) and 100 (105)
        {'dt': datetime.datetime(2026, 3, 1, 9, 19), 'o': 100.5, 'h': 102.0, 'l': 100.0, 'c': 101.0, 'v': 900}
    ]

    config_buy = {'dir': 'buy', 'step': 5.0, 'square': 5.0, 'per_qty': 50, 'total_qty': 200, 'max_lots': 4, 'cost': 15.0}
    res_buy = run_engine(candles_buy, config_buy, anchor=100.0)
    print(f"BUY Simulation Result -> Trades: {len(res_buy['trades'])}, Realised: ₹{res_buy['net_realised']:.2f}, Max Drawdown: ₹{res_buy['max_dd']:.2f}")
    assert len(res_buy['trades']) >= 2, "Buy ladder must complete profitable scalps"

    # Test Case B: SHORT direction ladder
    candles_short = [
        {'dt': datetime.datetime(2026, 3, 1, 9, 15), 'o': 100.0, 'h': 102.0, 'l': 99.0, 'c': 101.0, 'v': 1000}, # Hits short anchor 100
        {'dt': datetime.datetime(2026, 3, 1, 9, 16), 'o': 101.0, 'h': 101.5, 'l': 94.0, 'c': 94.5, 'v': 1200}, # Drops to 94: hits cover target 100-5=95, queues next short at 95+5=100
        {'dt': datetime.datetime(2026, 3, 1, 9, 17), 'o': 95.0, 'h': 107.0, 'l': 95.0, 'c': 106.0, 'v': 1500}, # Rises to 107: enters short at 100, 105
        {'dt': datetime.datetime(2026, 3, 1, 9, 18), 'o': 106.0, 'h': 106.0, 'l': 98.0, 'c': 99.0, 'v': 1100}  # Drops to 98: covers 105 target at 100
    ]
    config_short = {'dir': 'short', 'step': 5.0, 'square': 5.0, 'per_qty': 50, 'total_qty': 200, 'max_lots': 4, 'cost': 15.0}
    res_short = run_engine(candles_short, config_short, anchor=100.0)
    print(f"SHORT Simulation Result -> Trades: {len(res_short['trades'])}, Realised: ₹{res_short['net_realised']:.2f}, Max Drawdown: ₹{res_short['max_dd']:.2f}")
    assert len(res_short['trades']) >= 2, "Short ladder must complete profitable scalps"

    # Test Case C: Zero Division & Edge Conditions Test (Zero trades, zero drawdown, zero capital)
    empty_res = run_engine([], config_buy, anchor=100.0)
    assert empty_res['win_rate'] == 0.0
    assert empty_res['recovery_factor'] == 0.0
    assert empty_res['return_on_capital'] == 0.0
    print("PASS: Mathematical models, order matching, and zero-division fallbacks verified.")

def run_engine(candles, config, anchor=100.0):
    positions = []
    pending_levels = [anchor]
    trades = []
    max_qty_used = 0
    cumulative_qty = 0
    last_square_off = None
    grot_peak = 0.0
    max_grot_dd = 0.0
    peak_capital = 0.0

    def level_key(lvl): return round(float(lvl), 6)
    def net_qty(): return sum(p['qty'] for p in positions)
    def open_pnl(price): return sum((price - p['entry']) * (1 if p['side'] == 'buy' else -1) * p['qty'] for p in positions)
    def queue_level(lvl):
        key = level_key(lvl)
        if not any(level_key(x) == key for x in pending_levels) and not any(level_key(p['entry']) == key for p in positions):
            pending_levels.append(lvl)

    def add_entry(level, b):
        nonlocal max_qty_used, cumulative_qty, peak_capital
        room = config['total_qty'] - net_qty()
        qty = config['per_qty']
        if room < qty or any(level_key(p['entry']) == level_key(level) for p in positions):
            return False
        positions.append({'side': config['dir'], 'entry': level, 'entry_time': b['dt'], 'qty': qty, 'level': level})
        cumulative_qty += qty
        max_qty_used = max(max_qty_used, net_qty())
        curr_cap = sum(p['entry'] * p['qty'] for p in positions)
        peak_capital = max(peak_capital, curr_cap)
        queue_level(level - config['step'] if config['dir'] == 'buy' else level + config['step'])
        return True

    def close_one(p, price, b, reason):
        gross = (price - p['entry']) * (1 if p['side'] == 'buy' else -1) * p['qty']
        net = gross - config['cost']
        trades.append({**p, 'exit': price, 'exit_time': b['dt'], 'gross': gross, 'net': net, 'reason': reason})
        positions.remove(p)

    def process_targets(b):
        nonlocal last_square_off, pending_levels
        blocked = set()
        latest_target = None
        for p in list(positions):
            target = p['entry'] + config['square'] if p['side'] == 'buy' else p['entry'] - config['square']
            hit = b['h'] >= target if p['side'] == 'buy' else b['l'] <= target
            if hit:
                if latest_target is None:
                    latest_target = target
                else:
                    latest_target = max(latest_target, target) if config['dir'] == 'buy' else min(latest_target, target)
                close_one(p, target, b, 'STEP SQUARE-OFF')
        if latest_target is not None:
            last_square_off = latest_target
            pending_levels = []
            chase = latest_target - config['step'] if config['dir'] == 'buy' else latest_target + config['step']
            while any(level_key(p['entry']) == level_key(chase) for p in positions):
                chase = chase - config['step'] if config['dir'] == 'buy' else chase + config['step']
            blocked.add(level_key(chase))
            queue_level(chase)
        return blocked

    def process_entries(b, blocked):
        safety = 0
        while net_qty() + config['per_qty'] <= config['total_qty'] and safety < config['max_lots'] * 3:
            safety += 1
            curr_pending = [lvl for lvl in pending_levels if not any(level_key(p['entry']) == level_key(lvl) for p in positions)]
            curr_pending.sort(reverse=(config['dir'] == 'buy'))
            target_lvl = None
            for lvl in curr_pending:
                if level_key(lvl) not in blocked and (b['l'] <= lvl if config['dir'] == 'buy' else b['h'] >= lvl):
                    target_lvl = lvl
                    break
            if target_lvl is None:
                break
            pending_levels.remove(target_lvl)
            if not add_entry(target_lvl, b):
                break

    for b in candles:
        blocked = process_targets(b)
        process_entries(b, blocked)
        cur_grot = sum(t['net'] for t in trades) + open_pnl(b['c'])
        grot_peak = max(grot_peak, cur_grot)
        max_grot_dd = max(max_grot_dd, grot_peak - cur_grot)

    net_realised = sum(t['net'] for t in trades)
    wins = len([t for t in trades if t['net'] > 0])
    win_rate = (wins / len(trades) * 100.0) if trades else 0.0
    return_on_cap = (net_realised / peak_capital * 100.0) if peak_capital > 0 else 0.0
    recovery_factor = (net_realised / max_grot_dd) if max_grot_dd > 0 else 0.0

    return {
        'trades': trades,
        'positions': positions,
        'net_realised': net_realised,
        'max_qty_used': max_qty_used,
        'max_dd': max_grot_dd,
        'win_rate': win_rate,
        'return_on_capital': return_on_cap,
        'recovery_factor': recovery_factor
    }

def audit_flask_server():
    print("\n==================================================")
    print("3. AUDITING FLASK BACKEND & SERVERLESS API ENDPOINTS")
    print("==================================================")
    client = app.test_client()

    # 1. Root route
    r = client.get('/')
    assert r.status_code == 200, "Root must return 200"

    # 2. Client IP detection
    r = client.get('/api/client_ip')
    assert r.status_code == 200, "Client IP must return 200"
    assert "ip" in r.get_json(), "Must contain ip"

    # 3. Auth status endpoint. It is unauthenticated, so it may only publish
    #    booleans and non-sensitive identifiers -- never a secret, the live OTP,
    #    or the registered mobile number.
    r = client.get('/api/auth/status')
    assert r.status_code == 200, "Status must return 200"
    payload = r.get_json()
    forbidden = {"api_key", "session_id", "access_token", "last_otp", "otp", "mobile_no", "password"}
    exposed = forbidden.intersection(payload.keys())
    assert not exposed, f"/api/auth/status leaks sensitive fields: {sorted(exposed)}"

    # 4. Scrip search
    r = client.get('/api/scrip/search?query=reliance')
    assert r.status_code == 200
    res = r.get_json()
    assert res['count'] >= 1
    assert res['results'][0]['symbol'] == 'RELIANCE'

    # 5. Missing auth on historical. Isolated from whatever credentials this
    #    machine happens to hold, so the guard is always genuinely exercised and
    #    the request can never escape to the live Choice gateway.
    saved_state = dict(auth_state)
    saved_env = {k: os.environ.pop(k) for k in
                 ("CHOICE_VENDOR_ID", "CHOICE_API_KEY", "CHOICE_MOBILE",
                  "CHOICE_SESSION_ID", "CHOICE_ACCESS_TOKEN")
                 if k in os.environ}
    try:
        for key in ("vendor_id", "api_key", "mobile_no", "session_id", "access_token"):
            auth_state[key] = ""
        auth_state["logged_in"] = False
        r = client.post('/api/historical', json={"token": 26000, "from_date": "2026-03-01", "to_date": "2026-03-02"})
        assert r.status_code == 401, "Historical without auth should return 401"
    finally:
        auth_state.clear()
        auth_state.update(saved_state)
        os.environ.update(saved_env)

    # 6. Static catch-all must never leak source, secrets or session files
    for leak in ('server.py', 'secrets.json', '.choice_session.json', 'requirements.txt'):
        r = client.get('/' + leak)
        assert r.status_code == 404, f"Static route leaked {leak} (HTTP {r.status_code})"

    # 7. Secrets bootstrap page is reachable (the login modal links to it)
    r = client.get('/admin/bootstrap')
    assert r.status_code == 200, "/admin/bootstrap must render the secrets form"
    r = client.post('/admin/bootstrap', json={"vendor_id": "", "api_key": "", "mobile_no": ""})
    assert r.status_code == 400, "/admin/bootstrap must reject incomplete credentials"

    # 8. Date parser calculation check
    sec1 = parse_date_to_1980_seconds("2026-01-01")
    sec2 = parse_date_to_1980_seconds("2026-01-01 09:15:00")
    assert sec2 > sec1
    assert sec2 - sec1 == 9 * 3600 + 15 * 60

    print("PASS: All Flask endpoints, date parsers, and error guards functioning properly.")

def audit_credential_persistence():
    """
    The two credential lifetimes must stay separate. A session file from an
    earlier day has to keep yielding vendor_id / api_key / mobile_no, otherwise
    the user is forced through /admin/bootstrap again every single calendar day
    before they can even reach the login button.
    """
    print("\n==================================================")
    print("4. AUDITING CREDENTIAL LIFETIME SEPARATION")
    print("==================================================")
    import json
    import tempfile
    import datetime as _dt
    import server

    tmp = tempfile.mkdtemp()
    saved = (server.SESSION_FILE, server.SECRETS_FILE, dict(server.auth_state))

    def reset():
        for k in server.LONG_LIVED_KEYS + ("session_id", "access_token"):
            server.auth_state[k] = ""
        server.auth_state["base_url"] = server.DEFAULT_BASE_URL
        server.auth_state["logged_in"] = False

    def write(name, obj):
        path = os.path.join(tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        return path

    try:
        server.SECRETS_FILE = os.path.join(tmp, "absent.json")

        # A session file from a previous day
        server.SESSION_FILE = write("stale.json", {
            "date": "2020-01-01", "vendor_id": "V1", "api_key": "K1",
            "mobile_no": "M1", "session_id": "SESSION_OLD", "access_token": "TOKEN_OLD"
        })
        reset()
        server.load_secrets_from_file()
        fresh = server.load_session_from_file()
        assert server.auth_state["api_key"] == "K1", "stale session file must still yield the api key"
        assert server.auth_state["vendor_id"] == "V1", "stale session file must still yield the vendor id"
        assert server.auth_state["mobile_no"] == "M1", "stale session file must still yield the mobile number"
        assert not server.auth_state["session_id"], "an expired session id must NOT be restored"
        assert fresh is False, "a stale file must not report a live session"
        print("PASS: expired session dropped, long-lived credentials retained.")

        # Today's session file
        server.SESSION_FILE = write("fresh.json", {
            "date": _dt.date.today().isoformat(), "vendor_id": "V1", "api_key": "K1",
            "mobile_no": "M1", "session_id": "SESSION_NEW", "access_token": "TOKEN_NEW"
        })
        reset()
        assert server.load_session_from_file() is True
        assert server.auth_state["session_id"] == "SESSION_NEW"
        print("PASS: same-day session restored without re-login.")

        # A rotated key in secrets.json must not be overwritten by the older copy
        server.SECRETS_FILE = write("secrets.json", {
            "vendor_id": "V2", "api_key": "K_ROTATED", "mobile_no": "M2"
        })
        server.SESSION_FILE = write("stale2.json", {
            "date": "2020-01-01", "vendor_id": "V1", "api_key": "K_STALE",
            "mobile_no": "M1", "session_id": "SESSION_OLD"
        })
        reset()
        server.load_secrets_from_file()
        server.load_session_from_file()
        assert server.auth_state["api_key"] == "K_ROTATED", "secrets.json must outrank the session file copy"
        print("PASS: rotated credentials outrank the cached session copy.")
    finally:
        server.SESSION_FILE, server.SECRETS_FILE = saved[0], saved[1]
        server.auth_state.clear()
        server.auth_state.update(saved[2])

def calculate_trade_cost(side, entry, exit_price, qty, config):
    model = config.get('cost_model', 'fo_futures')
    if model == 'zero':
        return 0.0
    if model == 'flat_custom':
        return float(max(0.0, config.get('cost', 0.0)))

    buy_price = entry if side == 'buy' else exit_price
    sell_price = exit_price if side == 'buy' else entry
    turnover_buy = buy_price * qty
    turnover_sell = sell_price * qty
    total_turnover = turnover_buy + turnover_sell

    base_brok = float(max(0.0, config.get('brokerage_rate', 20.0)))
    if model == 'cash_intra':
        brokerage_buy = min(base_brok, turnover_buy * 0.0003)
        brokerage_sell = min(base_brok, turnover_sell * 0.0003)
    else:
        brokerage_buy = base_brok
        brokerage_sell = base_brok
    brokerage = brokerage_buy + brokerage_sell

    stt = 0.0
    if model == 'fo_futures':
        stt = turnover_sell * 0.0002
    elif model == 'fo_options':
        stt = turnover_sell * 0.001
    elif model == 'cash_intra':
        stt = turnover_sell * 0.00025

    txn = 0.0
    if model == 'fo_futures':
        txn = total_turnover * 0.0000173
    elif model == 'fo_options':
        txn = total_turnover * 0.00035
    elif model == 'cash_intra':
        txn = total_turnover * 0.0000297

    sebi = total_turnover * 0.000001
    gst = (brokerage + txn + sebi) * 0.18

    stamp = 0.0
    if model == 'fo_futures':
        stamp = turnover_buy * 0.00002
    elif model in ('fo_options', 'cash_intra'):
        stamp = turnover_buy * 0.00003

    total = brokerage + stt + txn + sebi + gst + stamp
    return round(total, 2)

def audit_tax_and_cost_models():
    print("\n==================================================")
    print("5. AUDITING INDIAN TAX & STATUTORY COST MODEL MATH")
    print("==================================================")
    
    # Test F&O Futures model: 65 qty @ 24000 entry, 24050 exit (₹3250 gross profit)
    c_fut = {'cost_model': 'fo_futures', 'brokerage_rate': 20.0}
    cost_fut = calculate_trade_cost('buy', 24000.0, 24050.0, 65, c_fut)
    # Expected hand-calculated:
    # buy_turnover: 1560000, sell_turnover: 1563250, total: 3123250
    # brok: 40.0, stt: 312.65, txn: 54.032225, sebi: 3.12325, gst: 17.4879855, stamp: 31.20 -> 458.49
    assert abs(cost_fut - 458.49) < 0.02, f"Futures cost mismatch: got {cost_fut}, expected 458.49"
    print(f"PASS: F&O Futures tax calculation verified (Cost: ₹{cost_fut:.2f} on ₹3.12M turnover).")

    # Test Cash Intraday model: small trade 10 shares @ ₹100 entry, ₹105 exit
    c_cash = {'cost_model': 'cash_intra', 'brokerage_rate': 20.0}
    cost_cash = calculate_trade_cost('buy', 100.0, 105.0, 10, c_cash)
    # turnover buy: 1000, sell: 1050. Brok is 0.03% (₹0.30 buy, ₹0.315 sell), NOT ₹20.
    assert cost_cash < 2.0, f"Cash intraday must apply lower of 0.03% and ₹20: got {cost_cash}"
    print(f"PASS: Cash intraday 0.03% vs ₹20 brokerage cap verified (Cost: ₹{cost_cash:.2f}).")

    # Test Zero and Flat models
    assert calculate_trade_cost('buy', 100.0, 105.0, 10, {'cost_model': 'zero'}) == 0.0
    assert calculate_trade_cost('buy', 100.0, 105.0, 10, {'cost_model': 'flat_custom', 'cost': 15.5}) == 15.5
    print("PASS: Zero and Flat custom cost overrides verified.")

def audit_multi_target_simultaneous_fill():
    print("\n==================================================")
    print("6. AUDITING MULTI-TARGET EXTREME CHASE RESOLUTION")
    print("==================================================")
    # A scenario where multiple positions are held and hit target on the same candle:
    # 3 BUY positions entered at 100, 95, 90.
    # Step = 5, Square = 5. Targets: 105, 100, 95.
    # Violent bar hits High 107. All 3 positions hit target!
    # Extreme target must resolve to 105 (highest exit), queuing next chase entry at 105 - 5 = 100.
    candles = [
        {'dt': datetime.datetime(2026, 3, 1, 9, 15), 'o': 100.0, 'h': 101.0, 'l': 90.0, 'c': 90.5, 'v': 1000}, # Enters 100, 95, 90
        {'dt': datetime.datetime(2026, 3, 1, 9, 16), 'o': 91.0, 'h': 107.0, 'l': 91.0, 'c': 106.0, 'v': 2000},  # Violent candle: exits all 3!
        {'dt': datetime.datetime(2026, 3, 1, 9, 17), 'o': 106.0, 'h': 106.0, 'l': 99.5, 'c': 101.0, 'v': 1000}  # Dips to 99.5: fills next chase at 100
    ]
    cfg = {'dir': 'buy', 'step': 5.0, 'square': 5.0, 'per_qty': 50, 'total_qty': 250, 'max_lots': 5, 'cost': 10.0}
    res = run_engine(candles, cfg, anchor=100.0)
    assert len(res['trades']) == 3, f"Expected 3 completed scalp trades, got {len(res['trades'])}"
    # Verify open positions: the 4th trade should be an open entry at 100
    assert len(res['positions']) == 1, f"Expected 1 open chase position at 100, got {len(res['positions'])}"
    assert res['positions'][0]['entry'] == 100.0, f"Chase entry should be 100, got {res['positions'][0]['entry']}"
    print(f"PASS: Simultaneous multi-target resolution properly anchored next chase to 100.0.")

if __name__ == "__main__":
    audit_html_dom()
    audit_simulation_algorithms()
    audit_flask_server()
    audit_credential_persistence()
    audit_tax_and_cost_models()
    audit_multi_target_simultaneous_fill()
    print("\n==================================================")
    print("🎉 DEEP SYSTEM AUDIT COMPLETE — ALL CHECKS PASSED!")
    print("==================================================")
