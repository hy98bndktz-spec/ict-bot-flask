# bot.py
import os
import time
import json
import requests
import pandas as pd
import pandas_ta as ta
import yfinance as yf
from datetime import datetime, timezone

# -----------------------
# CONFIG - ضع القيم في Environment Variables (لا تضعها نصاً هنا)
# BOT_TOKEN و CHAT_ID في متغيرات بيئة على Render / Replit
TOKEN = "8461165121:AAG3rQ5GFkv-Jmw-6GxHaQ56p-tgXLopp_A"
CHAT_ID = "690864747"
# symbols to monitor
BINANCE_SYMBOL = "BTCUSDT"  # Bitcoin
YFINANCE_SYMBOL = "GC=F"    # Gold futures (Yahoo)
TIMEFRAME = "5m"            # 5 minutes
FETCH_LIMIT = 500           # عدد الشموع المسترجعة

# Risk sizing defaults (للتبليغ فقط، لا ينفذ أوامر)
RISK_PERCENT = 0.01  # 1% افتراضي (فقط للعرض)

# Files
SIGNAL_CSV = "signals_log.csv"
POSITIONS_CSV = "positions.csv"
STATE_FILE = "positions.json"

# check env
if not TOKEN or not CHAT_ID:
    print("ERROR: BOT_TOKEN or CHAT_ID not set in environment")
    raise SystemExit("Set BOT_TOKEN and CHAT_ID environment variables")

CHAT_ID = str(CHAT_ID)
TG_URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

# -----------------------
# UTILITIES
def send_telegram(text):
    try:
        payload = {"chat_id": CHAT_ID, "text": text}
        r = requests.post(TG_URL, json=payload, timeout=10)
        return r.ok
    except Exception as e:
        print("Telegram send error:", e)
        return False

def now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

# -----------------------
# FETCH DATA
def fetch_binance_klines(symbol, interval="5m", limit=500):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    r = requests.get(url, params=params, timeout=10)
    data = r.json()
    # each kline: [openTime, open, high, low, close, ... , closeTime, ...]
    df = pd.DataFrame(data, columns=[
        "open_time","open","high","low","close","volume",
        "close_time","quote_asset_volume","num_trades","taker_buy_base","taker_buy_quote","ignore"
    ])
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    df.set_index("open_time", inplace=True)
    for col in ["open","high","low","close","volume"]:
        df[col] = df[col].astype(float)
    return df[["open","high","low","close","volume"]]

def fetch_yfinance_klines(ticker, interval="5m", period="2d"):
    df = yf.download(tickers=ticker, period=period, interval=interval, progress=False)
    if df.empty:
        return df
    df = df.dropna()
    df.index = pd.to_datetime(df.index)
    df = df.rename(columns={"Open":"open","High":"high","Low":"low","Close":"close","Volume":"volume"})
    return df[["open","high","low","close","volume"]]

# -----------------------
# INDICATORS & ICT-like detection (heuristic)
def compute_indicators(df):
    df = df.copy()
    df["EMA12"] = ta.ema(df["close"], length=12)
    df["EMA26"] = ta.ema(df["close"], length=26)
    df["ATR14"] = ta.atr(df["high"], df["low"], df["close"], length=14)
    df["RSI14"] = ta.rsi(df["close"], length=14)
    return df

def detect_order_block_and_fvg(df):
    # heuristic: last bearish candle before rally -> bullish OB
    ob = None
    fvg = None
    # scan backwards
    for i in range(len(df)-4, 1, -1):
        prev = df.iloc[i-1]
        cur = df.iloc[i]
        nxt = df.iloc[i+1] if i+1 < len(df) else None
        # bullish OB: previous candle bearish and then price rallies above its high
        if prev['close'] < prev['open'] and nxt is not None:
            future_highs = df['high'].iloc[i+1:i+4]
            if any(h > prev['high'] for h in future_highs):
                ob = {"type":"bullish", "time": prev.name.isoformat(), "high": float(prev['high']), "low": float(prev['low'])}
                break
        # bearish OB
        if prev['close'] > prev['open'] and nxt is not None:
            future_lows = df['low'].iloc[i+1:i+4]
            if any(l < prev['low'] for l in future_lows):
                ob = {"type":"bearish", "time": prev.name.isoformat(), "high": float(prev['high']), "low": float(prev['low'])}
                break
    # FVG detection (simple): middle candle body not overlapping neighbors
    for i in range(len(df)-3, 0, -1):
        a = df.iloc[i-1]; b = df.iloc[i]; c = df.iloc[i+1]
        # bullish FVG example
        if b['close'] < b['open'] and c['open'] > a['close']:
            fvg = {"type":"bullish","from":a.name.isoformat(),"to":c.name.isoformat(),"low": float(a['close']),"high": float(c['open'])}
            break
        if b['close'] > b['open'] and c['open'] < a['close']:
            fvg = {"type":"bearish","from":a.name.isoformat(),"to":c.name.isoformat(),"high": float(a['close']),"low": float(c['open'])}
            break
    return ob, fvg

def detect_structure(df):
    # simple HH/LL detection using last swings
    highs = df['high']; lows = df['low']
    swings = []
    win = 3
    for i in range(win, len(df)-win):
        h = highs[i-win:i+win+1]
        l = lows[i-win:i+win+1]
        if highs[i] == h.max():
            swings.append(("H", df.index[i], highs[i]))
        if lows[i] == l.min():
            swings.append(("L", df.index[i], lows[i]))
    # decide
    struct = "uncertain"
    try:
        last = swings[-4:]
        highs_list = [s for s in last if s[0]=="H"]
        lows_list = [s for s in last if s[0]=="L"]
        if len(highs_list)>=2 and len(lows_list)>=2:
            if highs_list[-1][2] > highs_list[-2][2] and lows_list[-1][2] > lows_list[-2][2]:
                struct = "uptrend"
            elif highs_list[-1][2] < highs_list[-2][2] and lows_list[-1][2] < lows_list[-2][2]:
                struct = "downtrend"
            else:
                struct = "sideways"
    except:
        struct = "uncertain"
    return struct

# -----------------------
# SIGNAL RULES + position management
def generate_signal(df):
    df = compute_indicators(df)
    last = df.iloc[-1]
    ema12 = last["EMA12"]; ema26 = last["EMA26"]
    rsi = last["RSI14"]; atr = last["ATR14"]
    structure = detect_structure(df)
    ob, fvg = detect_order_block_and_fvg(df)
    price = float(last["close"])

    reasons = []
    signal = "HOLD"
    sl = None; tp = None

    # BUY conditions (heuristic)
    if (structure == "uptrend" or ema12 > ema26) and rsi < 70:
        if ob and ob["type"]=="bullish":
            # price near order block?
            if price <= ob["high"] + 1.5*atr:
                signal = "BUY"
                reasons.append("Touched bullish OB")
        if fvg and fvg["type"]=="bullish" and signal=="HOLD":
            if price <= fvg["high"] + 1.5*atr:
                signal = "BUY"
                reasons.append("Bullish FVG")
        # fallback EMA
        if signal=="HOLD" and ema12 > ema26 and rsi < 60:
            signal = "BUY"
            reasons.append("EMA confirmation")

    # SELL conditions
    if (structure == "downtrend" or ema12 < ema26) and rsi > 30:
        if ob and ob["type"]=="bearish":
            if price >= ob["low"] - 1.5*atr:
                signal = "SELL"
                reasons.append("Touched bearish OB")
        if fvg and fvg["type"]=="bearish" and signal=="HOLD":
            if price >= fvg["low"] - 1.5*atr:
                signal = "SELL"
                reasons.append("Bearish FVG")
        if signal=="HOLD" and ema12 < ema26 and rsi > 40:
            signal = "SELL"
            reasons.append("EMA confirmation")

    # compute SL/TP if signal generated
    if signal in ["BUY","SELL"]:
        # use ATR-based SL and TP for scalping (tight)
        atr_val = float(atr) if not pd.isna(atr) and atr>0 else (price*0.002)  # fallback 0.2%
        if signal=="BUY":
            sl = price - 1.2*atr_val
            tp = price + 2.0*atr_val   # RR = ~1.7
        else:
            sl = price + 1.2*atr_val
            tp = price - 2.0*atr_val

    return {
        "time": df.index[-1].isoformat(),
        "price": price,
        "signal": signal,
        "sl": sl,
        "tp": tp,
        "rsi": float(rsi) if not pd.isna(rsi) else None,
        "atr": float(df["ATR14"].iloc[-1]) if not pd.isna(df["ATR14"].iloc[-1]) else None,
        "structure": structure,
        "ob": ob,
        "fvg": fvg,
        "reasons": reasons
    }

# positions management
def load_positions():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return []

def save_positions(pos):
    with open(STATE_FILE, "w") as f:
        json.dump(pos, f, indent=2, default=str)

def append_csv(filename, row, header=None):
    df = pd.DataFrame([row])
    if not os.path.exists(filename):
        df.to_csv(filename, index=False)
    else:
        df.to_csv(filename, mode='a', header=False, index=False)

# -----------------------
# MAIN LOOP
def analyze_and_act():
    positions = load_positions()
    # SYMBOLS loop
    pairs = [
        ("BTC", fetch_binance_klines, {"symbol": BINANCE_SYMBOL}),
        ("GOLD", fetch_yfinance_klines, {"ticker": YFINANCE_SYMBOL})
    ]
    for name, fetcher, kw in pairs:
        try:
            if name=="BTC":
                df = fetcher(kw["symbol"], interval=TIMEFRAME, limit=FETCH_LIMIT)
            else:
                df = fetcher(kw["ticker"], interval=TIMEFRAME, period="2d")
            if df is None or df.empty:
                print(f"{now_str()} - No data for {name}")
                continue
            sig = generate_signal(df)
            sig["symbol"] = name
            sig["checked_at"] = now_str()

            # log signal
            append_csv(SIGNAL_CSV, {
                "timestamp": sig["time"],
                "checked_at": sig["checked_at"],
                "symbol": name,
                "price": sig["price"],
                "signal": sig["signal"],
                "sl": sig["sl"],
                "tp": sig["tp"],
                "structure": sig["structure"],
                "reasons": "|".join(sig["reasons"])
            })

            # act: open new position if signal and no existing same-direction position for symbol
            open_positions_for_symbol = [p for p in positions if p["symbol"]==name and p["status"]=="OPEN"]
            if sig["signal"] in ["BUY","SELL"] and len(open_positions_for_symbol)==0:
                # open
                pos = {
                    "symbol": name,
                    "opened_at": now_str(),
                    "entry_time": sig["time"],
                    "entry_price": sig["price"],
                    "side": sig["signal"],
                    "sl": sig["sl"],
                    "tp": sig["tp"],
                    "status": "OPEN",
                    "reasons": sig["reasons"]
                }
                positions.append(pos)
                save_positions(positions)
                # send entry message
                txt = (f"🔔 SIGNAL ENTRY ({name})\n"
                       f"Time: {sig['checked_at']}\n"
                       f"Side: {sig['signal']}\n"
                       f"Price: {sig['price']:.2f}\n"
                       f"SL: {sig['sl']:.4f} | TP: {sig['tp']:.4f}\n"
                       f"Structure: {sig['structure']}\n"
                       f"Reasons: {', '.join(sig['reasons'])}\n"
                       f"(TF: {TIMEFRAME})")
                send_telegram(txt)
                append_csv(POSITIONS_CSV, {
                    "symbol": name,
                    "opened_at": pos["opened_at"],
                    "side": pos["side"],
                    "entry_price": pos["entry_price"],
                    "sl": pos["sl"],
                    "tp": pos["tp"],
                    "status": pos["status"]
                })
            # check existing positions for exit (SL/TP hit or structure reverse)
            new_positions = []
            for p in positions:
                if p["symbol"] != name or p["status"] != "OPEN":
                    new_positions.append(p); continue
                current_price = sig["price"]
                if p["side"]=="BUY":
                    # TP
                    if current_price >= float(p["tp"]):
                        p["status"]="CLOSED"
                        p["closed_at"] = now_str()
                        p["closed_price"] = current_price
                        p["result"] = "TP"
                        send_telegram(f"✅ EXIT (TP) {p['symbol']} | Side: BUY | Price: {current_price:.2f} | Opened: {p['opened_at']}")
                    # SL
                    elif current_price <= float(p["sl"]):
                        p["status"]="CLOSED"
                        p["closed_at"] = now_str()
                        p["closed_price"] = current_price
                        p["result"] = "SL"
                        send_telegram(f"⛔ EXIT (SL) {p['symbol']} | Side: BUY | Price: {current_price:.2f} | Opened: {p['opened_at']}")
                    else:
                        new_positions.append(p)
                else:  # SELL
                    if current_price <= float(p["tp"]):
                        p["status"]="CLOSED"
                        p["closed_at"] = now_str()
                        p["closed_price"] = current_price
                        p["result"] = "TP"
                        send_telegram(f"✅ EXIT (TP) {p['symbol']} | Side: SELL | Price: {current_price:.2f} | Opened: {p['opened_at']}")
                    elif current_price >= float(p["sl"]):
                        p["status"]="CLOSED"
                        p["closed_at"] = now_str()
                        p["closed_price"] = current_price
                        p["result"] = "SL"
                        send_telegram(f"⛔ EXIT (SL) {p['symbol']} | Side: SELL | Price: {current_price:.2f} | Opened: {p['opened_at']}")
                    else:
                        new_positions.append(p)
            positions = new_positions
            save_positions(positions)
        except Exception as e:
            print("Error in analyze_and_act for", name, e)

# -----------------------
if __name__ == "__main__":
    send_telegram("🚀 ICT-scalper Bot started (5m). Running in demo mode. Remember: demo only.")
    # run loop every 60 seconds to catch 5m closes quickly
    while True:
        analyze_and_act()
        time.sleep(60)
