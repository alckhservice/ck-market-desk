# CHHUN-KEANG Private Market Desk

Screener, charts and rule-based signals. Live: https://alckhservice.github.io/ck-market-desk/

- Daily bars: TradingView (delayed/EOD) embedded in `index.html`
- BTC/ETH: live from Binance public WebSocket in the browser
- Gold, EURUSD, US100, US500, US30: live from your MT5 via Firebase Realtime Database (`mt5_firebase_bridge.py`)
- US stocks (GOOGL NVDA AAPL MSFT TSLA SPY): Yahoo Finance via the same bridge, while the US market is open

## Live gold from MT5

On the Windows PC with MT5 open:

```
pip install MetaTrader5 requests
python mt5_firebase_bridge.py
```

First run asks for the Firebase database secret (Firebase console → ck-market-desk → Project settings → Service accounts → Database secrets). It is saved locally in `firebase_secret.txt`, which is never committed.

## Timeframes

Chart buttons 1m 3m 5m 15m 30m 1H 4H 1D 1W. Intraday candles come from your MT5 (gold, EURUSD, indices), Binance (crypto) and Yahoo (US stocks), published by the bridge to Firebase `candles/`.

## Backtest & challenge report

Backtest tab: 5 setups (EMA pullback, Donchian breakout, RSI reversal, MACD cross, Asian-range London breakout) on 5m–1D history, scored against prop-style challenge rules (target, daily loss, static/trailing max loss, min days) with equity curve, daily P&L, stats, trade log and a shuffled pass-probability. History: `hist/` in Firebase from your MT5 (gold, EURUSD), Yahoo (stocks, index futures) and Binance (crypto).

## Runs by itself

The bridge is registered as the Windows scheduled task **CK Market Desk Bridge**. It starts hidden at logon, opens MT5 if needed, and reconnects after drops. Log: `Documents\CK-Market-Desk\bridge.log`.

Each watchlist row shows **LIVE**, **CLOSED** (market shut, last real price) or **SIM** (no feed).
