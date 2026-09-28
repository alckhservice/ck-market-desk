"""
CHHUN-KEANG Private Market Desk - price bridge (v2, runs by itself)

Sends live prices to the desk through Firebase:
  - Gold, EURUSD, US100, US500, US30 from your MT5 terminal
  - GOOGL, NVDA, AAPL, MSFT, TSLA, SPY from Yahoo Finance (free, no key)
  - Intraday candles (1m 3m 5m 15m 30m 1H 4H) for all of them, for the desk's timeframe buttons

It starts automatically when you log in to Windows (scheduled task "CK Market Desk Bridge"),
runs hidden, starts MT5 if it isn't open, and reconnects on its own after MT5 restarts,
internet drops or sleep. Activity is written to bridge.log in this folder.

Manual run (shows output):   python mt5_firebase_bridge.py
"""
import os, sys, time, socket, threading, datetime
import MetaTrader5 as mt5
import requests

DB_URL = "https://ck-market-desk-default-rtdb.asia-southeast1.firebasedatabase.app"

# Broker symbol -> name on the desk. Edit the left side if your broker uses other names.
SYMBOLS = {
    "XAUUSDc": "XAUUSD",
    "EURUSDc": "EURUSD",
    "USTECc": "US100",
    "US500c": "US500",
    "US30c": "US30",
}
STOCKS = ["GOOGL", "NVDA", "AAPL", "MSFT", "TSLA", "SPY"]

SEND_EVERY = 0.5     # seconds between MT5 price checks
STOCK_EVERY = 5      # seconds between stock checks while the US market trades
HEARTBEAT = 20       # resend unchanged prices so the desk knows the bridge is alive
RETRY_MT5 = 30       # seconds between attempts to (re)connect to MT5
CANDLE_BARS = 300    # intraday candles kept per symbol and timeframe
TFS = ["1m", "3m", "5m", "15m", "30m", "1H", "4H"]

here = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(here, "bridge.log")
HIDDEN = sys.stdout is None or os.path.basename(sys.executable).lower().startswith("pythonw")


def log(*a):
    line = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S ") + " ".join(str(x) for x in a)
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > 1_000_000:
            os.replace(LOG, LOG + ".old")
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    if not HIDDEN:
        print(line)


# Only one copy may run (the scheduled task and a manual run would otherwise both send).
try:
    _lock = socket.socket(); _lock.bind(("127.0.0.1", 47651))
except OSError:
    log("Another copy of the bridge is already running - exiting.")
    sys.exit(0)

secret_file = os.path.join(here, "firebase_secret.txt")
if os.path.exists(secret_file):
    SECRET = open(secret_file).read().strip()
elif not HIDDEN:
    SECRET = input("Paste your Firebase database secret: ").strip()
    open(secret_file, "w").write(SECRET)
else:
    log("firebase_secret.txt is missing - run the bridge once by hand to paste the secret.")
    sys.exit(1)

URL = f"{DB_URL}/prices.json"
http = requests.Session()


def send(update):
    r = http.patch(URL, params={"auth": SECRET}, json=update, timeout=8)
    if r.status_code == 401:
        log("Firebase refused the secret. Delete firebase_secret.txt and run the bridge once by hand.")
        os._exit(1)
    r.raise_for_status()


def safe_send(update, what):
    try:
        send(update)
        return True
    except requests.RequestException as e:
        log(f"{what} send failed (will retry): {e.__class__.__name__}")
        return False


_candle_hash = {}


def put_candles(sym, tf, rows):
    """rows: list of (t, o, h, l, c, v). Stored as one compact string per symbol/timeframe."""
    if not rows:
        return
    txt = ";".join("%d,%s,%s,%s,%s,%d" % (t, _n(o), _n(h), _n(l), _n(c), v) for t, o, h, l, c, v in rows)
    key = (sym, tf)
    if _candle_hash.get(key) == hash(txt):
        return
    try:
        r = http.put(f"{DB_URL}/candles/{sym}/{tf}.json", params={"auth": SECRET}, json=txt, timeout=15)
        r.raise_for_status()
        _candle_hash[key] = hash(txt)
    except requests.RequestException as e:
        log(f"Candles {sym} {tf} send failed: {e.__class__.__name__}")


def _n(x):
    s = ("%.5f" % x).rstrip("0").rstrip(".")
    return s or "0"


def _agg(rows, secs, align=0):
    """Aggregate (t,o,h,l,c,v) rows into bigger bars of `secs` seconds."""
    out = []
    for t, o, h, l, c, v in rows:
        b = t - ((t - align) % secs)
        if out and out[-1][0] == b:
            B = out[-1]; out[-1] = (b, B[1], max(B[2], h), min(B[3], l), c, B[5] + v)
        else:
            out.append((b, o, h, l, c, v))
    return out


# ---------------- US stocks (Yahoo) ----------------
YAHOO_TF = {  # desk tf: (yahoo interval, range, aggregate-to seconds or None)
    "1m": ("1m", "1d", None), "3m": ("1m", "5d", 180), "5m": ("5m", "5d", None), "15m": ("15m", "5d", None),
    "30m": ("30m", "1mo", None), "1H": ("60m", "1mo", None), "4H": ("60m", "3mo", 14400),
}


def stock_candles(y, sym, open_now, tick):
    for tf, (iv, rng, agg) in YAHOO_TF.items():
        every = 60 if tf in ("1m", "3m", "5m") else 300
        if not open_now:
            every = 3600
        k = (sym, tf)
        if tick - _stock_candle_t.get(k, 0) < every:
            continue
        try:
            j = y.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                      params={"interval": iv, "range": rng}, timeout=10).json()
            res = j["chart"]["result"][0]; q = res["indicators"]["quote"][0]
            rows = [(t, q["open"][i], q["high"][i], q["low"][i], q["close"][i], int(q["volume"][i] or 0))
                    for i, t in enumerate(res.get("timestamp") or []) if q["close"][i] is not None and q["open"][i] is not None]
            if agg:
                rows = _agg(rows, agg, align=rows[0][0] % 3600 if rows and agg == 14400 else 0)
            put_candles(sym, tf, rows[-CANDLE_BARS:])
            _stock_candle_t[k] = tick
        except Exception:
            pass


_stock_candle_t = {}


def stock_loop():
    y = requests.Session(); y.headers["User-Agent"] = "Mozilla/5.0"
    last, last_t, was_open = {}, {}, {}
    while True:
        upd, any_open = {}, False
        for sym in STOCKS:
            try:
                j = y.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                          params={"interval": "1m", "range": "1d", "includePrePost": "true"}, timeout=10).json()
                res = j["chart"]["result"][0]
                ts, cl = res.get("timestamp") or [], res["indicators"]["quote"][0]["close"]
                pts = [(ts[i], cl[i]) for i in range(len(ts)) if cl[i] is not None]
                if pts:
                    t, px = pts[-1]
                else:
                    t, px = 0, res["meta"].get("regularMarketPrice")
                if not px:
                    continue
                px = round(px, 2)
                is_open = time.time() - t < 600
                any_open |= is_open
                changed = px != last.get(sym) or is_open != was_open.get(sym)
                due = time.time() - last_t.get(sym, 0) > (HEARTBEAT if is_open else 300)
                if changed or due:
                    upd[sym] = {"px": px, "t": {".sv": "timestamp"}, "src": "yahoo",
                                "closed": not is_open, "tt": int(t * 1000)}
                    last[sym], last_t[sym], was_open[sym] = px, time.time(), is_open
            except Exception:
                pass
        if upd:
            safe_send(upd, "Stock")
        for sym in STOCKS:
            stock_candles(y, sym, was_open.get(sym, False), time.time())
        time.sleep(STOCK_EVERY if any_open else 60)


# ---------------- MT5 ----------------
def connect_mt5():
    """Connect to MT5, starting the terminal if needed. Returns {broker: desk} or {}."""
    mt5.shutdown()
    if not mt5.initialize():
        log("MT5 not reachable:", mt5.last_error(), f"- retrying in {RETRY_MT5}s")
        return {}
    acc = mt5.account_info()
    if acc is None:
        log("MT5 is open but not logged in - retrying.")
        return {}
    active = {}
    for broker, desk in SYMBOLS.items():
        if mt5.symbol_select(broker, True):
            active[broker] = desk
        else:
            log(f"SKIP {broker} (not found at this broker)")
    log(f"MT5 connected (account {acc.login}, {acc.server}): " + ", ".join(active.values()))
    return active


MT5_TF = {}


def mt5_candles(active, force=False):
    """Push intraday candles when a new bar starts (checked cheaply with 1 bar), or when forced."""
    if not MT5_TF:
        MT5_TF.update({"1m": mt5.TIMEFRAME_M1, "3m": mt5.TIMEFRAME_M3, "5m": mt5.TIMEFRAME_M5,
                       "15m": mt5.TIMEFRAME_M15, "30m": mt5.TIMEFRAME_M30, "1H": mt5.TIMEFRAME_H1, "4H": mt5.TIMEFRAME_H4})
    for broker, desk in active.items():
        for tf, code in MT5_TF.items():
            k = (desk, tf)
            last = mt5.copy_rates_from_pos(broker, code, 0, 1)
            if last is None or not len(last):
                continue
            bt = int(last[-1]["time"])
            if not force and _mt5_bar_t.get(k) == bt and time.time() - _mt5_push_t.get(k, 0) < 300:
                continue
            r = mt5.copy_rates_from_pos(broker, code, 0, CANDLE_BARS)
            if r is None:
                continue
            put_candles(desk, tf, [(int(x["time"]), float(x["open"]), float(x["high"]), float(x["low"]),
                                    float(x["close"]), int(x["tick_volume"])) for x in r])
            _mt5_bar_t[k], _mt5_push_t[k] = bt, time.time()


_mt5_bar_t, _mt5_push_t = {}, {}


def mt5_loop():
    active, last_px, last_sent, dead_since = {}, {}, {}, None
    next_candles = 0
    while True:
        if not active:
            active = connect_mt5()
            if not active:
                time.sleep(RETRY_MT5)
                continue
            dead_since = None
            mt5_candles(active, force=True)
        update, now, got = {}, time.time(), 0
        if now >= next_candles:
            mt5_candles(active); next_candles = now + 2
        for broker, desk in active.items():
            t = mt5.symbol_info_tick(broker)
            if not t or not t.bid or not t.ask:
                continue
            got += 1
            px = round((t.bid + t.ask) / 2, 5)
            tick_ms = int(t.time_msc) if getattr(t, "time_msc", 0) else int(t.time) * 1000
            if px != last_px.get(desk) or now - last_sent.get(desk, 0) > HEARTBEAT:
                update[desk] = {"px": px, "bid": t.bid, "ask": t.ask, "t": {".sv": "timestamp"}, "tt": tick_ms}
                last_px[desk], last_sent[desk] = px, now
        if got == 0:
            dead_since = dead_since or now
            if now - dead_since > 15:
                log("Lost MT5 connection - reconnecting.")
                active = {}
                continue
        else:
            dead_since = None
        if update:
            if safe_send(update, "MT5") and not HIDDEN:
                print(time.strftime("%H:%M:%S"), "  ".join(f"{k} {v['px']}" for k, v in update.items()), end="\r")
            elif not update:
                pass
        time.sleep(SEND_EVERY)


log("Bridge starting" + (" (hidden)" if HIDDEN else ""))
threading.Thread(target=stock_loop, daemon=True).start()
while True:
    try:
        mt5_loop()
    except Exception as e:           # never die: log and restart the loop
        log("Unexpected error, restarting MT5 loop:", repr(e))
        time.sleep(5)
