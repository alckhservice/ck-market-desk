# CHHUN-KEANG Private Market Desk

Screener, charts and rule-based signals. Live: https://alckhservice.github.io/ck-market-desk/

- Daily bars: TradingView (delayed/EOD) embedded in `index.html`
- BTC/ETH: live from Binance public WebSocket in the browser
- Gold/EURUSD: live from your MT5 via Firebase Realtime Database (`mt5_firebase_bridge.py`)
- Other symbols: simulated ticks until a live feed is connected

## Live gold from MT5

On the Windows PC with MT5 open:

```
pip install MetaTrader5 requests
python mt5_firebase_bridge.py
```

First run asks for the Firebase database secret (Firebase console → ck-market-desk → Project settings → Service accounts → Database secrets). It is saved locally in `firebase_secret.txt`, which is never committed.
