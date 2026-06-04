<img width="514" height="353" alt="Screenshot 2026-06-03 at 4 56 06 PM" src="https://github.com/user-attachments/assets/4a11463c-1b25-488b-81f7-d27b0d79c9b0" />
<img width="1512" height="982" alt="Screenshot 2026-06-04 at 10 55 02 AM" src="https://github.com/user-attachments/assets/88a35462-4d7e-42cc-b819-0fe89616ac9a" />
<img width="1285" height="401" alt="Screenshot 2026-06-04 at 1 28 58 PM" src="https://github.com/user-attachments/assets/e29d7b66-2cc2-4e52-8a89-06e9c4db9cc8" />


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
.venv/bin/python main.py --strategy be-volume-hc-cool-rvol
.venv/bin/python main.py --strategy rsi-dip-reclaim-optimal
.venv/bin/python main.py --strategy rsi-dip-reclaim-precision
.venv/bin/python main.py --strategy rsi-dip-reclaim-expanded-80
.venv/bin/python main.py --strategy ema21-bounce-expanded
```

## Strategy Choices

`main.py --strategy all` runs every available strategy. `main.py --strategy
optimized` runs the curated optimized bundle configured in `main.py`, based on
the strongest discovery variants.

Current optimized bundle:

- `BE_VOLUME_REVERSAL_HIGH_CONFIDENCE`
- `BE_VOLUME_HC_MID_52W`
- `BE_VOLUME_HC_BALANCED`
- `BE_VOLUME_HC_COOL_RVOL`
- `RSI_DIP_RECLAIM_OPTIMAL`
- `RSI_DIP_RECLAIM_PRECISION`
- `RSI_DIP_RECLAIM_EXPANDED_80`
- `EMA21_BOUNCE_EXPANDED`

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
- `be-volume-hc-cool-rvol`
- `rsi-dip-reclaim-optimal`
- `rsi-dip-reclaim-precision`
- `rsi-dip-reclaim-expanded-80`
- `ema21-bounce-expanded`
- `optimized`
- `all`

## Strategy Rules And Backtest Results

These strategies were discovered with a one-month target-hit backtest. In that
backtest, a win meant the stock touched the target price within the next 30
trading days after the signal. Only the strategies listed in the current
optimized bundle above run when using `--strategy optimized`; additional
comparison strategies are kept here for reference and can still be run
individually.

### `BE_VOLUME_REVERSAL_RSI_65_68` Not In Optimized

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

Latest discovery result from `2020-01-01` to `2026-04-01`:

- Trades: `314`
- Target-hit win rate: `73.25%`
- Average exit return: `0.54%`
- Profit factor: `1.27`

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

Latest discovery result from `2020-01-01` to `2026-04-01`:

- Trades: `360`
- Target-hit win rate: `74.44%`
- Average exit return: `0.22%`
- Profit factor: `1.11`

### `BE_VOLUME_HC_MID_52W`

This is a stricter high-confidence bullish engulfing variant. It avoids stocks
that are exactly at the 52-week high and avoids extreme volume spikes.

Additional rules on top of `BE_VOLUME_REVERSAL_HIGH_CONFIDENCE`:

- RSI(14) must be between `58` and `66`.
- Relative volume must be at most `2.5`.
- Distance from 52-week high must be between `2%` and `8%`.
- Distance from 21 EMA must be at most `8%`.

Latest discovery result from `2020-01-01` to `2026-04-01`:

- Trades: `97`
- Target-hit win rate: `81.44%`
- Average exit return: `0.55%`
- Profit factor: `1.28`

### `BE_VOLUME_HC_BALANCED`

This is a balanced version of the high-confidence bullish engulfing setup. It
requires the stock to be close to trend support, but not too stretched.

Additional rules on top of `BE_VOLUME_REVERSAL_HIGH_CONFIDENCE`:

- RSI(14) must be between `60` and `68`.
- Relative volume must be at most `2.5`.
- Distance from 52-week high must be between `2%` and `8%`.
- Distance from 21 EMA must be between `1%` and `6%`.

Latest discovery result from `2020-01-01` to `2026-04-01`:

- Trades: `76`
- Target-hit win rate: `73.68%`
- Average exit return: `0.86%`
- Profit factor: `1.46`

### `BE_VOLUME_HC_EARLY_SURGE` Not In Optimized

This is an early-surge version of the high-confidence bullish engulfing setup.
It looks for a controlled volume reversal close to the 52-week high.

Additional rules on top of `BE_VOLUME_REVERSAL_HIGH_CONFIDENCE`:

- RSI(14) must be between `58` and `66`.
- Relative volume must be at most `2.5`.
- Distance from 52-week high must be at most `5%`.
- Distance from 21 EMA must be between `1%` and `6%`.

Latest discovery result from `2020-01-01` to `2026-04-01`:

- Trades: `103`
- Target-hit win rate: `66.99%`
- Average exit return: `0.51%`
- Profit factor: `1.26`

### `BE_VOLUME_HC_COOL_RVOL`

This is a broader high-confidence bullish engulfing variant. It keeps the
strong reversal setup but avoids very large relative-volume spikes, which often
come after the move is already crowded.

Additional rules on top of `BE_VOLUME_REVERSAL_HIGH_CONFIDENCE`:

- RSI(14) must be between `58` and `66`.
- Relative volume must be at most `2.5`.
- Distance from 52-week high must be at most `5%`.
- Distance from 21 EMA must be at most `8%`.

Latest discovery result from `2020-01-01` to `2026-04-01`:

- Trades: `159`
- Target-hit win rate: `74.21%`
- Average exit return: `0.33%`
- Profit factor: `1.16`

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

Latest discovery result from `2020-01-01` to `2026-04-01`:

- Trades: `476`
- Target-hit win rate: `78.78%`
- Average exit return: `0.89%`
- Profit factor: `1.48`

### `RSI_DIP_RECLAIM_OPTIMAL`

This is the tighter RSI dip-reclaim setup. It looks for the same RSI dip below
50 and 21 EMA reclaim, but keeps the trade closer to the 21 EMA and requires a
moderate volume expansion.

Rules:

- 3-month return must be positive.
- RSI(14) must have dipped below `50` within the previous 10 trading days.
- Latest RSI(14) must reclaim above `55`.
- Previous close must be below the 21 EMA.
- Current close must reclaim and close above the 21 EMA.
- Close must be above 50 DMA, and 50 DMA must be above 200 DMA.
- RSI(14) must be between `58` and `68`.
- Relative volume must be between `1.2` and `3.0`.
- Distance from 52-week high must be between `2%` and `10%`.
- Distance from 21 EMA must be at most `3%`.
- Average traded value must be at least Rs 5 crore.
- Stock price must be at least Rs 50.

Latest discovery result from `2020-01-01` to `2026-04-01`:

- Trades: `157`
- Target-hit win rate: `74.52%`
- Average exit return: `1.43%`
- Profit factor: `1.95`

### `RSI_DIP_RECLAIM_PRECISION`

This is the most selective RSI dip-reclaim setup. It avoids both weaker RSI
reclaims and hotter volume spikes, so it produced fewer trades but a higher
target-hit rate in the discovery run.

Rules:

- 3-month return must be positive.
- RSI(14) must have dipped below `50` within the previous 10 trading days.
- Latest RSI(14) must reclaim above `55`.
- Previous close must be below the 21 EMA.
- Current close must reclaim and close above the 21 EMA.
- Close must be above 50 DMA, and 50 DMA must be above 200 DMA.
- RSI(14) must be between `58` and `65`.
- Relative volume must be at least `1.0` and at most `2.0`.
- Distance from 52-week high must be between `3%` and `10%`.
- Distance from 21 EMA must be at most `3%`.
- Average traded value must be at least Rs 5 crore.
- Stock price must be at least Rs 50.

Latest discovery result from `2020-01-01` to `2026-04-01`:

- Trades: `119`
- Target-hit win rate: `74.79%`
- Average exit return: `1.39%`
- Profit factor: `1.89`

### `EMA21_BOUNCE_EXPANDED`

This is a broader trend-continuation pullback setup. It looks for a stock above
its key moving averages that pulls back to the 21 EMA, then closes strongly back
near the top of the candle range.

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

Latest discovery result from `2020-01-01` to `2026-04-01`:

- Trades: `1988`
- Target-hit win rate: `76.31%`
- Average exit return: `0.56%`
- Profit factor: `1.28`

### `RANGE_BREAKOUT_VOLUME_RSI_65_68` Not In Optimized

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

Latest discovery result from `2020-01-01` to `2026-04-01`:

- Trades: `420`
- Target-hit win rate: `73.57%`
- Average exit return: `0.68%`
- Profit factor: `1.36`

### `MOMENTUM_PULLBACK_TIGHT_EMA` Not In Optimized

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

Latest discovery result from `2020-01-01` to `2026-04-01`:

- Trades: `399`
- Target-hit win rate: `70.93%`
- Average exit return: `1.10%`
- Profit factor: `1.65`

## Backtesting And Discovery

The discovery script reruns the one-month backtest for the active discovery
variants and creates two CSV files:

```bash
.venv/bin/python strategy_discovery_backtest.py --start-date 2020-01-01 --end-date 2026-04-01 --trades-output strategy_discovery_trades.csv --summary-output strategy_discovery_summary.csv
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

Recent discovery results for all `main.py` strategies from `2020-01-01` to
`2026-04-01`:

- `BE_VOLUME_HC_MID_52W`: `97` trades, `81.44%` target-hit win rate.
- `RSI_DIP_RECLAIM_EXPANDED_80`: `476` trades, `78.78%` target-hit win rate.
- `EMA21_BOUNCE_EXPANDED`: `1988` trades, `76.31%` target-hit win rate.
- `RSI_DIP_RECLAIM_PRECISION`: `119` trades, `74.79%` target-hit win rate.
- `RSI_DIP_RECLAIM_OPTIMAL`: `157` trades, `74.52%` target-hit win rate.
- `BE_VOLUME_REVERSAL_HIGH_CONFIDENCE`: `360` trades, `74.44%` target-hit win rate.
- `BE_VOLUME_HC_COOL_RVOL`: `159` trades, `74.21%` target-hit win rate.
- `BE_VOLUME_HC_BALANCED`: `76` trades, `73.68%` target-hit win rate.
- `RANGE_BREAKOUT_VOLUME_RSI_65_68`: `420` trades, `73.57%` target-hit win rate.
- `BE_VOLUME_REVERSAL_RSI_65_68`: `314` trades, `73.25%` target-hit win rate.
- `MOMENTUM_PULLBACK_TIGHT_EMA`: `399` trades, `70.93%` target-hit win rate.
- `NSE_21_EMA_PULLBACK`: `9042` trades, `68.25%` target-hit win rate.
- `BE_VOLUME_HC_EARLY_SURGE`: `103` trades, `66.99%` target-hit win rate.
- `NSE_21_EMA_PULLBACK_2_0`: `2383` trades, `66.47%` target-hit win rate.

## Supabase

`main.py` can still save signals to Supabase when called with:

```bash
.venv/bin/python main.py --strategy optimized --save-db
```

Required environment variables:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

`SUPABASE_ANON_KEY` can also work if your table policies allow inserts.
