# bot.py
"""
ICT Smart Money PRO V2
- 1H bias + 5m entries
- Advanced heuristics: Order Blocks (OB), Fair Value Gaps (FVG), Liquidity Sweeps
- Sends detailed Telegram alerts + annotated chart images
- Fallback data sources: MT5 (optional) / Binance (BTC) / yfinance (XAU, EUR)
"""

import os
import time
import json
import math
import io
import requests
from datetime import datetime, timezone
import threading

import numpy as np
import pandas as pd
import pandas_ta as ta
import matplotlib.pyplot as plt
from PIL import Image

# try mt5 optional (not required)
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except Exception:
    MT5_AVAILABLE = False

from flask import Flask

# -----------------------
# CONFIG (يفضل نقلها كـ ENV في Render)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8461165121:AAG3rQ5GFkv-Jmw-6GxHaQ56p-tgXLopp_A")
CHAT_ID = os.environ.get("CHAT_ID", "690864747")
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
FETCH_LIMIT = int(os.environ.get("FETCH_LIMIT", 500))
ALIVE_NOTIFY = os.environ.get("ALIVE_NOTIFY", "1")

# assets: logical keys
ASSETS = {
    "XAUUSD": {"mt5": "XAUUSD", "yfinance": "GC=F", "label": "Gold (XAUUSD)"},
    "BTCUSD": {"mt5": "BTCUSD", "binance": "BTCUSDT", "label": "Bitcoin (BTCUSD)"},
    "EURUSD": {"mt5": "EURUSD", "yfinance": "EURUSD=X", "label": "EUR/USD"}
}

LAST_SIGNALS_FILE = "last_signals_v2.json"

# Flask keep-alive
app = Flask(__name__)
@app.route("/")
def home():
    return "ICT Smart Money PRO V2 — running"

# -----------------------
def now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def send_telegram_text(text):
    try:
        r = requests.post(f"{TG_API}/sendMessage", json={"chat_id": CHAT_ID, "text": text}, timeout=10)
        if not r.ok:
            print("Telegram text error:", r.status_code, r.text)
    except Exception as e:
        print("Telegram text exception:", e)

def send_telegram_photo_bytes(img_bytes, caption):
    try:
        files = {"photo": ("chart.png", img_bytes, "image/png")}
        data = {"chat_id": CHAT_ID, "caption": caption}
        r = requests.post(f"{TG_API}/sendPhoto", data=data, files=files, timeout=20)
        if not r.ok:
            print("Telegram photo error:", r.status_code, r.text)
    except Exception as e:
        print("Telegram sendPhoto exception:", e)

# -----------------------
# persistence to avoid spam
def load_last_signals():
    try:
        if os.path.exists(LAST_SIGNALS_FILE):
            with open(LAST_SIGNALS_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_last_signals(d):
    try:
        with open(LAST_SIGNALS_FILE, "w") as f:
            json.dump(d, f)
    except Exception as e:
        print("save_last_signals error:", e)

last_signals = load_last_signals()

# -----------------------
# FETCHERS: MT5 optional, else Binance / yfinance
def fetch_mt5_ohlc(symbol, timeframe_minutes=5, bars=500):
    if not MT5_AVAILABLE:
        return pd.DataFrame()
    try:
        if not mt5.initialize():
            if os.environ.get("MT5_LOGIN") and os.environ.get("MT5_PASSWORD") and os.environ.get("MT5_SERVER"):
                mt5.shutdown()
                ok = mt5.initialize(login=int(os.environ.get("MT5_LOGIN")),
                                     password=os.environ.get("MT5_PASSWORD"),
                                     server=os.environ.get("MT5_SERVER"))
                if not ok:
                    print("MT5 initialize failed with credentials")
                    return pd.DataFrame()
            else:
                print("MT5 not initialized")
                return pd.DataFrame()
        tf_map = {1: mt5.TIMEFRAME_M1, 5: mt5.TIMEFRAME_M5, 15: mt5.TIMEFRAME_M15, 30: mt5.TIMEFRAME_M30, 60: mt5.TIMEFRAME_H1}
        tf = tf_map.get(timeframe_minutes, mt5.TIMEFRAME_M5)
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, bars)
        if rates is None or len(rates) == 0:
            return pd.DataFrame()
        df = pd.DataFrame(rates)
        df['open_time'] = pd.to_datetime(df['time'], unit='s')
        df.set_index('open_time', inplace=True)
        df = df.rename(columns={'tick_volume': 'volume'})
        df = df[['open','high','low','close','volume']]
        return df
    except Exception as e:
        print("fetch_mt5_ohlc error:", e)
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
            "close_time","quote_asset_volume","num_trades","taker_buy_base","taker_buy_quote","ignore"
        ])
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df.set_index("open_time", inplace=True)
        for c in ["open","high","low","close","volume"]:
            df[c] = df[c].astype(float)
        return df[["open","high","low","close","volume"]]
    except Exception as e:
        print("fetch_binance_klines error:", e)
        return pd.DataFrame()

def fetch_yfinance_klines(ticker, interval="5m", period="2d"):
    try:
        import yfinance as yf
        df = yf.download(tickers=ticker, interval=interval, period=period, progress=False)
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.dropna()
        df.index = pd.to_datetime(df.index)
        df = df.rename(columns={"Open":"open","High":"high","Low":"low","Close":"close","Volume":"volume"})
        return df[["open","high","low","close","volume"]]
    except Exception as e:
        print("fetch_yfinance_klines error:", e)
        return pd.DataFrame()

def fetch_ohlc(asset_key, timeframe_minutes=5):
    cfg = ASSETS.get(asset_key)
    if cfg is None:
        return pd.DataFrame()
    # try mt5
    mt5_sym = cfg.get("mt5")
    if mt5_sym and MT5_AVAILABLE:
        df = fetch_mt5_ohlc(mt5_sym, timeframe_minutes=timeframe_minutes, bars=FETCH_LIMIT)
        if not df.empty:
            return df
    # fallback
    if asset_key == "BTCUSD":
        return fetch_binance_klines("BTCUSDT", interval=f"{timeframe_minutes}m", limit=FETCH_LIMIT)
    elif asset_key == "XAUUSD":
        return fetch_yfinance_klines(cfg.get("yfinance"), interval=f"{timeframe_minutes}m", period="2d")
    elif asset_key == "EURUSD":
        return fetch_yfinance_klines(cfg.get("yfinance"), interval=f"{timeframe_minutes}m", period="2d")
    return pd.DataFrame()

# -----------------------
# Indicators + small helpers
def compute_indicators(df):
    if df is None or df.empty:
        return df
    df = df.copy()
    if len(df) < 6:
        return df
    df["EMA50"] = ta.ema(df["close"], length=50)
    df["EMA200"] = ta.ema(df["close"], length=200)
    df["RSI14"] = ta.rsi(df["close"], length=14)
    return df

# -----------------------
# Advanced SMC heuristics (OB / FVG / Liquidity)
def detect_order_blocks_advanced(df, lookback=50):
    """
    Heuristic for order blocks:
    - find recent 'opposite' candle before a strong move (range expansion)
    - returns list of OB dicts {type, high, low, start_idx}
    We'll scan backwards and collect up to a few OBs.
    """
    obs = []
    try:
        n = len(df)
        for i in range(n-5, max(5, n-lookback), -1):
            prev = df.iloc[i-1]
            cur = df.iloc[i]
            fut = df.iloc[i+1:i+5]
            # bullish OB candidate: prev bearish then strong rallies
            if (prev['close'] < prev['open']) and (fut['high'].max() > prev['high'] + 0):
                obs.append({"type":"bullish","high":float(prev['high']), "low":float(prev['low']), "time": str(prev.name)})
            # bearish OB candidate
            if (prev['close'] > prev['open']) and (fut['low'].min() < prev['low'] - 0):
                obs.append({"type":"bearish","high":float(prev['high']), "low":float(prev['low']), "time": str(prev.name)})
            if len(obs) >= 4:
                break
    except Exception as e:
        print("detect_order_blocks_advanced error:", e)
    return obs[::-1]  # chronological

def detect_fvg_advanced(df):
    """
    Detect simple 3-candle fair value gaps (FVG).
    Return list of fvg dicts with type, low, high, from_time, to_time
    """
    fvgs = []
    try:
        n = len(df)
        for i in range(1, n-1):
            a = df.iloc[i-1]; b = df.iloc[i]; c = df.iloc[i+1]
            # bullish FVG: middle bearish and gap between a.close and c.open
            if (b['close'] < b['open']) and (c['open'] > a['close']):
                fvgs.append({"type":"bullish","low":float(a['close']), "high": float(c['open']), "from": str(a.name), "to": str(c.name)})
            # bearish FVG
            if (b['close'] > b['open']) and (c['open'] < a['close']):
                fvgs.append({"type":"bearish","low": float(c['open']), "high": float(a['close']), "from": str(a.name), "to": str(c.name)})
    except Exception as e:
        print("detect_fvg_advanced error:", e)
    return fvgs

def detect_liquidity_sweep(df, lookback=40):
    """
    Liquidity sweep heuristic:
    - detect recent wick that surpasses previous swing high/low then reversal
    - returns list of sweeps with type and price and time
    """
    sweeps = []
    try:
        highs = df['high']; lows = df['low']
        n = len(df)
        for i in range(n-5, max(10, n-lookback), -1):
            # detect high sweep (wick above prior highs) then close below
            window = highs.iloc[i-5:i]
            prior_high = window.max() if len(window) > 0 else highs.iloc[i-1]
            if highs.iloc[i] > prior_high and df['close'].iloc[i] < df['open'].iloc[i]:
                sweeps.append({"type":"high_sweep","price":float(highs.iloc[i]), "time": str(df.index[i])})
            # low sweep
            windowl = lows.iloc[i-5:i]
            prior_low = windowl.min() if len(windowl) > 0 else lows.iloc[i-1]
            if lows.iloc[i] < prior_low and df['close'].iloc[i] > df['open'].iloc[i]:
                sweeps.append({"type":"low_sweep","price":float(lows.iloc[i]), "time": str(df.index[i])})
            if len(sweeps) >= 3:
                break
    except Exception as e:
        print("detect_liquidity_sweep error:", e)
    return sweeps[::-1]

# -----------------------
# signal generation combining HTF bias + LTF confirmation + OB/FVG
def detect_structure_simple(df):
    if df is None or len(df) < 6:
        return "insufficient"
    highs = df['high']; lows = df['low']
    last_high = float(highs.iloc[-1]); prev_high = float(highs.iloc[-3])
    last_low = float(lows.iloc[-1]); prev_low = float(lows.iloc[-3])
    if last_high > prev_high and last_low > prev_low:
        return "uptrend"
    elif last_high < prev_high and last_low < prev_low:
        return "downtrend"
    else:
        return "sideways"

def generate_advanced_signal(asset_key, df1h, df5):
    # compute indicators
    df1h = compute_indicators(df1h)
    df5 = compute_indicators(df5)
    bias = detect_structure_simple(df1h) if df1h is not None and not df1h.empty else "insufficient"
    structure_5m = detect_structure_simple(df5) if df5 is not None and not df5.empty else "insufficient"

    last = df5.iloc[-1]
    price = float(last['close'])
    rsi = float(last.get('RSI14')) if 'RSI14' in last and not pd.isna(last.get('RSI14')) else None
    ema50 = float(last.get('EMA50')) if 'EMA50' in last and not pd.isna(last.get('EMA50')) else None
    ema200 = float(last.get('EMA200')) if 'EMA200' in last and not pd.isna(last.get('EMA200')) else None

    obs = detect_order_blocks_advanced(df5, lookback=80)
    fvgs = detect_fvg_advanced(df5)
    sweeps = detect_liquidity_sweep(df5, lookback=60)

    signal = "HOLD"
    reasons = []

    # Rules:
    # If bias is uptrend, prefer BUY when price touches bullish OB or bullish FVG and not overbought
    if bias == "uptrend":
        if (ema50 and ema200 and ema50 > ema200) or structure_5m == "uptrend":
            # check bullish OB
            for ob in reversed(obs):
                if ob['type'] == 'bullish' and price <= ob['high'] + 1.5 * df5['close'].diff().abs().mean():
                    signal = "BUY"
                    reasons.append("Touched bullish OB")
                    break
            # check bullish FVG
            if signal == "HOLD":
                for f in reversed(fvgs):
                    if f['type'] == 'bullish' and price <= f['high'] + 1.5 * df5['close'].diff().abs().mean():
                        signal = "BUY"
                        reasons.append("Touched bullish FVG")
                        break
            # liquidity sweep confirmation can strengthen
            if signal == "HOLD" and len(sweeps) > 0:
                # if a recent low_sweep then price returned -> bullish
                for s in sweeps:
                    if s['type'] == 'low_sweep' and price > s['price']:
                        signal = "BUY"
                        reasons.append("Liquidity low-sweep then return")
                        break
    # SELL mirror
    if bias == "downtrend":
        if (ema50 and ema200 and ema50 < ema200) or structure_5m == "downtrend":
            for ob in reversed(obs):
                if ob['type'] == 'bearish' and price >= ob['low'] - 1.5 * df5['close'].diff().abs().mean():
                    signal = "SELL"
                    reasons.append("Touched bearish OB")
                    break
            if signal == "HOLD":
                for f in reversed(fvgs):
                    if f['type'] == 'bearish' and price >= f['low'] - 1.5 * df5['close'].diff().abs().mean():
                        signal = "SELL"
                        reasons.append("Touched bearish FVG")
                        break
            if signal == "HOLD" and len(sweeps) > 0:
                for s in sweeps:
                    if s['type'] == 'high_sweep' and price < s['price']:
                        signal = "SELL"
                        reasons.append("Liquidity high-sweep then return")
                        break

    result = {
        "signal": signal,
        "price": price,
        "rsi": rsi,
        "bias": bias,
        "structure_5m": structure_5m,
        "ob_list": obs,
        "fvg_list": fvgs,
        "sweeps": sweeps,
        "reasons": reasons,
        "time": now_str()
    }
    return result

# -----------------------
# Charting (candles + EMAs + OB/FVG/Sweeps)
def plot_annotated_chart(df5, asset_key, sig):
    try:
        plt.ioff()
        fig, ax = plt.subplots(figsize=(10,5))
        # candlestick-like: we'll plot close line and shade OB/FVG
        ax.plot(df5.index, df5['close'], linewidth=1)

        # EMAs if present
        if 'EMA50' in df5.columns:
            ax.plot(df5.index, df5['EMA50'], linewidth=0.9, label="EMA50")
        if 'EMA200' in df5.columns:
            ax.plot(df5.index, df5['EMA200'], linewidth=0.9, label="EMA200")

        # plot OBs
        for ob in sig.get('ob_list', []):
            low = ob['low']; high = ob['high']
            # shade last part only for readability
            ax.fill_between(df5.index[-60:], low, high, alpha=0.12)

            ax.text(df5.index[-1], high, "OB "+ob['type'], fontsize=8, va='bottom')

        # plot FVGs
        for f in sig.get('fvg_list', []):
            low = f['low']; high = f['high']
            ax.fill_between(df5.index[-60:], low, high, alpha=0.12, hatch='//')
            ax.text(df5.index[-1], high, "FVG "+f['type'], fontsize=8, va='bottom')

        # plot sweeps
        for s in sig.get('sweeps', []):
            if s['type'] == 'high_sweep':
                ax.axhline(s['price'], linestyle='--', linewidth=0.8)
                ax.text(df5.index[-1], s['price'], "Sweep High", fontsize=8, va='bottom')
            else:
                ax.axhline(s['price'], linestyle='--', linewidth=0.8)
                ax.text(df5.index[-1], s['price'], "Sweep Low", fontsize=8, va='bottom')

        last_time = df5.index[-1]
        last_price = df5['close'].iloc[-1]
        ax.scatter([last_time], [last_price], s=20)
        ax.annotate(f"{sig['signal']} {last_price:.4f}", xy=(last_time, last_price),
                    xytext=(0,12), textcoords="offset points", fontsize=9)

        ax.set_title(f"{ASSETS[asset_key]['label']} — {sig['signal']} — {sig['bias']}")
        ax.set_xlabel("Time (UTC)")
        ax.set_ylabel("Price")
        ax.legend()
        fig.autofmt_xdate()
        buf = io.BytesIO()
        plt.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    except Exception as e:
        print("plot_annotated_chart error:", e)
        return None

# -----------------------
# Main analyze loop
def analyze_and_alert_v2():
    for key in ASSETS.keys():
        try:
            # fetch 1H bias and 5m LTF
            df1h = fetch_ohlc_for_key(key, timeframe_minutes=60)
            df5 = fetch_ohlc_for_key(key, timeframe_minutes=5)
            if df5 is None or df5.empty or df1h is None or df1h.empty:
                print(f"{now_str()} - No data for {key}")
                continue
            sig = generate_advanced_signal(key, df1h, df5)
            last = last_signals.get(key)

            # send only when changed
            if sig['signal'] != "HOLD":
                if last != sig['signal']:
                    # craft caption
                    caption = (
                        f"📊 ICT Smart Money PRO\n"
                        f"{ASSETS[key]['label']}\n"
                        f"Time: {sig['time']}\n"
                        f"Price: {sig['price']:.4f}\n"
                        f"Signal: {sig['signal']}\n"
                        f"Bias(1H): {sig['bias']}\n"
                        f"5m structure: {sig['structure_5m']}\n"
                        f"RSI: {sig['rsi']}\n"
                        f"Reasons: {', '.join(sig['reasons']) if sig['reasons'] else 'N/A'}\n"
                        f"Strategy: Michael ICT - Smart Money Concepts (1H→5m)"
                    )
                    # create annotated chart
                    chart_bytes = plot_annotated_chart(df5, key, sig)
                    send_telegram_text(caption)
                    if chart_bytes:
                        send_telegram_photo_bytes(chart_bytes, caption)
                    else:
                        send_telegram_text(caption + "\n(note: chart generation failed)")
                    last_signals[key] = sig['signal']
                    save_last_signals(last_signals)
                else:
                    print(f"{now_str()} - {key} same signal {sig['signal']} suppressed")
            else:
                print(f"{now_str()} - {key} HOLD")
        except Exception as e:
            err = f"⚠️ analyze error for {key}: {e}"
            print(err)
            send_telegram_text(err)

# helper wrapper to use earlier fetch function names
def fetch_ohlc_for_key(key, timeframe_minutes=5):
    # use earlier defined fetchers (Binance / yfinance / MT5)
    cfg = ASSETS.get(key)
    if cfg is None:
        return pd.DataFrame()
    # try MT5 first if available
    mt5_sym = cfg.get("mt5")
    if mt5_sym and MT5_AVAILABLE:
        df = fetch_mt5_ohlc(mt5_sym, timeframe_minutes=timeframe_minutes, bars=FETCH_LIMIT)
        if not df.empty:
            return df
    # fallbacks
    if key == "BTCUSD":
        return fetch_binance_klines(cfg.get('binance', 'BTCUSDT'), interval=f"{timeframe_minutes}m", limit=FETCH_LIMIT)
    elif key == "XAUUSD":
        return fetch_yfinance_klines(cfg.get('yfinance', 'GC=F'), interval=f"{timeframe_minutes}m", period="2d")
    elif key == "EURUSD":
        return fetch_yfinance_klines(cfg.get('yfinance', 'EURUSD=X'), interval=f"{timeframe_minutes}m", period="2d")
    return pd.DataFrame()

# ensure fetch functions used above are available (reuse earlier names)
def fetch_mt5_ohlc(symbol, timeframe_minutes=5, bars=500):
    return fetch_mt5_ohlc  # placeholder for MT5 function defined earlier; actual function exists up above

# The previous declarations for fetch_binance_klines and fetch_yfinance_klines are used
# If functions not in same scope (depending on previous paste), ensure definitions exist.
# (To avoid duplication issues, paste full file as above where fetch functions are defined earlier.)

# -----------------------
if __name__ == "__main__":
    # startup notify
    if ALIVE_NOTIFY == "1":
        send_telegram_text("🚀 ICT Smart Money PRO V2 started — 1H bias + 5m entries (OB/FVG/Liquidity).")

    # run loop thread
    def main_loop():
        while True:
            analyze_and_alert_v2()
            time.sleep(60)

    t = threading.Thread(target=main_loop, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
