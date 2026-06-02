# NSE Stock Automator

This project screens NSE equity stocks using daily Yahoo Finance data. The main
scanner is `main.py`; discovery/backtesting experiments live in separate scripts
so production screening can stay simple.

## Setup

```bash
python3 -m pip install -r requirements.txt
```

If you already use the local virtual environment:

```bash
.venv/bin/python main.py --help
```

## Running The Scanner

Scan all NSE EQ stocks with every strategy:

```bash
.venv/bin/python main.py
```

Scan only the optimized strategies:

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

Run one specific strategy:

```bash
.venv/bin/python main.py --strategy be-volume-rsi-65-68
.venv/bin/python main.py --strategy be-volume-high-confidence
.venv/bin/python main.py --strategy range-breakout-rsi-65-68
.venv/bin/python main.py --strategy momentum-tight-ema
.venv/bin/python main.py --strategy be-volume-hc-mid-52w
.venv/bin/python main.py --strategy be-volume-hc-balanced
.venv/bin/python main.py --strategy be-volume-hc-early-surge
```

## Strategy Choices

`main.py --strategy all` runs the original two strategies plus the optimized
strategies. `main.py --strategy optimized` runs only the optimized strategies.

Available strategy keys:

- `1.0`
- `2.0`
- `be-volume-rsi-65-68`
- `be-volume-high-confidence`
- `range-breakout-rsi-65-68`
- `momentum-tight-ema`
- `be-volume-hc-mid-52w`
- `be-volume-hc-balanced`
- `be-volume-hc-early-surge`
- `optimized`
- `all`

## Optimized Strategy Rules

The optimized strategies were discovered with a one-month target-hit backtest.
In that backtest, a win meant the stock touched the target price within the next
30 trading days after the signal.

### `BE_VOLUME_REVERSAL_RSI_65_68`

This is a strict bullish engulfing reversal setup.

Rules:

- Current candle must be a bullish engulfing candle.
- Previous candle must be bearish.
- Current close must be above the previous candle high.
- Current volume must be at least `1.2x` average 20-day volume.
- Close must be above the 200 DMA.
- RSI(14) must be between `65` and `68`.
- Relative volume must be at least `1.2`.
- Close must be within `10%` of the 52-week high.
- Close must not be more than `8%` away from the 21 EMA.
- Average traded value must be at least Rs 5 crore.
- Stock price must be at least Rs 50.

### `BE_VOLUME_REVERSAL_HIGH_CONFIDENCE`

This is a tighter version of the bullish engulfing volume reversal setup. It
requires stronger relative volume and closer 52-week-high positioning.

Rules:

- Current candle must be a bullish engulfing candle.
- Previous candle must be bearish.
- Current close must be above the previous candle high.
- Current volume must be at least `1.2x` average 20-day volume.
- Close must be above the 200 DMA.
- RSI(14) must be between `62` and `68`.
- Relative volume must be at least `1.5`.
- Close must be within `5%` of the 52-week high.
- Close must not be more than `8%` away from the 21 EMA.
- Average traded value must be at least Rs 5 crore.
- Stock price must be at least Rs 50.

### `BE_VOLUME_HC_MID_52W`

This is a stricter high-confidence bullish engulfing variant. It avoids stocks
that are exactly at the 52-week high and avoids extreme volume spikes.

Additional rules on top of `BE_VOLUME_REVERSAL_HIGH_CONFIDENCE`:

- RSI(14) must be between `58` and `66`.
- Relative volume must be at most `2.5`.
- Distance from 52-week high must be between `2%` and `8%`.
- Distance from 21 EMA must be at most `8%`.

Latest discovery result from `2025-01-01` to `2026-06-03`:

- Trades: `15`
- Target-hit win rate: `100.00%`

### `BE_VOLUME_HC_BALANCED`

This is a balanced version of the high-confidence bullish engulfing setup. It
requires the stock to be close to trend support, but not too stretched.

Additional rules on top of `BE_VOLUME_REVERSAL_HIGH_CONFIDENCE`:

- RSI(14) must be between `60` and `68`.
- Relative volume must be at most `2.5`.
- Distance from 52-week high must be between `2%` and `8%`.
- Distance from 21 EMA must be between `1%` and `6%`.

Latest discovery result from `2025-01-01` to `2026-06-03`:

- Trades: `15`
- Target-hit win rate: `93.33%`

### `BE_VOLUME_HC_EARLY_SURGE`

This is an early-surge version of the high-confidence bullish engulfing setup.
It looks for a controlled volume reversal close to the 52-week high.

Additional rules on top of `BE_VOLUME_REVERSAL_HIGH_CONFIDENCE`:

- RSI(14) must be between `58` and `66`.
- Relative volume must be at most `2.5`.
- Distance from 52-week high must be at most `5%`.
- Distance from 21 EMA must be between `1%` and `6%`.

Latest discovery result from `2025-01-01` to `2026-06-03`:

- Trades: `13`
- Target-hit win rate: `92.31%`

### `RANGE_BREAKOUT_VOLUME_RSI_65_68`

This is a non-candlestick breakout strategy. It looks for a strong close above
the prior 20-day high with high volume.

Rules:

- Current close must break above the previous 20-day high.
- Current volume must be at least `1.5x` average 20-day volume.
- Relative volume must be at least `2.0`.
- Close must be above 21 EMA, 21 EMA above 50 DMA, and 50 DMA above 200 DMA.
- RSI(14) must be between `65` and `68`.
- Close must be within `8%` of the 52-week high.
- Close must not be more than `8%` away from the 21 EMA.
- Current close must be in the top 25% of the daily candle range.
- Average traded value must be at least Rs 5 crore.
- Stock price must be at least Rs 50.

### `MOMENTUM_PULLBACK_TIGHT_EMA`

This strategy looks for a stock already in momentum, pulling back to the 21 EMA,
then reclaiming it.

Rules:

- 3-month return must be positive.
- Stock must have had a recent 3-8 trading-day pullback.
- Previous close must be below the 21 EMA.
- Current close must reclaim and close above the 21 EMA.
- Current candle must close above its open.
- Current volume must be greater than previous day volume.
- RSI(14) must be between `55` and `70`.
- Relative volume must be at least `0.8`.
- Close must be within `10%` of the 52-week high.
- Close must be within `1.5%` of the 21 EMA.
- Average traded value must be at least Rs 5 crore.
- Stock price must be at least Rs 50.

## Backtesting And Discovery

The discovery script reruns the one-month backtest for only the optimized
strategies and creates two CSV files:

```bash
.venv/bin/python strategy_discovery_backtest.py --start-date 2025-01-01 --end-date 2026-06-03 --trades-output strategy_discovery_trades.csv --summary-output strategy_discovery_summary.csv
```

Outputs:

- `strategy_discovery_trades.csv`: one row per stock signal.
- `strategy_discovery_summary.csv`: one row per strategy with win rate and
  performance stats.

The discovery win rate is based on whether the target percent was touched within
the next 30 trading days. The current discovery defaults are:

- Target: `5%`
- Stop: `4%`
- Holding window: `30` trading days
- Universe cap: `2400` sorted NSE EQ symbols

## Supabase

`main.py` can still save signals to Supabase when called with:

```bash
.venv/bin/python main.py --strategy optimized --save-db
```

Required environment variables:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

`SUPABASE_ANON_KEY` can also work if your table policies allow inserts.
