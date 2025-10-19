# main.py
# Telegram trading signal bot (experimental)

BOT_TOKEN = "8461165121:AAG3rQ5GFkv-Jmw-6GxHaQ56p-tgXLopp_A"
TARGET_CHAT_ID = "690864747"  # تم وضع رقم الشات اللي عطيتني إياه

import time
import io
from datetime import datetime, timezone
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from pycoingecko import CoinGeckoAPI
import mplfinance as mpf
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Bot, InputFile

bot = Bot(token=BOT_TOKEN)
cg = CoinGeckoAPI()

SYMBOLS = [
    {"name": "Bitcoin", "type": "crypto", "id": "bitcoin", "label": "BTC/USDT"},
    {"name": "Gold", "type": "yfinance", "ticker": "GC=F", "label": "XAU/USD"},
    {"name": "EUR/USD", "type": "yfinance", "ticker": "EURUSD=X", "label": "EUR/USD"},
    {"name": "USD/JPY", "type": "yfinance", "ticker": "JPY=X", "label": "USD/JPY"},
]

def rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.ewm(com=period - 1, adjust=False).mean()
    ma_down = down.ewm(com=period - 1, adjust=False).mean()
    rs = ma_up / ma_down
    return 100 - (100 / (1 + rs))

def atr(df, period=14):
    high_low = df['High'] - df['Low']
    high_close = (df['High'] - df['Close'].shift()).abs()
    low_close = (df['Low'] - df['Close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(period).mean().iloc[-1]

def fetch_crypto_ohlcv(coin_id, vs_currency='usd'):
    data = cg.get_coin_market_chart_by_id(id=coin_id, vs_currency=vs_currency, days=2)
    prices = data['prices']
    df = pd.DataFrame(prices, columns=['ts', 'price'])
    df['datetime'] = pd.to_datetime(df['ts'], unit='ms')
    df = df.set_index('datetime').drop(columns=['ts'])
    return df['price']

def fetch_yfinance_ohlcv(ticker, period="7d", interval="1m"):
    try:
        data = yf.download(tickers=ticker, period=period, interval=interval, progress=False, threads=False)
        if data is None or data.empty:
            return pd.DataFrame()
        data.index = pd.to_datetime(data.index)
        return data[['Open','High','Low','Close','Volume']]
    except Exception as e:
        print("yf error", e)
        return pd.DataFrame()

def build_ohlc_from_series(price_series, resample_rule='60T'):
    ohlc = price_series.resample(resample_rule).ohlc()
    ohlc['Volume'] = 0
    ohlc.dropna(inplace=True)
    return ohlc

def is_market_open(symbol):
    if symbol['type'] == 'crypto':
        return True
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False
    return True

def analyze_ohlc(df):
    if df is None or df.empty:
        return {"signal":"no_data"}
    close = df['Close']
    r = rsi(close)
    sma_short = close.rolling(window=9).mean()
    sma_long = close.rolling(window=21).mean()
    last_rsi = r.iloc[-1]
    last_close = close.iloc[-1]
    last_sma_short = sma_short.iloc[-1]
    last_sma_long = sma_long.iloc[-1]
    if last_rsi < 30 and last_sma_short > last_sma_long:
        side = "BUY"
    elif last_rsi > 70 and last_sma_short < last_sma_long:
        side = "SELL"
    else:
        side = "HOLD"
    try:
        a = atr(df)
    except:
        a = (df['High'].max() - df['Low'].min()) * 0.5
    if side == "BUY":
        sl = last_close - a * 1.5
        tp = last_close + a * 3
    elif side == "SELL":
        sl = last_close + a * 1.5
        tp = last_close - a * 3
    else:
        sl = None
        tp = None
    return {
        "signal": side,
        "rsi": round(float(last_rsi),2),
        "close": float(last_close),
        "sl": float(sl) if sl else None,
        "tp": float(tp) if tp else None,
        "atr": float(a)
    }

def plot_candles(df, title="Chart"):
    buf = io.BytesIO()
    mc = mpf.make_marketcolors(up='g', down='r', inherit=True)
    s = mpf.make_mpf_style(base_mpf_style='nightclouds', marketcolors=mc)
    try:
        mpf.plot(df, type='candle', style=s, title=title, ylabel='Price', savefig=dict(fname=buf, dpi=100, bbox_inches='tight'))
        buf.seek(0)
        return buf
    except Exception as e:
        print("mpl error", e)
        return None

def job_send_signals():
    now = datetime.now(timezone.utc)
    print("Running job at", now.isoformat())
    for sym in SYMBOLS:
        try:
            if not is_market_open(sym):
                print(f"Market closed for {sym['label']}, skipping.")
                continue
            if sym['type'] == 'crypto':
                s = fetch_crypto_ohlcv(sym['id'])
                ohlc = build_ohlc_from_series(s, resample_rule='60T')
            else:
                ohlc = fetch_yfinance_ohlcv(sym['ticker'])
                if ohlc.empty:
                    continue
                ohlc = ohlc.resample('60T').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'})
                ohlc.dropna(inplace=True)
            analysis = analyze_ohlc(ohlc)
            if analysis['signal'] in ["HOLD","no_data"]:
                continue
            df_plot = ohlc.tail(50)
            buf = plot_candles(df_plot, title=f"{sym['label']} - {analysis['signal']}")
            msg = f"*{sym['label']}* — _{analysis['signal']}_\n"
            msg += f"Price: `{analysis['close']:.4f}`\nRSI: `{analysis['rsi']}`  ATR: `{analysis['atr']:.4f}`\n"
            if analysis['sl'] and analysis['tp']:
                msg += f"SL: `{analysis['sl']:.4f}`  TP: `{analysis['tp']:.4f}`\n"
            msg += f"\n_Timeframe: 1H (entry 5m)_\nICT Concept – demo_"
            if buf:
                buf.seek(0)
                bot.send_photo(chat_id=TARGET_CHAT_ID, photo=InputFile(buf, filename=f"{sym['label']}.png"), caption=msg, parse_mode='Markdown')
                print("sent", sym['label'])
            else:
                bot.send_message(chat_id=TARGET_CHAT_ID, text=msg, parse_mode='Markdown')
        except Exception as e:
            print("error for", sym, e)

if __name__ == "__main__":
    scheduler = BackgroundScheduler()
    scheduler.add_job(job_send_signals, 'interval', minutes=5, next_run_time=datetime.now())
    scheduler.start()
    print("Bot started — will send updates every 5 minutes.")
    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        scheduler.shutdown()
