# bot.py
import os
import time
import io
import json
import math
import requests
import pandas as pd
import numpy as np
import mplfinance as mpf
import matplotlib.pyplot as plt
from datetime import datetime, timezone, timedelta
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    JobQueue,
)
import threading

# -----------------------
# CONFIG - مدرج التوكن الذي أعطيتني
TOKEN = "8461165121:AAG3rQ5GFkv-Jmw-6GxHaQ56p-tgXLopp_A"
# ملف حفظ المشتركين
SUBS_FILE = "subscribers.json"

# Binance symbols (5m)
SYMBOLS = {
    "XAU": "XAUUSDT",   # Gold synthetic on Binance (if available)
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "EURUSD": "EURUSDT",  # note: Binance symbol uses base/USDT; EURUSDT exists
    "USDJPY": "USDJPY",   # may not exist on Binance; we'll try fallback to "EURUSD" if missing
    "GBPUSD": "GBPUSDT"
}

INTERVAL = "5m"
LIMIT = 200

# how fresh data must be (minutes)
FRESHNESS_MINUTES = 15

# -----------------------
# helpers: subscribers persistence
def load_subs():
    if os.path.exists(SUBS_FILE):
        try:
            with open(SUBS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_subs(subs):
    with open(SUBS_FILE, "w") as f:
        json.dump(list(set(subs)), f)

# -----------------------
# Telegram helpers
async def add_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    subs = load_subs()
    if chat_id in subs:
        await context.bot.send_message(chat_id=chat_id, text="✅ You are already subscribed. You will receive signals.")
        return
    subs.append(chat_id)
    save_subs(subs)
    await context.bot.send_message(chat_id=chat_id, text="✅ Subscribed! You will receive signals every 5 minutes. Use /stop to unsubscribe.")

async def remove_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    subs = load_subs()
    if chat_id in subs:
        subs.remove(chat_id)
        save_subs(subs)
        await context.bot.send_message(chat_id=chat_id, text="🛑 Unsubscribed. You will no longer receive signals.")
    else:
        await context.bot.send_message(chat_id=chat_id, text="You are not subscribed.")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subs = load_subs()
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Subscribers: {len(subs)}")

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await add_sub(update, context)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "/start - subscribe to signals\n"
        "/stop - unsubscribe\n"
        "/status - show subscriber count (admin)\n"
        "/analyze - run immediate analysis now"
    )
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text)

# -----------------------
# Binance klines fetcher
def get_klines_binance(symbol, interval=INTERVAL, limit=LIMIT):
    try:
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        # columns: openTime, open, high, low, close, volume, closeTime, ...
        df = pd.DataFrame(data, columns=[
            "open_time","open","high","low","close","volume",
            "close_time","quote_asset_volume","num_trades","taker_buy_base","taker_buy_quote","ignore"
        ])
        df["datetime"] = pd.to_datetime(df["open_time"], unit="ms")
        df.set_index("datetime", inplace=True)
        for c in ["open","high","low","close","volume"]:
            df[c] = df[c].astype(float)
        return df[["open","high","low","close","volume"]]
    except Exception as e:
        # return None on error
        print("Binance fetch error for", symbol, e)
        return None

# -----------------------
# Indicators and ICT-ish detection (approx)
def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def compute_rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ma_up = up.ewm(com=period-1, adjust=False).mean()
    ma_down = down.ewm(com=period-1, adjust=False).mean()
    rs = ma_up / ma_down
    rsi = 100 - (100 / (1 + rs))
    return rsi

def compute_indicators(df):
    df = df.copy()
    df["EMA20"] = ema(df["close"], 20)
    df["EMA50"] = ema(df["close"], 50)
    df["RSI"] = compute_rsi(df["close"], 14)
    return df

def detect_fvg(df):
    fvg = []
    # simple heuristic: middle candle body not overlapping neighbors
    for i in range(1, len(df)-1):
        a_open, a_close = df["open"].iloc[i-1], df["close"].iloc[i-1]
        b_open, b_close = df["open"].iloc[i], df["close"].iloc[i]
        c_open, c_close = df["open"].iloc[i+1], df["close"].iloc[i+1]
        a_low, a_high = min(a_open,a_close), max(a_open,a_close)
        b_low, b_high = min(b_open,b_close), max(b_open,b_close)
        c_low, c_high = min(c_open,c_close), max(c_open,c_close)
        # bullish FVG
        if (b_close < b_open) and (c_low > a_high):
            fvg.append((df.index[i-1], df.index[i+1], a_high, c_low))
        # bearish FVG
        if (b_close > b_open) and (c_high < a_low):
            fvg.append((df.index[i-1], df.index[i+1], c_high, a_low))
    return fvg

def detect_order_blocks(df):
    obs = []
    for i in range(1, len(df)-3):
        prev = df.iloc[i-1]
        cur = df.iloc[i]
        future = df.iloc[i+1:i+5]
        # bullish OB
        if prev["close"] < prev["open"]:
            if (future["high"] > prev["high"]).any():
                obs.append(("bullish", prev.name, float(prev["low"]), float(prev["high"])))
        # bearish OB
        if prev["close"] > prev["open"]:
            if (future["low"] < prev["low"]).any():
                obs.append(("bearish", prev.name, float(prev["low"]), float(prev["high"])))
    return obs

def detect_liquidity(df):
    liq = []
    highs = df["high"]; lows = df["low"]
    for i in range(3, len(df)-3):
        win_h = highs.iloc[i-3:i+4]
        win_l = lows.iloc[i-3:i+4]
        if highs.iloc[i] == win_h.max():
            liq.append(("sell", df.index[i], highs.iloc[i]))
        if lows.iloc[i] == win_l.min():
            liq.append(("buy", df.index[i], lows.iloc[i]))
    return liq

# -----------------------
# Chart maker: candle dark + overlays (mplfinance)
def make_chart_bytes(df, sig, fvg_list, obs, liq_list):
    ohlc = df[["open","high","low","close"]].copy()
    # prepare style dark
    s = mpf.make_mpf_style(base_mpf_style='nightclouds', rc={
        'axes.facecolor': '#0e0f11', 'figure.facecolor': '#0e0f11'
    })
    addplots = []
    if "EMA20" in df.columns:
        addplots.append(mpf.make_addplot(df["EMA20"], color='cyan', width=0.8))
    if "EMA50" in df.columns:
        addplots.append(mpf.make_addplot(df["EMA50"], color='magenta', width=0.8))

    fig, axes = mpf.plot(ohlc, type='candle', style=s, addplot=addplots, returnfig=True, figsize=(8,4), tight_layout=True)
    ax = axes[0]

    # FVG rectangles
    for (start, end, low, high) in fvg_list:
        try:
            ax.axvspan(start, end, color='#ffd700', alpha=0.25)
            ax.text(end, (low+high)/2, 'FVG', color='black', fontsize=7, va='center', ha='right', backgroundcolor='#ffd700', alpha=0.6)
        except Exception:
            continue

    # OB spans
    for ob in obs:
        typ, time_idx, low, high = ob
        color = '#00bfff' if typ=="bullish" else '#ff69b4'
        try:
            ax.axvspan(time_idx, df.index[-1], color=color, alpha=0.06)
            ax.text(time_idx, high, 'OB', color=color, fontsize=7, va='bottom')
        except Exception:
            continue

    # liquidity markers
    for li in liq_list:
        typ, t_idx, price = li
        marker = '^' if typ=='buy' else 'v'
        try:
            ax.plot([t_idx], [price], marker=marker, color='white', markersize=6)
            ax.text(t_idx, price, 'LQ', color='white', fontsize=7, va='bottom' if typ=='buy' else 'top')
        except Exception:
            continue

    # title
    ax.set_title(f"{sig['symbol']}  {sig['signal']}  @{sig['price']:.4f}", color='white', fontsize=10)

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=120, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf

# -----------------------
# freshness check
def is_fresh(df, minutes=FRESHNESS_MINUTES):
    if df is None or df.empty:
        return False
    last_time = df.index[-1]
    now = datetime.now(timezone.utc)
    return (now - last_time) <= timedelta(minutes=minutes)

# -----------------------
# signal logic
def generate_signal(df, symbol):
    df = compute_indicators(df)
    if df is None or df.empty:
        return {"symbol": symbol, "signal": "NO_DATA"}
    last = df.iloc[-1]
    price = float(last["close"])
    ema20 = float(last["EMA20"]) if not math.isnan(last["EMA20"]) else math.nan
    ema50 = float(last["EMA50"]) if not math.isnan(last["EMA50"]) else math.nan
    rsi_val = float(last["RSI"]) if not math.isnan(last["RSI"]) else math.nan

    signal = "HOLD"; tp = None
    if not math.isnan(ema20) and not math.isnan(ema50):
        if ema20 > ema50 and rsi_val < 70:
            signal = "BUY"; tp = price * 1.002
        elif ema20 < ema50 and rsi_val > 30:
            signal = "SELL"; tp = price * 0.998

    return {"symbol": symbol, "price": price, "signal": signal, "tp": tp, "rsi": rsi_val, "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}

# -----------------------
# analyze single symbol and send to all subs
def analyze_symbol_and_send(app, symbol_binance):
    df = get_klines_binance(symbol_binance)
    if df is None or len(df) < 30:
        print("No data for", symbol_binance); return
    if not is_fresh(df):
        print("Stale data for", symbol_binance); return

    df = compute_indicators(df)
    sig = generate_signal(df, symbol_binance)
    fvg = detect_fvg(df)
    obs = detect_order_blocks(df)
    liq = detect_liquidity(df)

    if sig["signal"] in ("BUY","SELL"):
        try:
            chart = make_chart_bytes = make_chart_bytes  # no-op to reference
        except:
            pass
        try:
            chart_buf = make_chart_bytes(df, sig, fvg, obs, liq)
        except Exception as e:
            print("Chart creation error:", e)
            chart_buf = None

        caption = (
            f"*ICT Smart Money Signal*\n"
            f"Asset: `{sig['symbol']}`\n"
            f"Time: `{sig['time']}`\n"
            f"Price: `${sig['price']:.4f}`\n"
            f"Signal: *{sig['signal']}*\n"
            f"RSI: `{sig['rsi']:.1f}`\n"
        )
        if sig["tp"] is not None:
            caption += f"🎯 TP: `{sig['tp']:.4f}`\n"
        caption += "⚙️ Strategy: Michael ICT - approx"

        # send to each subscriber
        subs = load_subs()
        if not subs:
            print("No subscribers to send to.")
            return
        for chat_id in subs:
            try:
                if chart_buf:
                    # Telegram expects file-like; reset pointer for each send
                    chart_buf.seek(0)
                    await_send_photo(chat_id, chart_buf, caption)
                else:
                    await_send_message(chat_id, caption)
            except Exception as e:
                print("Send to", chat_id, "failed:", e)
    else:
        print(sig["symbol"], "HOLD")

# small sync wrappers to use requests-based send (we're inside async app)
def await_send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=15)
    except Exception as e:
        print("tg send msg failed:", e)

def await_send_photo(chat_id, buf, caption):
    url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
    files = {"photo": ("chart.png", buf)}
    data = {"chat_id": chat_id, "caption": caption, "parse_mode": "Markdown"}
    try:
        requests.post(url, data=data, files=files, timeout=30)
    except Exception as e:
        print("tg send photo failed:", e)

# -----------------------
# job: analyze all symbols (runs in JobQueue)
def job_analyze(context: ContextTypes.DEFAULT_TYPE):
    # loop symbols
    for short, sym in SYMBOLS.items():
        try:
            analyze_symbol_and_send(context.application, sym)
        except Exception as e:
            print("Error in analyze_symbol_and_send:", e)

# -----------------------
# manual analyze command
async def analyze_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="🔍 Running immediate analysis (this may take a few seconds)...")
    # run analysis once synchronously (calls sends)
    for short, sym in SYMBOLS.items():
        analyze_symbol_and_send(context.application, sym)
    await context.bot.send_message(chat_id=update.effective_chat.id, text="✅ Analysis complete.")

# -----------------------
# main: setup bot app, handlers, and jobqueue
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("stop", remove_sub))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("analyze", analyze_cmd))

    # schedule job every 5 minutes (300s)
    jq = app.job_queue
    jq.run_repeating(job_analyze, interval=300, first=10)

    print("Bot starting (polling)...")
    app.run_polling()

if __name__ == "__main__":
    main()
