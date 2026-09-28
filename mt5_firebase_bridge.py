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
import os, sys, time
import MetaTrader5 as mt5
import requests

DB_URL = "https://ck-market-desk-default-rtdb.asia-southeast1.firebasedatabase.app"

# Broker symbol -> name on the desk. Edit the left side if your broker uses other names.
SYMBOLS = {
    "XAUUSDc": "XAUUSD",
    "EURUSDc": "EURUSD",
}
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
            r = requests.patch(url, params={"auth": SECRET}, json=update, timeout=5)
            if r.status_code == 401:
                sys.exit("Firebase refused the secret. Delete firebase_secret.txt and run again.")
            r.raise_for_status()
            print(time.strftime("%H:%M:%S"), "  ".join(f"{k} {v['px']}" for k, v in update.items()), end="\r")
        except requests.RequestException as e:
            print("\nSend failed, retrying:", e)
            time.sleep(3)
    time.sleep(SEND_EVERY)
