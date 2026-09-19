# NSE Stock Automator

This project screens NSE equity stocks using daily Yahoo Finance data. The
scanner currently runs two active swing-trading strategies:

- `rsi-dip-reclaim-expanded-80`
- `ema21-bounce-expanded`

## Setup

```bash
python3 -m pip install -r requirements.txt
```

If you already use the local virtual environment:

```bash
.venv/bin/python main.py --help
```

## Running The Scanner

Scan all NSE EQ stocks with every active strategy:

```bash
.venv/bin/python main.py
```

Scan the optimized bundle:

```bash
.venv/bin/python main.py --strategy optimized
```

Scan selected symbols:

```bash
.venv/bin/python main.py --symbols RELIANCE TCS INFY --strategy optimized
```

Save scanner output to CSV:

```bash
.venv/bin/python main.py --strategy optimized --output optimized_signals.csv
```

Run one specific active strategy:

```bash
.venv/bin/python main.py --strategy rsi-dip-reclaim-expanded-80
.venv/bin/python main.py --strategy ema21-bounce-expanded
```

## Strategy Choices

`main.py --strategy all` runs every active strategy. `main.py --strategy
optimized` currently runs the same two-strategy bundle.

Available strategy keys:

- `rsi-dip-reclaim-expanded-80`
- `ema21-bounce-expanded`
- `optimized`
- `all`

## Strategy Rules

### `RSI_DIP_RECLAIM_EXPANDED_80`

This is a non-candlestick pullback strategy. It looks for a stock in a positive
3-month trend where RSI dipped below 50, then reclaimed strength while price
also reclaimed the 21 EMA.

Rules:

- 3-month return must be positive.
- RSI(14) must have dipped below `50` within the previous 10 trading days.
- Latest RSI(14) must reclaim above `55`.
- Previous close must be below the 21 EMA.
- Current close must reclaim and close above the 21 EMA.
- Close must be above 50 DMA, and 50 DMA must be above 200 DMA.
- RSI(14) must be between `55` and `65`.
- Relative volume must be between `1.0` and `2.0`.
- Distance from 52-week high must be between `5%` and `12%`.
- Distance from 21 EMA must be between `3%` and `6%`.
- Average traded value must be at least Rs 5 crore.
- Stock price must be at least Rs 50.

### `EMA21_BOUNCE_EXPANDED`

This is a trend-continuation pullback setup. It looks for a stock above its key
moving averages that pulls back to the 21 EMA, then closes strongly near the top
of the candle range.

Rules:

- Close must be above 21 EMA, 21 EMA above 50 DMA, and 50 DMA above 200 DMA.
- Latest low must touch or come within `1%` of the 21 EMA.
- Current close must be above current open.
- Current volume must be greater than previous day volume.
- Stock must have had a recent 3-8 trading-day pullback.
- Current close must be in the top `35%` of the daily candle range.
- RSI(14) must be between `58` and `68`.
- Relative volume must be between `0.8` and `2.0`.
- Distance from 52-week high must be between `3%` and `12%`.
- Distance from 21 EMA must be between `2%` and `6%`.
- Average traded value must be at least Rs 5 crore.
- Stock price must be at least Rs 50.

## Supabase

`main.py` can save signals to Supabase when called with:

```bash
.venv/bin/python main.py --strategy optimized --save-db
```

Required environment variables:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

`SUPABASE_ANON_KEY` can also work if your table policies allow inserts.
