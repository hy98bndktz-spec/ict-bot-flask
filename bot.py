# bot.py
# ICT Smart Money signal sender (5m) - improved and robust version
# Note: Token/chat id included from user input. For security later move them to env vars.

import os
import time
import json
import requests
import pandas as pd
import pandas_ta as ta
import yfinance as yf
from datetime import datetime, timezone
from flask import Flask
import threading
import math
import traceback

# -----------------------
# CONFIG - (you provided token/id)
TOKEN = "8461165121:AAG3rQ5GFkv-Jmw-6GxHaQ56p-tgXLopp_A"
CHAT_ID = "690864747"

# Symbols
BINANCE_SYMBOL = "BTCUSDT"   # Binance symbol for BTC/USDT
YFINANCE_PRIMARY = "GC=F"    # Yahoo primary (Gold futures)
YFINANCE_FALLBACK = "XAUUSD=X"  # alternative symbol
TIMEFRAME = "5m"
FETCH_LIMIT = 500

# files (optional logging)
SIGNAL_CSV = "signals_log.csv"

# Telegram endpoint
TG_URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

# ensure token/chat set
if not TOKEN or not CHAT_ID:
    raise SystemExit("BOT token or CHAT_ID missing. Set them in the script or environment.")

CHAT_ID = str(CHAT_ID)

# -----------------------
# utils
def send_telegram(text):
    try:
        payload = {"chat_id": CHAT_ID, "text": text}
        r = requests.post(TG_URL, json=payload, timeout=10)
        if not r.ok:
            print("Telegram send failed:", r.status_code, r.text)
        return r.ok
    except Exception as e:
        print("Telegram send exception:", e)
        return False

def now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def append_csv(filename, row, header=None):
    try:
        df = pd.DataFrame([row])
        if not os.path.exists(filename):
            df.to_csv(filename, index=False)
        else:
            df.to_csv(filename, mode='a', header=False, index=False)
    except Exception as e:
        print("CSV append error:", e)

# -----------------------
# Fetchers
def fetch_binance_klines(symbol, interval="5m", limit=500):
    try:
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        df = pd.DataFrame(data, columns=[
            "open_time","open","high","low","close","volume",
            "close_time","quote_asset_volume","num_trades","taker_buy_base","taker_buy_quote","ignore"
        ])
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df.set_index("open_time", inplace=True)
        for c in ["open","high","low","close","volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df[["open","high","low","close","volume"]].dropna()
    except Exception as e:
        print(f"{now_str()} - Binance fetch error for {symbol}: {e}")
        return pd.DataFrame()

def fetch_yfinance_klines_try_symbols(tickers, interval="5m", period="2d"):
    # tickers: list of candidates
    for t in tickers:
        try:
            df = yf.download(tickers=t, period=period, interval=interval, progress=False)
            if df is None or df.empty:
                print(f"{now_str()} - yfinance returned empty for {t}")
                continue
            df = df.dropna()
            if df.empty:
                continue
            df.index = pd.to_datetime(df.index)
            df = df.rename(columns={"Open":"open","High":"high","Low":"low","Close":"close","Volume":"volume"})
            return df[["open","high","low","close","volume"]].dropna()
        except Exception as e:
            print(f"{now_str()} - yfinance error for {t}: {e}")
            continue
    return pd.DataFrame()

# -----------------------
# Indicators and helpers
def compute_indicators(df):
    df = df.copy()
    # ensure numeric
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    # minimal length check
    if len(df) < 20:
        return df
    try:
        df["EMA12"] = ta.ema(df["close"], length=12)
        df["EMA26"] = ta.ema(df["close"], length=26)
        df["ATR14"] = ta.atr(df["high"], df["low"], df["close"], length=14)
        df["RSI14"] = ta.rsi(df["close"], length=14)
    except Exception as e:
        print("Indicator compute error:", e)
    return df

def detect_structure(df):
    # robust: require at least 5 candles
    if len(df) < 5:
        return "uncertain"
    highs = df['high'].astype(float)
    lows = df['low'].astype(float)
    try:
        # use recent swings: compare current vs 3 candles ago
        curr_high = float(highs.iloc[-1])
        prev_high = float(highs.iloc[-3])
        curr_low = float(lows.iloc[-1])
        prev_low = float(lows.iloc[-3])
        if curr_high > prev_high and curr_low > prev_low:
            return "uptrend"
        elif curr_high < prev_high and curr_low < prev_low:
            return "downtrend"
        else:
            return "sideways"
    except Exception as e:
        print("detect_structure error:", e)
        return "uncertain"

def safe_scalar(x):
    # return scalar float or None
    try:
        if x is None:
            return None
        if isinstance(x, (float,int)):
            if math.isnan(x):
                return None
            return float(x)
        # handle numpy / pandas scalars
        return float(x)
    except:
        return None

# -----------------------
# Signal rules (ICT-ish heuristic)
def generate_signal(df):
    # df should already have indicators (or compute here)
    df = compute_indicators(df)
    if df is None or df.empty or len(df) < 20:
        return {"signal":"HOLD", "reason":"insufficient data", "price":None, "time": now_str()}

    last = df.iloc[-1]
    ema12 = safe_scalar(last.get("EMA12"))
    ema26 = safe_scalar(last.get("EMA26"))
    rsi = safe_scalar(last.get("RSI14"))
    atr = safe_scalar(last.get("ATR14"))
    price = safe_scalar(last.get("close"))

    structure = detect_structure(df)
    reasons = []
    signal = "HOLD"
    sl = tp = None

    # only act if we have both EMAs and RSI
    if ema12 is not None and ema26 is not None and rsi is not None and price is not None:
        # BUY logic
        if (structure == "uptrend" or ema12 > ema26) and rsi < 70:
            signal = "BUY"
            reasons.append("EMA and bias + RSI criteria")
        # SELL logic
        if (structure == "downtrend" or ema12 < ema26) and rsi > 30:
            # prefer SELL only if stronger bearish
            if signal == "BUY":
                # conflict - prefer hold
                signal = "HOLD"
                reasons.append("conflict between buy/sell - holding")
            else:
                signal = "SELL"
                reasons.append("EMA and bias + RSI criteria")

    # compute SL/TP if signal
    if signal in ("BUY","SELL"):
        atr_val = atr if atr is not None else max(0.002 * price, 0.5)
        if signal == "BUY":
            sl = price - 1.5 * atr_val
            tp = price + 3.0 * atr_val
        else:
            sl = price + 1.5 * atr_val
            tp = price - 3.0 * atr_val

    return {
        "time": now_str(),
        "price": price,
        "signal": signal,
        "sl": sl,
        "tp": tp,
        "rsi": rsi,
        "atr": atr,
        "structure": structure,
        "reasons": reasons
    }

# -----------------------
# Main analyzer (sends telegram messages)
def analyze_and_send():
    try:
        # list of assets: tuple(name, fetcher function, args)
        assets = [
            ("BTCUSDT", fetch_binance_klines, {"symbol": BINANCE_SYMBOL}),
            ("GOLD", fetch_yfinance_klines_try_symbols, {"tickers":[YFINANCE_PRIMARY, YFINANCE_FALLBACK], "interval":TIMEFRAME, "period":"2d"})
        ]
        for name, func, kwargs in assets:
            try:
                if name == "BTCUSDT":
                    df = func(kwargs["symbol"], interval=TIMEFRAME, limit=FETCH_LIMIT)
                else:
                    df = func(kwargs["tickers"], interval=TIMEFRAME, period=kwargs.get("period","2d"))
                if df is None or df.empty or len(df) < 10:
                    print(f"{now_str()} - No/insufficient data for {name}")
                    continue

                sig = generate_signal(df)
                sig["symbol"] = name

                # log
                append_csv(SIGNAL_CSV, {
                    "checked_at": now_str(),
                    "symbol": name,
                    "price": sig.get("price"),
                    "signal": sig.get("signal"),
                    "sl": sig.get("sl"),
                    "tp": sig.get("tp"),
                    "structure": sig.get("structure"),
                    "reasons": "|".join(sig.get("reasons",[]))
                })

                # send only non-HOLD
                if sig.get("signal") and sig["signal"] != "HOLD":
                    text = (
                        f"📈 ICT Smart Money Signal ({name})\n"
                        f"Time: {sig['time']}\n"
                        f"Price: {sig['price']:.2f}\n"
                        f"Signal: {sig['signal']}\n"
                        f"SL: {sig['sl']:.4f}  TP: {sig['tp']:.4f}\n"
                        f"RSI: {sig['rsi']:.2f}\n"
                        f"Structure: {sig['structure']}\n"
                        f"Reason: {', '.join(sig['reasons'])}\n"
                        f"⚙️ Strategy: Michael ICT - Smart Money (5m)"
                    )
                    send_telegram(text)
                else:
                    print(f"{now_str()} - {name} HOLD")
            except Exception as e:
                err = f"⚠️ Error analyzing {name}: {e}"
                print(err)
                traceback.print_exc()
                send_telegram(err)
    except Exception as e:
        print("analyze_and_send outer error:", e)
        traceback.print_exc()

# -----------------------
# Flask keepalive + thread
app = Flask(__name__)

@app.route("/")
def home():
    return "🚀 ICT Smart Money Bot (5m) - running"

if __name__ == "__main__":
    send_telegram("🚀 ICT Smart Money Bot started (5m timeframe) - demo")
    def runner():
        while True:
            analyze_and_send()
            time.sleep(60)  # check every 60s to catch 5m closes quickly

    t = threading.Thread(target=runner, daemon=True)
    t.start()

    # Run flask (dev server) for keepalive on Render; Render will set PORT env var
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
