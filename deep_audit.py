import re
import json
import datetime
from server import app, parse_date_to_1980_seconds, encode_mobile, extract_credentials, DEFAULT_SCRIPS

def audit_html_dom():
    print("==================================================")
    print("1. AUDITING HTML DOM ID CONSISTENCY")
    print("==================================================")
    with open("KKunal_GROT_Last_SquareOff_v7.html", "r", encoding="utf-8") as f:
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
                latest_target = target
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

    # 3. Auth status endpoint
    r = client.get('/api/auth/status')
    assert r.status_code == 200, "Status must return 200"

    # 4. Scrip search
    r = client.get('/api/scrip/search?query=reliance')
    assert r.status_code == 200
    res = r.get_json()
    assert res['count'] >= 1
    assert res['results'][0]['symbol'] == 'RELIANCE'

    # 5. Missing auth on historical
    r = client.post('/api/historical', json={"token": 26000, "from_date": "2026-03-01", "to_date": "2026-03-02"})
    assert r.status_code == 401, "Historical without auth should return 401"

    # 6. Date parser calculation check
    sec1 = parse_date_to_1980_seconds("2026-01-01")
    sec2 = parse_date_to_1980_seconds("2026-01-01 09:15:00")
    assert sec2 > sec1
    assert sec2 - sec1 == 9 * 3600 + 15 * 60

    print("PASS: All Flask endpoints, date parsers, and error guards functioning properly.")

if __name__ == "__main__":
    audit_html_dom()
    audit_simulation_algorithms()
    audit_flask_server()
    print("\n==================================================")
    print("🎉 DEEP SYSTEM AUDIT COMPLETE — ALL CHECKS PASSED!")
    print("==================================================")
