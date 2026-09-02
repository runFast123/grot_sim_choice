import datetime
from server import app, parse_date_to_1980_seconds, encode_mobile, DEFAULT_SCRIPS

def run_simulation_logic_test():
    sample_bars = [
        {'dt': datetime.datetime(2026, 3, 1, 9, 15), 'o': 100.0, 'h': 105.0, 'l': 99.0, 'c': 101.0, 'v': 1000},
        {'dt': datetime.datetime(2026, 3, 1, 9, 16), 'o': 101.0, 'h': 102.0, 'l': 95.0, 'c': 96.0, 'v': 1200},
        {'dt': datetime.datetime(2026, 3, 1, 9, 17), 'o': 96.0, 'h': 102.0, 'l': 94.0, 'c': 102.0, 'v': 1500},
        {'dt': datetime.datetime(2026, 3, 1, 9, 18), 'o': 102.0, 'h': 108.0, 'l': 101.0, 'c': 107.0, 'v': 1100},
        {'dt': datetime.datetime(2026, 3, 1, 9, 19), 'o': 107.0, 'h': 110.0, 'l': 104.0, 'c': 105.0, 'v': 900}
    ]

    positions = []
    pending_levels = [100.0]
    trades = []
    max_qty_used = 0
    cumulative_qty = 0
    last_square_off = None
    config = {'dir': 'buy', 'step': 5.0, 'square': 5.0, 'per_qty': 50, 'total_qty': 250, 'max_lots': 5, 'cost': 20.0}

    def level_key(lvl): return round(float(lvl), 6)
    def net_qty(): return sum(p['qty'] for p in positions)
    def open_pnl(price): return sum((price - p['entry']) * (1 if p['side'] == 'buy' else -1) * p['qty'] for p in positions)
    def queue_level(lvl):
        key = level_key(lvl)
        if not any(level_key(x) == key for x in pending_levels) and not any(level_key(p['entry']) == key for p in positions):
            pending_levels.append(lvl)

    def add_entry(level, b):
        nonlocal max_qty_used, cumulative_qty
        room = config['total_qty'] - net_qty()
        qty = config['per_qty']
        if room < qty or any(level_key(p['entry']) == level_key(level) for p in positions):
            return False
        positions.append({'side': config['dir'], 'entry': level, 'entry_time': b['dt'], 'qty': qty, 'level': level})
        cumulative_qty += qty
        max_qty_used = max(max_qty_used, net_qty())
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

    for b in sample_bars:
        blocked = process_targets(b)
        process_entries(b, blocked)

    assert len(trades) > 0, "Should have executed at least one trade"
    assert max_qty_used <= config['total_qty'], "Quantity limit exceeded"
    print(f"Algorithm math test passed! Executed {len(trades)} trades. Peak qty: {max_qty_used}.")

def test_api_endpoints():
    client = app.test_client()
    
    # Check root route
    resp = client.get('/')
    assert resp.status_code == 200, "Root route should return 200"
    
    # Check status route
    resp = client.get('/api/auth/status')
    assert resp.status_code == 200, "Auth status should return 200"
    data = resp.get_json()
    assert 'logged_in' in data, "Auth status must have logged_in field"

    # Check scrip search route
    resp = client.get('/api/scrip/search?query=nifty')
    assert resp.status_code == 200, "Scrip search should return 200"
    results = resp.get_json().get('results', [])
    assert len(results) > 0, "NIFTY should be found in default scrips"

    # Check input validation
    resp = client.post('/api/auth/get_client_otp', json={})
    assert resp.status_code == 400, "Empty mobile should return 400"

    resp = client.post('/api/auth/validate', json={})
    assert resp.status_code == 400, "Empty OTP should return 400"

    resp = client.post('/api/historical', json={})
    assert resp.status_code == 400, "Missing token should return 400"
    
    print("All Flask API endpoint tests passed!")

if __name__ == "__main__":
    run_simulation_logic_test()
    test_api_endpoints()
    print("ALL TESTS COMPLETED SUCCESSFULLY!")
