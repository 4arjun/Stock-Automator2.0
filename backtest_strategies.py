#!/usr/bin/env python3
"""
One-time backtest runner for the existing NSE 21 EMA pullback strategies.

This script does not write to Supabase and does not modify main.py. It imports
the existing strategy functions, scans each completed trading day in the
backtest window, and writes trigger/performance rows to a separate CSV file.

Examples:
    python3 backtest_strategies.py
    python3 backtest_strategies.py --strategy 2.0 --output backtest_v2.csv
    python3 backtest_strategies.py --symbols RELIANCE TCS INFY
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd
import yfinance as yf

from main import (
    chunks,
    fetch_nse_symbols,
    flatten_downloaded_data,
    iso_date_from_index,
    nse_symbol,
    screen_history,
    selected_strategy_versions,
    yahoo_symbol,
)


DEFAULT_START_DATE = "2026-01-01"
DEFAULT_OUTPUT = "strategy_backtest_from_2026-01-01.csv"
WARMUP_DAYS = 450
FORWARD_WINDOWS = (1, 5, 21, 63)
DAILY_CLOSE_DAYS = 30


@dataclass(frozen=True)
class BacktestConfig:
    start_date: str
    end_date: str
    batch_size: int
    sleep_seconds: float
    output: str
    strategy: str
    max_symbols: int | None


def parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use YYYY-MM-DD format.") from exc


def download_backtest_histories(symbols: list[str], config: BacktestConfig) -> dict[str, pd.DataFrame]:
    histories: dict[str, pd.DataFrame] = {}
    start = (parse_date(config.start_date) - timedelta(days=WARMUP_DAYS)).isoformat()
    end = (parse_date(config.end_date) + timedelta(days=1)).isoformat()
    total_batches = math.ceil(len(symbols) / config.batch_size)

    for index, symbol_batch in enumerate(chunks(symbols, config.batch_size), start=1):
        tickers = [yahoo_symbol(symbol) for symbol in symbol_batch]
        print(f"Downloading batch {index}/{total_batches} ({len(tickers)} stocks)...", file=sys.stderr)

        try:
            data = yf.download(
                tickers=tickers,
                start=start,
                end=end,
                interval="1d",
                group_by="ticker",
                auto_adjust=False,
                progress=False,
                threads=True,
            )
        except Exception as exc:
            print(f"Skipping batch {index}: {exc}", file=sys.stderr)
            continue

        for ticker, history in flatten_downloaded_data(data, tickers).items():
            clean_history = history.dropna(how="all").copy()
            if not clean_history.empty:
                histories[nse_symbol(ticker)] = clean_history

        if index < total_batches and config.sleep_seconds:
            time.sleep(config.sleep_seconds)

    return histories


def pct_return(exit_price: float | None, entry_price: float) -> float | None:
    if exit_price is None or entry_price <= 0:
        return None
    return (exit_price - entry_price) / entry_price * 100


def price_at_offset(history: pd.DataFrame, trigger_position: int, offset: int) -> float | None:
    target_position = trigger_position + offset
    if target_position >= len(history):
        return None
    close_price = history.iloc[target_position].get("Close")
    if pd.isna(close_price):
        return None
    return float(close_price)


def performance_values(history: pd.DataFrame, trigger_date: pd.Timestamp, entry_price: float) -> dict[str, float | int | str | None]:
    trigger_position = history.index.get_loc(trigger_date)
    if isinstance(trigger_position, slice) or not isinstance(trigger_position, int):
        return {}

    future = history.iloc[trigger_position:].dropna(subset=["High", "Low", "Close"])
    latest_close = None if future.empty else float(future.iloc[-1]["Close"])
    latest_date = "" if future.empty else iso_date_from_index(future.index[-1])

    values: dict[str, float | int | str | None] = {
        "Latest Date": latest_date,
        "Latest Close": latest_close,
        "Trading Days Held": max(len(future) - 1, 0),
        "Return to Latest Close (%)": pct_return(latest_close, entry_price),
        "Max Favorable Move (%)": None,
        "Max Drawdown (%)": None,
    }

    first_month = future.head(DAILY_CLOSE_DAYS + 1)
    if not first_month.empty:
        values["Max Favorable Move (%)"] = pct_return(float(first_month["High"].max()), entry_price)
        values["Max Drawdown (%)"] = pct_return(float(first_month["Low"].min()), entry_price)

    for offset in FORWARD_WINDOWS:
        exit_price = price_at_offset(history, trigger_position, offset)
        values[f"{offset}D Close"] = exit_price
        values[f"{offset}D Return (%)"] = pct_return(exit_price, entry_price)

    for offset in range(1, DAILY_CLOSE_DAYS + 1):
        values[f"Day {offset} Close"] = price_at_offset(history, trigger_position, offset)

    return values


def completed_history(history: pd.DataFrame) -> pd.DataFrame:
    required_columns = ["Open", "High", "Low", "Close", "Volume"]
    available_columns = [column for column in required_columns if column in history.columns]
    if len(available_columns) != len(required_columns):
        return pd.DataFrame()
    cleaned = history.dropna(subset=required_columns).copy()
    return cleaned[cleaned["Volume"] > 0]


def backtest_symbol(symbol: str, history: pd.DataFrame, config: BacktestConfig) -> list[dict[str, float | int | str | None]]:
    history = completed_history(history)
    if history.empty:
        return []

    start_ts = pd.Timestamp(config.start_date)
    end_ts = pd.Timestamp(config.end_date)
    backtest_dates = [index for index in history.index if start_ts <= pd.Timestamp(index) <= end_ts]
    rows: list[dict[str, float | int | str | None]] = []

    for index in backtest_dates:
        index_ts = pd.Timestamp(index)
        history_to_date = history.loc[:index_ts]
        for trigger in screen_history(symbol, history_to_date, config.strategy):
            entry_price = float(trigger["Close Price"])
            rows.append(
                {
                    **trigger,
                    **performance_values(history, index_ts, entry_price),
                }
            )

    return rows


def sort_backtest_rows(rows: list[dict[str, float | int | str | None]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()

    frame = pd.DataFrame(rows)
    return frame.sort_values(
        by=["Triggered Date", "Strategy Name", "Symbol"],
        ascending=[True, True, True],
    ).reset_index(drop=True)


def parse_args() -> argparse.Namespace:
    today = date.today().isoformat()
    parser = argparse.ArgumentParser(description="Backtest existing NSE strategy triggers and write a CSV.")
    parser.add_argument(
        "--symbols",
        nargs="+",
        help="Optional NSE symbols to backtest, for example: RELIANCE TCS INFY. Defaults to all NSE EQ stocks.",
    )
    parser.add_argument("--start-date", type=parse_date, default=parse_date(DEFAULT_START_DATE), help="Default: 2026-01-01.")
    parser.add_argument("--end-date", type=parse_date, default=parse_date(today), help=f"Default: {today}.")
    parser.add_argument("--batch-size", type=int, default=80, help="Yahoo Finance batch size. Default: 80.")
    parser.add_argument("--sleep", type=float, default=1.0, help="Seconds to sleep between batches. Default: 1.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help=f"CSV output path. Default: {DEFAULT_OUTPUT}.")
    parser.add_argument("--max-symbols", type=int, help="Limit the number of NSE symbols processed after sorting.")
    parser.add_argument(
        "--strategy",
        choices=["all", "1.0", "2.0"],
        default="all",
        help="Strategy version to run. Default: all.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.end_date < args.start_date:
        print("--end-date must be on or after --start-date.", file=sys.stderr)
        return 2

    config = BacktestConfig(
        start_date=args.start_date.isoformat(),
        end_date=args.end_date.isoformat(),
        batch_size=args.batch_size,
        sleep_seconds=args.sleep,
        output=args.output,
        strategy=args.strategy,
        max_symbols=args.max_symbols,
    )

    symbols = [symbol.upper().replace(".NS", "") for symbol in args.symbols] if args.symbols else fetch_nse_symbols()
    if config.max_symbols is not None:
        if config.max_symbols <= 0:
            print("--max-symbols must be greater than 0.", file=sys.stderr)
            return 2
        symbols = symbols[: config.max_symbols]

    strategies = ", ".join(selected_strategy_versions(config.strategy))
    print(
        f"Backtesting {len(symbols)} NSE stocks from {config.start_date} to {config.end_date} "
        f"with strategy={strategies}...",
        file=sys.stderr,
    )

    histories = download_backtest_histories(symbols, config)
    rows: list[dict[str, float | int | str | None]] = []
    for index, symbol in enumerate(symbols, start=1):
        history = histories.get(symbol)
        if history is None:
            continue
        rows.extend(backtest_symbol(symbol, history, config))
        if index % 100 == 0:
            print(f"Processed {index}/{len(symbols)} stocks, found {len(rows)} triggers...", file=sys.stderr)

    frame = sort_backtest_rows(rows)
    frame.to_csv(config.output, index=False)
    print(f"Saved {len(frame)} backtest rows to {config.output}")
    if frame.empty:
        print("No strategy triggers were found in the selected window.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
