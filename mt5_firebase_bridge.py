"""
CHHUN-KEANG Private Market Desk — MT5 -> Firebase price bridge

Sends your broker's live gold (and EURUSD) prices from MetaTrader 5 to the desk.
Run it on the Windows PC where MT5 is open and logged in.

Setup (one time):
    pip install MetaTrader5 requests

Run:
    python mt5_firebase_bridge.py

The first run asks for your Firebase database secret and saves it next to this
script in firebase_secret.txt, so you only paste it once.
Where to find the secret: Firebase console -> project ck-market-desk ->
Project settings (gear) -> Service accounts -> Database secrets -> Show -> copy.
"""
import os, sys, time, threading
import MetaTrader5 as mt5
import requests

DB_URL = "https://ck-market-desk-default-rtdb.asia-southeast1.firebasedatabase.app"

# Broker symbol -> name on the desk. Edit the left side if your broker uses other names.
SYMBOLS = {
    "XAUUSDc": "XAUUSD",
    "EURUSDc": "EURUSD",
    "USTECc": "US100",
}

# US stocks: your broker has none, so these come from Yahoo Finance (free, no key, ~real-time
# in US market hours incl. pre/post-market). Sent only while that market is trading.
STOCKS = ["GOOGL", "NVDA", "AAPL", "MSFT", "TSLA", "SPY"]
STOCK_EVERY = 5    # seconds between stock checks
SEND_EVERY = 0.5   # seconds between checks
HEARTBEAT = 20     # resend even if price is unchanged, so the desk knows the feed is alive

here = os.path.dirname(os.path.abspath(__file__))
secret_file = os.path.join(here, "firebase_secret.txt")
if os.path.exists(secret_file):
    SECRET = open(secret_file).read().strip()
else:
    SECRET = input("Paste your Firebase database secret: ").strip()
    open(secret_file, "w").write(SECRET)
    print("Saved to firebase_secret.txt (keep this file private).")

if not mt5.initialize():
    sys.exit(f"Could not connect to MT5: {mt5.last_error()}  - is MT5 open and logged in?")

active = {}
for broker, desk in SYMBOLS.items():
    if mt5.symbol_select(broker, True):
        active[broker] = desk
        print(f"OK   {broker:10s} -> {desk}")
    else:
        print(f"SKIP {broker:10s} (not found at this broker)")
if not active:
    sys.exit("None of the symbols were found. Edit SYMBOLS at the top of this script.")

url = f"{DB_URL}/prices.json"

def send(update):
    r = requests.patch(url, params={"auth": SECRET}, json=update, timeout=5)
    if r.status_code == 401:
        print("\nFirebase refused the secret. Delete firebase_secret.txt and run again."); os._exit(1)
    r.raise_for_status()

def stock_loop():
    s = requests.Session(); s.headers["User-Agent"] = "Mozilla/5.0"
    last = {}
    while True:
        upd = {}
        for sym in STOCKS:
            try:
                j = s.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                          params={"interval": "1m", "range": "1d", "includePrePost": "true"}, timeout=8).json()
                res = j["chart"]["result"][0]
                ts, cl = res.get("timestamp") or [], res["indicators"]["quote"][0]["close"]
                pts = [(ts[i], cl[i]) for i in range(len(ts)) if cl[i] is not None]
                if not pts: continue
                t, px = pts[-1]
                if time.time() - t > 600: continue          # market closed: leave desk on simulation
                px = round(px, 2)
                if px != last.get(sym) or time.time() - last.get(sym + "_t", 0) > HEARTBEAT:
                    upd[sym] = {"px": px, "t": {".sv": "timestamp"}, "src": "yahoo"}
                    last[sym], last[sym + "_t"] = px, time.time()
            except Exception:
                pass
        if upd:
            try: send(upd)
            except requests.RequestException as e: print("\nStock send failed:", e)
        time.sleep(STOCK_EVERY)

threading.Thread(target=stock_loop, daemon=True).start()
print("US stocks: GOOGL NVDA AAPL MSFT TSLA SPY from Yahoo (live only while the US market is open)")
last_px, last_sent = {}, {}
print("Streaming to the desk. Leave this window open. Ctrl+C to stop.")
while True:
    update, now = {}, time.time()
    for broker, desk in active.items():
        t = mt5.symbol_info_tick(broker)
        if not t or not t.bid or not t.ask:
            continue
        px = round((t.bid + t.ask) / 2, 5)
        if px != last_px.get(desk) or now - last_sent.get(desk, 0) > HEARTBEAT:
            update[desk] = {"px": px, "bid": t.bid, "ask": t.ask, "t": {".sv": "timestamp"}}
            last_px[desk], last_sent[desk] = px, now
    if update:
        try:
            send(update)
            print(time.strftime("%H:%M:%S"), "  ".join(f"{k} {v['px']}" for k, v in update.items()), end="\r")
        except requests.RequestException as e:
            print("\nSend failed, retrying:", e)
            time.sleep(3)
    time.sleep(SEND_EVERY)
