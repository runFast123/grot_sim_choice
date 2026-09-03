"""
Indian Stock Market & F&O Cost Engine (NSE / SEBI Statutory Rates).

Calculates exact Brokerage, STT/CTT, Exchange Turnover Charges, GST,
SEBI Turnover Charges, and Stamp Duty for scalping and algorithmic trades.
"""

from typing import Dict, Any

def calculate_trade_cost(
    side: str,
    entry: float,
    exit: float,
    qty: int,
    model: str = "fo_futures",
    base_brokerage: float = 20.0,
    custom_flat: float = 0.0
) -> Dict[str, Any]:
    """
    Calculate full statutory and brokerage costs for a round-trip trade.

    Supported models:
      - fo_futures: NSE Equity Futures (Brokerage + STT 0.02% on sell + Txn 0.00173% + GST 18% + Stamp 0.002% on buy)
      - fo_options: NSE Equity Options (Brokerage + STT 0.1% on sell premium + Txn 0.035% + GST 18% + Stamp 0.003% on buy)
      - cash_intra: NSE Cash Intraday (Brokerage + STT 0.025% on sell + Txn 0.00297% + GST 18% + Stamp 0.003% on buy)
      - flat_custom: Flat ₹ amount per round-trip trade
      - zero: Zero brokerage and zero statutory taxes
    """
    if model == "zero":
        return {
            "total_cost": 0.0,
            "brokerage": 0.0,
            "stt": 0.0,
            "exchange_txn": 0.0,
            "gst": 0.0,
            "sebi": 0.0,
            "stamp_duty": 0.0,
            "turnover_buy": 0.0,
            "turnover_sell": 0.0,
            "total_turnover": 0.0
        }

    if model == "flat_custom":
        cost = max(0.0, float(custom_flat))
        return {
            "total_cost": round(cost, 2),
            "brokerage": round(cost, 2),
            "stt": 0.0,
            "exchange_txn": 0.0,
            "gst": 0.0,
            "sebi": 0.0,
            "stamp_duty": 0.0,
            "turnover_buy": 0.0,
            "turnover_sell": 0.0,
            "total_turnover": 0.0
        }

    buy_price = entry if side.lower() == "buy" else exit
    sell_price = exit if side.lower() == "buy" else entry

    turnover_buy = buy_price * qty
    turnover_sell = sell_price * qty
    total_turnover = turnover_buy + turnover_sell

    # 1. Brokerage: ₹20 per executed order (Entry + Exit = 2 orders), or 0.03% whichever is lower
    per_order_brokerage = float(base_brokerage) if base_brokerage > 0 else 20.0
    brokerage_buy = min(per_order_brokerage, turnover_buy * 0.0003) if model == "cash_intra" else per_order_brokerage
    brokerage_sell = min(per_order_brokerage, turnover_sell * 0.0003) if model == "cash_intra" else per_order_brokerage
    brokerage = brokerage_buy + brokerage_sell

    # 2. STT (Securities Transaction Tax)
    if model == "fo_futures":
        stt = turnover_sell * 0.0002  # 0.02% on sell turnover
    elif model == "fo_options":
        stt = turnover_sell * 0.001   # 0.1% on sell premium
    elif model == "cash_intra":
        stt = turnover_sell * 0.00025 # 0.025% on sell turnover
    else:
        stt = 0.0

    # 3. Exchange Transaction Charges (NSE)
    if model == "fo_futures":
        exchange_txn = total_turnover * 0.0000173 # 0.00173% on turnover
    elif model == "fo_options":
        exchange_txn = total_turnover * 0.00035   # 0.035% on premium turnover
    elif model == "cash_intra":
        exchange_txn = total_turnover * 0.0000297 # 0.00297% on turnover
    else:
        exchange_txn = 0.0

    # 4. SEBI Turnover Charges: ₹10 per Crore = 0.0001% on total turnover
    sebi = total_turnover * 0.000001

    # 5. GST: 18% on (Brokerage + Exchange Txn + SEBI)
    gst = (brokerage + exchange_txn + sebi) * 0.18

    # 6. Stamp Duty: applied on Buy side turnover
    if model == "fo_futures":
        stamp_duty = turnover_buy * 0.00002 # 0.002% on buy side
    elif model in ("fo_options", "cash_intra"):
        stamp_duty = turnover_buy * 0.00003 # 0.003% on buy side
    else:
        stamp_duty = 0.0

    total_cost = brokerage + stt + exchange_txn + sebi + gst + stamp_duty

    return {
        "total_cost": round(total_cost, 2),
        "brokerage": round(brokerage, 2),
        "stt": round(stt, 2),
        "exchange_txn": round(exchange_txn, 2),
        "gst": round(gst, 2),
        "sebi": round(sebi, 2),
        "stamp_duty": round(stamp_duty, 2),
        "turnover_buy": round(turnover_buy, 2),
        "turnover_sell": round(turnover_sell, 2),
        "total_turnover": round(total_turnover, 2)
    }
