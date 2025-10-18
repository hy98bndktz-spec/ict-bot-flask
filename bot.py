# bot.py
"""
Telegram signal bot (ICT / Smart Money style) — 5m TF
Assets: XAUUSD (Gold), BTCUSD (Bitcoin), EURUSD
Behavior:
 - Prefer MetaTrader5 for quotes if available (optional)
 - Fallback: Binance for BTC, yfinance for XAU/EUR
 - Sends BUY/SELL signals to Telegram according to simple ICT rules:
    - Market structure (HH/LL) + EMA crossover + RSI confirmation
 - Keeps a small "de-dup" state so same signal is not spammed repeatedly
 - Keep-alive via Flask for Render
"""

import os
import time
import json
import requests
from datetime import datetime, timezone
import threading

import pandas as pd
import pandas_ta as ta

# optional libraries (MetaTrader5 may not be installed on Render)
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except Exception:
    MT5_AVAILABLE = False

# -------------------------
# CONFIG (يمكن وضع هذه القيم كـ Environment Variables على Render)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8461165121:AAG3rQ5GFkv-Jmw-6GxHaQ56p-tgXLopp_A")
CHAT_ID = os.environ.get("CHAT_ID", "690864747")
TIMEFRAME = "5m"
FETCH_LIMIT = int(os.environ.get("FETCH_LIMIT", 500))
ALIVE_NOTIFY = os.environ.get("ALIVE_NOTIFY", "1")  # "1" -> send start message

# MT5 credentials (optional, only used if you enable MT5 and supply env vars later)
MT5_LOGIN = os.environ.get("MT5_LOGIN")       # e.g. "1234567"
MT5_PASSWORD = os.environ.get("MT5_PASSWORD")
MT5_SERVER = os.environ.get("MT5_SERVER")     # broker server name (optional)

# telegram
TG_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

# files / state
LAST_SIGNAL_FILE = "last_signals.json"  # persistence across restarts (optional)

# -------------------------
# Flask keep-alive for Render
from flask import Flask
app = Flask(__name__)

@app.route("/")
def home():
    return "ICT Smart Money Bot (5m) — running"

def send_telegram(text):
    try:
        payload = {"chat_id": CHAT_ID, "text": text}
        r = requests.post(TG_URL, json=payload, timeout=10)
        if not r.ok:
            print("Telegram API error:", r.status_code, r.text)
    except Exception as e:
        print("Telegram send error:", e)

def now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

# -------------------------
# Helpers: persist last signals to avoid spam
def load_last_signals():
    try:
        if os.path.exists(LAST_SIGNAL_FILE):
            with open(LAST_SIGNAL_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_last_signals(d):
    try:
        with open(LAST_SIGNAL_FILE, "w") as f:
            json.dump(d, f)
    except Exception as e:
        print("save_last_signals error:", e)

last_signals = load_last_signals()  # { "XAUUSD": "BUY", ... }

# -------------------------
# FETCHERS
# - Attempt MT5 if available and configured
# - Fallback to Binance / yfinance

def fetch_mt5_ohlc(symbol, timeframe_minutes=5, bars=500):
    """
    Return DataFrame with columns open, high, low, close, volume using MT5.
    Symbol format: platform symbol as in MT5 (e.g. "XAUUSD", "BTCUSD" depending on broker)
    Requires MetaTrader5 module and MT5 connection set up.
    """
    if not MT5_AVAILABLE:
        return pd.DataFrame()
    try:
        # initialize if needed
        if not mt5.initialize():
            # try to initialize with server/login if env provided
            if MT5_LOGIN and MT5_PASSWORD and MT5_SERVER:
                mt5.shutdown()
                ok = mt5.initialize(login=int(MT5_LOGIN), password=MT5_PASSWORD, server=MT5_SERVER)
                if not ok:
                    print("MT5 initialize with credentials failed")
                    return pd.DataFrame()
            else:
                print("MT5 not initialized and no credentials")
                return pd.DataFrame()
        # map minutes to mt5 timeframe
        tf_map = {1: mt5.TIMEFRAME_M1, 5: mt5.TIMEFRAME_M5, 15: mt5.TIMEFRAME_M15, 30: mt5.TIMEFRAME_M30, 60: mt5.TIMEFRAME_H1}
        tf = tf_map.get(timeframe_minutes, mt5.TIMEFRAME_M5)
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, bars)
        if rates is None or len(rates) == 0:
            return pd.DataFrame()
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df = df.rename(columns={'time':'open_time', 'tick_volume':'volume', 'close':'close', 'open':'open', 'high':'high', 'low':'low'})
        df.set_index('open_time', inplace=True)
        df = df[['open','high','low','close','volume']]
        return df
    except Exception as e:
        print("MT5 fetch error:", e)
        return pd.DataFrame()

def fetch_binance_klines(symbol, interval="5m", limit=500):
    try:
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        if not isinstance(data, list) or len(data) == 0:
            return pd.DataFrame()
        df = pd.DataFrame(data, columns=[
            "open_time","open","high","low","close","volume",
            "close_time","quote_asset_volume","num_trades",
            "taker_buy_base","taker_buy_quote","ignore"
        ])
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df.set_index("open_time", inplace=True)
        for c in ["open","high","low","close","volume"]:
            df[c] = df[c].astype(float)
        return df[["open","high","low","close","volume"]]
    except Exception as e:
        print("Binance fetch error:", e)
        return pd.DataFrame()

def fetch_yfinance_klines(ticker, interval="5m", period="2d"):
    try:
        import yfinance as yf
        df = yf.download(tickers=ticker, period=period, interval=interval, progress=False)
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.dropna()
        df.index = pd.to_datetime(df.index)
        df = df.rename(columns={"Open":"open","High":"high","Low":"low","Close":"close","Volume":"volume"})
        return df[["open","high","low","close","volume"]]
    except Exception as e:
        print("yfinance fetch error:", e)
        return pd.DataFrame()

# unified fetch function preferring MT5
def fetch_ohlc_for(symbol_key, use_mt5_symbol=None):
    """
    symbol_key: logical key like "XAUUSD", "BTCUSD", "EURUSD"
    use_mt5_symbol: if given, try MT5 with that symbol string
    """
    # Try MT5 first if configured
    if use_mt5_symbol and MT5_AVAILABLE:
        df = fetch_mt5_ohlc(use_mt5_symbol, timeframe_minutes=5, bars=FETCH_LIMIT)
        if df is not None and not df.empty:
            return df

    # Fallbacks
    if symbol_key == "BTCUSD":
        # use Binance symbol BTCUSDT
        return fetch_binance_klines("BTCUSDT", interval="5m", limit=FETCH_LIMIT)
    elif symbol_key == "XAUUSD":
        # yfinance gold futures GC=F
        return fetch_yfinance_klines("GC=F", interval="5m", period="2d")
    elif symbol_key == "EURUSD":
        return fetch_yfinance_klines("EURUSD=X", interval="5m", period="2d")
    else:
        return pd.DataFrame()

# -------------------------
# ANALYSIS / ICT-like heuristics
def compute_indicators(df):
    df = df.copy()
    if len(df) < 10:
        return df
    df["EMA12"] = ta.ema(df["close"], length=12)
    df["EMA26"] = ta.ema(df["close"], length=26)
    df["RSI14"] = ta.rsi(df["close"], length=14)
    return df

def detect_structure(df):
    """
    Simple HH/LL structure detection using last swings.
    Returns: "uptrend" / "downtrend" / "sideways" / "insufficient"
    """
    if df is None or len(df) < 6:
        return "insufficient"
    highs = df['high'].values
    lows = df['low'].values
    try:
        last_high = float(highs[-1])
        prev_high = float(highs[-3])
        last_low = float(lows[-1])
        prev_low = float(lows[-3])
        if last_high > prev_high and last_low > prev_low:
            return "uptrend"
        elif last_high < prev_high and last_low < prev_low:
            return "downtrend"
        else:
            return "sideways"
    except Exception as e:
        print("detect_structure error:", e)
        return "insufficient"

def detect_order_block_simple(df):
    """
    Very simple heuristic OB: find last bearish candle followed by rally (bullish OB),
    or last bullish candle followed by drop (bearish OB). Returns dict or None.
    """
    try:
        for i in range(len(df)-4, 1, -1):
            prev = df.iloc[i-1]
            cur = df.iloc[i]
            nxt = df.iloc[i+1] if i+1 < len(df) else None
            # bullish OB candidate
            if prev["close"] < prev["open"] and nxt is not None:
                future_highs = df['high'].iloc[i+1:i+4]
                if any(h > prev['high'] for h in future_highs):
                    return {"type":"bullish", "high": float(prev['high']), "low": float(prev['low']), "time": str(prev.name)}
            # bearish OB candidate
            if prev["close"] > prev["open"] and nxt is not None:
                future_lows = df['low'].iloc[i+1:i+4]
                if any(l < prev['low'] for l in future_lows):
                    return {"type":"bearish","high": float(prev['high']), "low": float(prev['low']), "time": str(prev.name)}
    except Exception as e:
        print("detect_order_block_simple error:", e)
    return None

def generate_signal_from_df(df):
    df = compute_indicators(df)
    if df is None or df.empty or len(df) < 20:
        return {"signal":"HOLD","reason":"insufficient_data"}
    last = df.iloc[-1]
    ema12 = last.get("EMA12")
    ema26 = last.get("EMA26")
    rsi = last.get("RSI14")
    price = float(last["close"])
    structure = detect_structure(df)
    ob = detect_order_block_simple(df)

    signal = "HOLD"
    reasons = []

    if pd.notna(ema12) and pd.notna(ema26) and pd.notna(rsi):
        # BUY logic (ICT-like)
        if (ema12 > ema26 or structure=="uptrend") and rsi < 70:
            # prefer OB if present
            if ob and ob.get("type")=="bullish" and price <= ob["high"] + 1.5 * (df["close"].diff().abs().mean()):
                signal = "BUY"
                reasons.append("Bullish OB + EMA/RSI")
            else:
                # fallback EMA confirmation
                if ema12 > ema26 and rsi < 60:
                    signal = "BUY"
                    reasons.append("EMA confirmation + RSI")
        # SELL logic
        if (ema12 < ema26 or structure=="downtrend") and rsi > 30:
            if ob and ob.get("type")=="bearish" and price >= ob["low"] - 1.5 * (df["close"].diff().abs().mean()):
                signal = "SELL"
                reasons.append("Bearish OB + EMA/RSI")
            else:
                if ema12 < ema26 and rsi > 40:
                    signal = "SELL"
                    reasons.append("EMA confirmation + RSI")

    return {
        "signal": signal,
        "price": price,
        "rsi": float(rsi) if pd.notna(rsi) else None,
        "structure": structure,
        "reasons": reasons,
        "time": now_str()
    }

# -------------------------
# Main analyze loop
ASSETS = [
    # (logical key, mt5_symbol_if_any)
    ("XAUUSD", "XAUUSD"),   # MT5 symbol example; fallback -> GC=F (yfinance)
    ("BTCUSD", "BTCUSD"),   # MT5 symbol example; fallback -> Binance BTCUSDT
    ("EURUSD", "EURUSD")    # MT5 symbol example; fallback -> EURUSD=X (yfinance)
]

def analyze_once():
    results = {}
    for key, mt5_sym in ASSETS:
        try:
            df = fetch_ohlc_for(key, use_mt5_symbol=mt5_sym)
            if df is None or df.empty:
                print(f"{now_str()} - No data for {key}")
                continue
            sig = generate_signal_from_df(df)
            results[key] = sig

            # avoid spamming same signal repeatedly:
            last = last_signals.get(key)
            if sig["signal"] != "HOLD":
                if last != sig["signal"]:
                    # send telegram message
                    txt = (
                        f"📊 ICT Smart Money Signal ({key})\n"
                        f"Time: {sig['time']}\n"
                        f"Price: {sig['price']:.4f}\n"
                        f"Signal: {sig['signal']}\n"
                        f"RSI: {sig['rsi']}\n"
                        f"Structure: {sig['structure']}\n"
                        f"Reason: {', '.join(sig['reasons'])}\n"
                        f"⚙️ Strategy: Michael ICT - Smart Money Concepts (5m)"
                    )
                    send_telegram(txt)
                    last_signals[key] = sig["signal"]
                    save_last_signals(last_signals)
                else:
                    print(f"{now_str()} - {key} same signal {sig['signal']} (suppressed)")
            else:
                # reset if HOLD (optionally clear last to allow re-alert later)
                # we keep last_signals to avoid immediate repeats
                print(f"{now_str()} - {key} HOLD")
        except Exception as e:
            err = f"⚠️ Error analyzing {key}: {e}"
            print(err)
            send_telegram(err)
    return results

# -------------------------
# Runner: thread loop + flask run
def run_loop_forever():
    # optional startup notify
    if ALIVE_NOTIFY == "1":
        send_telegram("🚀 ICT Smart Money Bot started (5m) — demo (prices prefer MT5 if available).")
    while True:
        analyze_once()
        # sleep 60 seconds so we catch 5m closes quickly
        time.sleep(60)

# -------------------------
if __name__ == "__main__":
    # start analysis thread
    t = threading.Thread(target=run_loop_forever, daemon=True)
    t.start()
    # run keep-alive web server (Render expects an open port)
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
