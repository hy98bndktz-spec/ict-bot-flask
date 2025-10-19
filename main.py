# main.py
# ICT Smart-Money Telegram Signal Bot (single-file, ready for Render)
# ملاحظة: الكود يحتوي التوكن والـ chat id كما طلبت (تجريبي). لاحقاً ضعه كـ env vars لأمان أفضل.

import os
import time
import io
import math
import traceback
import requests
from datetime import datetime, timezone, timedelta
from threading import Thread

# plotting & data
import matplotlib
matplotlib.use("Agg")  # headless backend for servers
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
import yfinance as yf

# web keep-alive
from flask import Flask

# -----------------------
# CONFIG (هنا التوكن والـ chat id — موضوع حسب طلبك)
TOKEN = "8461165121:AAG3rQ5GFkv-Jmw-6GxHaQ56p-tgXLopp_A"
CHAT_ID = "690864747"  # استخدم id القناة أو المستخدم أو الغرفة حسب ما تريد

# Symbols mapping (yfinance symbols)
SYMBOLS = {
    "BTC": "BTC-USD",
    "GOLD": "GC=F",
    "ETH": "ETH-USD",
    "EURUSD": "EURUSD=X",
    "USDJPY": "JPY=X",
    "GBPUSD": "GBPUSD=X"
}

TIMEFRAME_BIG = "1h"   # تحليل على الإطار الكبير (ساعه)
TIMEFRAME_ENTRY = "5m" # إطار الدخول
CHECK_INTERVAL = 300   # ثانية -> 5 دقائق

# Telegram endpoints (simple requests, no dependency on python-telegram-bot)
TG_SEND = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
TG_SEND_PHOTO = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"

# Flask app for Render keep-alive
app = Flask(__name__)

@app.route("/")
def home():
    return "🚀 ICT Smart Money Bot — Running"

# -----------------------
# Utilities
def now_utc_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def send_telegram_text(text):
    try:
        payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
        r = requests.post(TG_SEND, json=payload, timeout=10)
        if not r.ok:
            print("Telegram text send failed:", r.status_code, r.text)
        return r.ok
    except Exception as e:
        print("Telegram send error:", e)
        return False

def send_telegram_photo(file_bytes_io, caption=""):
    try:
        file_bytes_io.seek(0)
        files = {"photo": ("chart.png", file_bytes_io.getvalue())}
        data = {"chat_id": CHAT_ID, "caption": caption, "parse_mode": "Markdown"}
        r = requests.post(TG_SEND_PHOTO, data=data, files=files, timeout=30)
        if not r.ok:
            print("Telegram photo send failed:", r.status_code, r.text)
        return r.ok
    except Exception as e:
        print("Telegram send photo error:", e)
        return False

# -----------------------
# Data fetchers
def fetch_yf(symbol, period="2d", interval="1h"):
    """
    Returns DataFrame with columns: Open, High, Low, Close, Volume and DatetimeIndex
    """
    try:
        df = yf.download(tickers=symbol, period=period, interval=interval, progress=False, auto_adjust=False)
        if df is None or df.empty:
            return None
        # ensure proper column names
        df = df.rename(columns={"Open":"Open","High":"High","Low":"Low","Close":"Close","Volume":"Volume"})
        df.index = pd.to_datetime(df.index)
        df = df[["Open","High","Low","Close","Volume"]]
        return df
    except Exception as e:
        print(f"fetch_yf error for {symbol}:", e)
        return None

# -----------------------
# Indicators (lightweight)
def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ma_up = up.ewm(alpha=1/period, adjust=False).mean()
    ma_down = down.ewm(alpha=1/period, adjust=False).mean()
    rs = ma_up / (ma_down + 1e-9)
    return 100 - (100/(1+rs))

# Simple heuristic detection: Order Blocks / FVG approximations (for visuals)
def detect_order_blocks_and_fvg(df):
    ob_list = []
    fvg_list = []
    try:
        n = len(df)
        for i in range(2, n-2):
            prev = df.iloc[i-1]
            cur = df.iloc[i]
            nxt = df.iloc[i+1]
            # OB heuristic
            if prev['Close'] < prev['Open'] and (df['High'].iloc[i+1:i+4] > prev['High']).any():
                ob_list.append(("bullish", prev.name, float(prev['Low']), float(prev['High'])))
            if prev['Close'] > prev['Open'] and (df['Low'].iloc[i+1:i+4] < prev['Low']).any():
                ob_list.append(("bearish", prev.name, float(prev['Low']), float(prev['High'])))
            # FVG heuristic: middle candle body not overlapping neighbors
            a_open, a_close = df['Open'].iloc[i-1], df['Close'].iloc[i-1]
            b_open, b_close = df['Open'].iloc[i], df['Close'].iloc[i]
            c_open, c_close = df['Open'].iloc[i+1], df['Close'].iloc[i+1]
            a_low, a_high = min(a_open,a_close), max(a_open,a_close)
            b_low, b_high = min(b_open,b_close), max(b_open,b_close)
            c_low, c_high = min(c_open,c_close), max(c_open,c_close)
            if (b_close < b_open) and (c_low > a_high):
                fvg_list.append((df.index[i-1], df.index[i+1], a_high, c_low))
            if (b_close > b_open) and (c_high < a_low):
                fvg_list.append((df.index[i-1], df.index[i+1], c_high, a_low))
    except Exception as e:
        print("detect OB/FVG error:", e)
    return ob_list, fvg_list

# -----------------------
# Chart generator (candles dark, EMA overlays)
def generate_candlestick_image(df, symbol, sig):
    """
    df must have index datetime and columns Open,High,Low,Close,Volume
    returns BytesIO with PNG image
    """
    try:
        df_plot = df.copy()
        df_plot.index = pd.to_datetime(df_plot.index)
        df_plot = df_plot.rename(columns={"Open":"Open","High":"High","Low":"Low","Close":"Close","Volume":"Volume"})
        # add EMAs
        df_plot["EMA20"] = ema(df_plot["Close"], 20)
        df_plot["EMA50"] = ema(df_plot["Close"], 50)

        apds = [
            mpf.make_addplot(df_plot["EMA20"], width=0.8),
            mpf.make_addplot(df_plot["EMA50"], width=0.8)
        ]

        style = mpf.make_mpf_style(base_mpf_style="nightclouds", rc={"figure.facecolor":"#0e0f11", "axes.facecolor":"#0e0f11"})
        fig, axes = mpf.plot(df_plot, type='candle', style=style, addplot=apds, returnfig=True, figsize=(9,4), tight_layout=True)

        # try to add OB/FVG markers
        ob_list, fvg_list = detect_order_blocks_and_fvg(df_plot)
        ax = axes[0]
        try:
            for (typ, t_idx, low, high) in ob_list:
                color = "#00bfff" if typ=="bullish" else "#ff69b4"
                ax.axvspan(t_idx, df_plot.index[-1], color=color, alpha=0.06)
            for (s,e,low,high) in fvg_list:
                ax.axvspan(s, e, color="#ffd700", alpha=0.2)
        except Exception:
            pass

        # title
        title = f"{symbol}  | {sig['signal']}  | {sig['time']}"
        ax.set_title(title, color="white", fontsize=10)

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor=fig.get_facecolor())
        buf.seek(0)
        plt.close(fig)
        return buf
    except Exception as e:
        print("generate_candlestick_image error:", e, traceback.format_exc())
        return None

# -----------------------
# Signal generator (ICT-ish heuristic)
def generate_signal_from_df(df):
    """
    Input: df with datetime index and Open/High/Low/Close/Volume
    Output: dict with signal / sl / tp / rsi / price / time
    """
    try:
        df2 = df.copy()
        df2["EMA20"] = ema(df2["Close"], 20)
        df2["EMA50"] = ema(df2["Close"], 50)
        df2["RSI"] = rsi(df2["Close"], 14)
        last = df2.iloc[-1]
        price = float(last["Close"])
        ema20 = float(last["EMA20"]) if not math.isnan(last["EMA20"]) else None
        ema50 = float(last["EMA50"]) if not math.isnan(last["EMA50"]) else None
        rsi_val = float(last["RSI"]) if not math.isnan(last["RSI"]) else None

        signal = "HOLD"
        sl = None; tp = None
        reasons = []

        if ema20 is not None and ema50 is not None:
            if ema20 > ema50 and (rsi_val is None or rsi_val < 70):
                signal = "BUY"
                reasons.append("EMA bias + RSI")
            elif ema20 < ema50 and (rsi_val is None or rsi_val > 30):
                signal = "SELL"
                reasons.append("EMA bias + RSI")

        # ATR-based SL/TP fallback
        try:
            high_low = df2["High"].rolling(14).max() - df2["Low"].rolling(14).min()
            atr = high_low.iloc[-1] if not high_low.empty else (price * 0.002)
            atr_val = float(atr) if atr and not math.isnan(atr) else (price*0.002)
        except Exception:
            atr_val = price*0.002

        if signal == "BUY":
            sl = price - 1.2 * atr_val
            tp = price + 2.0 * atr_val
        elif signal == "SELL":
            sl = price + 1.2 * atr_val
            tp = price - 2.0 * atr_val

        return {
            "time": now_utc_str(),
            "price": price,
            "signal": signal,
            "sl": sl,
            "tp": tp,
            "rsi": rsi_val,
            "reasons": reasons
        }
    except Exception as e:
        print("generate_signal_from_df error:", e)
        return {"time": now_utc_str(), "price": None, "signal":"HOLD"}

# -----------------------
# Freshness & market-open checks
def data_is_fresh(df, max_age_minutes=30):
    if df is None or df.empty:
        return False
    last_ts = df.index[-1]
    now = datetime.now(timezone.utc)
    # if last timestamp has tzinfo attach if missing
    if last_ts.tzinfo is None:
        last_ts = last_ts.tz_localize(timezone.utc)
    age = now - last_ts
    return age <= timedelta(minutes=max_age_minutes)

# -----------------------
# Main analyze loop for all symbols
def analyze_and_send_all():
    print(f"{now_utc_str()} - Background loop started. Checking every {CHECK_INTERVAL}s.")
    # initial notify
    try:
        send_telegram_text(f"🚀 ICT Bot started successfully. Time: {now_utc_str()}")
    except Exception:
        pass

    while True:
        try:
            for short, sym in SYMBOLS.items():
                try:
                    # fetch hourly for structure/plot and 5m if needed
                    df_1h = fetch_yf(sym, period="7d", interval="1h")
                    # check freshness
                    if df_1h is None or df_1h.empty or not data_is_fresh(df_1h, max_age_minutes=90):
                        print(f"{now_utc_str()} - No fresh 1h data for {sym} -> skipping")
                        continue

                    sig = generate_signal_from_df(df_1h)
                    sig["symbol"] = short
                    sig["checked_at"] = now_utc_str()

                    # only act on BUY/SELL
                    if sig["signal"] in ("BUY", "SELL"):
                        # generate chart (use last 120 candles)
                        df_plot = df_1h.tail(120)
                        chart_buf = generate_candlestick_image(df_plot, short, sig)
                        # caption message
                        caption = (f"*ICT Smart Money Signal*  `{short}`\n"
                                   f"Time: `{sig['time']}`\n"
                                   f"Price: `{sig['price']:.4f}`\n"
                                   f"Signal: *{sig['signal']}*\n"
                                   f"RSI: `{sig['rsi']:.1f}`\n")
                        if sig["sl"] is not None and sig["tp"] is not None:
                            caption += f"SL: `{sig['sl']:.4f}` | TP: `{sig['tp']:.4f}`\n"
                        caption += "\n_Strategy: Michael ICT - Smart Money Concepts (demo)_"

                        # send
                        if chart_buf:
                            send_telegram_photo(chart_buf, caption)
                        else:
                            send_telegram_text(caption)
                        print(f"{now_utc_str()} - Sent {sig['signal']} for {short} @{sig['price']:.4f}")
                    else:
                        print(f"{now_utc_str()} - {short} HOLD")

                except Exception as e:
                    print(f"Error per-symbol {sym}: {e}", traceback.format_exc())
            # loop sleep
            time.sleep(CHECK_INTERVAL)
        except Exception as main_e:
            print("Main loop error:", main_e, traceback.format_exc())
            time.sleep(10)

# -----------------------
# Start background thread + Flask app (Render friendly)
def start_background():
    t = Thread(target=analyze_and_send_all, daemon=True)
    t.start()

if __name__ == "__main__":
    # start background
    start_background()
    # start flask to bind port
    port = int(os.environ.get("PORT", 5000))
    print(f"{now_utc_str()} - Starting Flask on port {port} (keep-alive)")
    app.run(host="0.0.0.0", port=port)
