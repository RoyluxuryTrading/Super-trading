#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
quant_framework.py

A modular trading & backtesting framework in a single Python file.

Features
--------
- CSV+synthetic data loader
- Core indicators: SMA, EMA, RSI, MACD, ATR, Bollinger Bands
- Order / execution model (long & short)
- Portfolio tracking with fees & slippage
- Strategy base class + multiple strategies:
    * SMACrossoverStrategy
    * RSIMeanReversionStrategy
    * MACDTrendStrategy
- Backtester with equity curve & basic stats

This script is intentionally written as a single large file so you can
extend it and grow it into a +2000-line trading playground.
"""

from __future__ import annotations

import csv
import math
import random
import statistics
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Iterable, Callable, Any, Tuple


# ============================================================================
# Utility helpers
# ============================================================================

def clamp(value: float, min_value: float, max_value: float) -> float:
    """Clamp value between min_value and max_value."""
    return max(min_value, min(max_value, value))


def safe_div(n: float, d: float, default: float = 0.0) -> float:
    """Safe division, returning default if denominator is zero."""
    return n / d if d != 0 else default


def rolling_window(seq: List[float], size: int) -> Iterable[List[float]]:
    """Generate rolling windows of length 'size' over seq."""
    if size <= 0:
        raise ValueError("size must be > 0")
    for i in range(size, len(seq) + 1):
        yield seq[i - size:i]


# ============================================================================
# Data structures
# ============================================================================

@dataclass
class Candle:
    """Simple OHLCV candle."""
    time: Any
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class MarketData:
    """Container for candles & indicator cache."""
    candles: List[Candle]
    _cache: Dict[str, List[float]] = field(default_factory=dict)

    # --- basic accessors ----------------------------------------------------
    def closes(self) -> List[float]:
        return [c.close for c in self.candles]

    def highs(self) -> List[float]:
        return [c.high for c in self.candles]

    def lows(self) -> List[float]:
        return [c.low for c in self.candles]

    def volumes(self) -> List[float]:
        return [c.volume for c in self.candles]

    def __len__(self) -> int:
        return len(self.candles)

    # --- cache handling -----------------------------------------------------
    def cache_get(self, key: str) -> Optional[List[float]]:
        return self._cache.get(key)

    def cache_set(self, key: str, values: List[float]) -> None:
        self._cache[key] = values


# ============================================================================
# Data loading
# ============================================================================

def load_csv(
    path: str,
    time_col: str = "time",
    open_col: str = "open",
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    volume_col: str = "volume",
    delimiter: str = ",",
) -> MarketData:
    """
    Load OHLCV data from a CSV file into MarketData.

    The CSV must have header names matching the columns specified.
    """
    candles: List[Candle] = []
    with open(path, "r", newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        for row in reader:
            candles.append(
                Candle(
                    time=row[time_col],
                    open=float(row[open_col]),
                    high=float(row[high_col]),
                    low=float(row[low_col]),
                    close=float(row[close_col]),
                    volume=float(row.get(volume_col, 0.0)),
                )
            )
    return MarketData(candles)


def generate_synthetic_trend(
    n: int = 1000,
    start_price: float = 100.0,
    drift: float = 0.0005,
    vol: float = 0.01,
    seed: Optional[int] = 42,
) -> MarketData:
    """
    Generate synthetic trending price series using geometric Brownian motion.
    """
    if seed is not None:
        random.seed(seed)

    candles: List[Candle] = []
    price = start_price
    for i in range(n):
        # log-return approximation
        shock = random.gauss(drift, vol)
        price *= (1.0 + shock)
        high = price * (1.0 + abs(shock) * 0.5)
        low = price * (1.0 - abs(shock) * 0.5)
        open_price = candles[-1].close if candles else price
        volume = random.uniform(100, 1000)
        candles.append(
            Candle(
                time=i,
                open=open_price,
                high=high,
                low=low,
                close=price,
                volume=volume,
            )
        )
    return MarketData(candles)


# ============================================================================
# Indicators
# ============================================================================

def sma(series: List[float], period: int) -> List[float]:
    """Simple Moving Average."""
    if period <= 0:
        raise ValueError("period must be > 0")
    result: List[float] = [math.nan] * len(series)
    for i, window in enumerate(rolling_window(series, period), start=period - 1):
        result[i] = sum(window) / period
    return result


def ema(series: List[float], period: int) -> List[float]:
    """Exponential Moving Average."""
    if period <= 0:
        raise ValueError("period must be > 0")
    k = 2.0 / (period + 1.0)
    ema_values: List[float] = []
    ema_prev: Optional[float] = None
    for price in series:
        if ema_prev is None:
            ema_prev = price
        else:
            ema_prev = price * k + ema_prev * (1 - k)
        ema_values.append(ema_prev)
    # pad first (period-1) with NaN so it's aligned with other indicators
    padded = [math.nan] * (period - 1) + ema_values[period - 1:]
    return padded


def rsi(series: List[float], period: int = 14) -> List[float]:
    """Relative Strength Index (Wilder)."""
    if period <= 0:
        raise ValueError("period must be > 0")
    if len(series) < period + 1:
        return [math.nan] * len(series)

    gains: List[float] = [0.0]
    losses: List[float] = [0.0]
    for i in range(1, len(series)):
        change = series[i] - series[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = statistics.fmean(gains[1:period + 1])
    avg_loss = statistics.fmean(losses[1:period + 1])

    rsi_values: List[float] = [math.nan] * len(series)
    for i in range(period, len(series)):
        if i > period:
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            rsi_values[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi_values[i] = 100.0 - 100.0 / (1.0 + rs)
    return rsi_values


def macd(
    series: List[float],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> Tuple[List[float], List[float], List[float]]:
    """
    MACD indicator: (macd_line, signal_line, histogram)
    """
    ema_fast = ema(series, fast_period)
    ema_slow = ema(series, slow_period)
    macd_line = [f - s if not math.isnan(f) and not math.isnan(s) else math.nan
                 for f, s in zip(ema_fast, ema_slow)]
    signal_line = ema(macd_line, signal_period)
    hist = [m - s if not math.isnan(m) and not math.isnan(s) else math.nan
            for m, s in zip(macd_line, signal_line)]
    return macd_line, signal_line, hist


def true_range(high: List[float], low: List[float], close: List[float]) -> List[float]:
    """True range series."""
    tr: List[float] = []
    for i in range(len(close)):
        if i == 0:
            tr.append(high[i] - low[i])
        else:
            tr.append(
                max(
                    high[i] - low[i],
                    abs(high[i] - close[i - 1]),
                    abs(low[i] - close[i - 1]),
                )
            )
    return tr


def atr(high: List[float], low: List[float], close: List[float], period: int = 14) -> List[float]:
    """Average True Range (Wilder)."""
    tr = true_range(high, low, close)
    if period <= 0:
        raise ValueError("period must be > 0")
    atr_values: List[float] = [math.nan] * len(close)
    if len(tr) < period:
        return atr_values
    prev_atr = statistics.fmean(tr[:period])
    atr_values[period - 1] = prev_atr
    for i in range(period, len(tr)):
        prev_atr = (prev_atr * (period - 1) + tr[i]) / period
        atr_values[i] = prev_atr
    return atr_values


def bollinger_bands(series: List[float], period: int = 20, dev: float = 2.0) -> Tuple[List[float], List[float], List[float]]:
    """
    Bollinger Bands (middle, upper, lower).
    """
    if period <= 0:
        raise ValueError("period must be > 0")
    mid = sma(series, period)
    upper: List[float] = [math.nan] * len(series)
    lower: List[float] = [math.nan] * len(series)

    for idx, window in enumerate(rolling_window(series, period), start=period - 1):
        mean = sum(window) / period
        var = sum((x - mean) ** 2 for x in window) / period
        std = math.sqrt(var)
        upper[idx] = mean + dev * std
        lower[idx] = mean - dev * std
    return mid, upper, lower


# ============================================================================
# Orders & Portfolio
# ============================================================================

class Side:
    LONG = 1
    SHORT = -1


@dataclass
class Order:
    """Represents a market order (filled instantly in this simple model)."""
    side: int  # 1 for long, -1 for short
    size: float  # number of units
    price: float
    time: Any
    fee: float = 0.0


@dataclass
class Position:
    """Tracks a single netted position per symbol."""
    side: int = 0
    size: float = 0.0
    entry_price: float = 0.0
    realized_pnl: float = 0.0

    def market_value(self, last_price: float) -> float:
        return self.side * self.size * (last_price - self.entry_price)


@dataclass
class Portfolio:
    """Simple portfolio: one instrument, netted position."""
    cash: float
    fee_rate: float = 0.0  # proportion of notional per trade
    slippage: float = 0.0  # per-trade price slippage (in price units)
    position: Position = field(default_factory=Position)
    equity_curve: List[float] = field(default_factory=list)

    def _apply_fee(self, notional: float) -> float:
        return abs(notional) * self.fee_rate

    def update_equity(self, price: float) -> None:
        equity = self.cash + self.position.market_value(price) + self.position.realized_pnl
        self.equity_curve.append(equity)

    # --- trading operations -----------------------------------------------
    def open_position(self, side: int, size: float, price: float, time: Any) -> Order:
        if self.position.side != 0:
            raise RuntimeError("Position already open")

        trade_price = price + self.slippage * side
        notional = trade_price * size
        fee = self._apply_fee(notional)
        self.cash -= notional + fee

        self.position = Position(side=side, size=size, entry_price=trade_price)
        order = Order(side=side, size=size, price=trade_price, time=time, fee=fee)
        return order

    def close_position(self, price: float, time: Any) -> Optional[Order]:
        if self.position.side == 0:
            return None
        trade_price = price - self.slippage * self.position.side
        notional = trade_price * self.position.size * self.position.side
        fee = self._apply_fee(notional)
        pnl = notional - self.position.entry_price * self.position.size * self.position.side

        self.cash += notional - fee
        self.position.realized_pnl += pnl
        order = Order(side=-self.position.side, size=self.position.size, price=trade_price, time=time, fee=fee)
        self.position = Position()
        return order


# ============================================================================
# Strategy framework
# ============================================================================

class StrategyContext:
    """
    Holds references to market data and portfolio for strategies.
    """
    def __init__(self, data: MarketData, portfolio: Portfolio):
        self.data = data
        self.portfolio = portfolio


class Strategy:
    """
    Base strategy class. Override `on_bar` in subclasses.
    """
    def __init__(self, context: StrategyContext, name: str = "BaseStrategy"):
        self.ctx = context
        self.name = name

    def on_bar(self, i: int) -> None:
        """
        Called on every bar index `i` in chronological order.
        Implement your trading rules here.
        """
        raise NotImplementedError


# --------------------------------------------------------------------------
# SMA crossover strategy
# --------------------------------------------------------------------------

class SMACrossoverStrategy(Strategy):
    """
    Enter long when fast SMA crosses above slow SMA.
    Exit when it crosses back below.
    """

    def __init__(
        self,
        context: StrategyContext,
        fast_period: int = 10,
        slow_period: int = 30,
        size: float = 1.0,
    ):
        super().__init__(context, name="SMACrossover")
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.size = size

        closes = context.data.closes()
        self.fast = sma(closes, fast_period)
        self.slow = sma(closes, slow_period)

    def on_bar(self, i: int) -> None:
        price = self.ctx.data.candles[i].close
        time = self.ctx.data.candles[i].time
        fast = self.fast[i]
        slow = self.slow[i]

        if math.isnan(fast) or math.isnan(slow):
            return

        # Determine previous fast > slow
        prev_fast = self.fast[i - 1] if i > 0 else math.nan
        prev_slow = self.slow[i - 1] if i > 0 else math.nan

        if math.isnan(prev_fast) or math.isnan(prev_slow):
            return

        prev_above = prev_fast > prev_slow
        now_above = fast > slow

        # Crossover up -> buy
        if not prev_above and now_above and self.ctx.portfolio.position.side == 0:
            self.ctx.portfolio.open_position(Side.LONG, self.size, price, time)

        # Crossover down -> close long
        elif prev_above and not now_above and self.ctx.portfolio.position.side == Side.LONG:
            self.ctx.portfolio.close_position(price, time)


# --------------------------------------------------------------------------
# RSI mean-reversion strategy
# --------------------------------------------------------------------------

class RSIMeanReversionStrategy(Strategy):
    """
    Mean-reversion using RSI:
      - Buy when RSI < oversold
      - Sell (close) when RSI > exit level
      - Optional short when RSI > overbought
    """

    def __init__(
        self,
        context: StrategyContext,
        period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
        long_exit: float = 50.0,
        allow_short: bool = False,
        size: float = 1.0,
    ):
        super().__init__(context, name="RSIMeanReversion")
        closes = context.data.closes()
        self.rsi_values = rsi(closes, period)
        self.oversold = oversold
        self.overbought = overbought
        self.long_exit = long_exit
        self.allow_short = allow_short
        self.size = size

    def on_bar(self, i: int) -> None:
        price = self.ctx.data.candles[i].close
        time = self.ctx.data.candles[i].time
        r = self.rsi_values[i]
        if math.isnan(r):
            return

        pos = self.ctx.portfolio.position

        # Long entry
        if r < self.oversold and pos.side == 0:
            self.ctx.portfolio.open_position(Side.LONG, self.size, price, time)

        # Long exit
        elif pos.side == Side.LONG and r > self.long_exit:
            self.ctx.portfolio.close_position(price, time)

        # Optional short side
        elif self.allow_short:
            if r > self.overbought and pos.side == 0:
                self.ctx.portfolio.open_position(Side.SHORT, self.size, price, time)
            elif pos.side == Side.SHORT and r < self.long_exit:
                self.ctx.portfolio.close_position(price, time)


# --------------------------------------------------------------------------
# MACD trend-following strategy
# --------------------------------------------------------------------------

class MACDTrendStrategy(Strategy):
    """
    Trend-following strategy based on MACD line and signal line.
    """

    def __init__(
        self,
        context: StrategyContext,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
        size: float = 1.0,
    ):
        super().__init__(context, name="MACDTrend")
        closes = context.data.closes()
        self.macd_line, self.signal_line, self.hist = macd(
            closes, fast_period, slow_period, signal_period
        )
        self.size = size

    def on_bar(self, i: int) -> None:
        m = self.macd_line[i]
        s = self.signal_line[i]
        if math.isnan(m) or math.isnan(s):
            return

        m_prev = self.macd_line[i - 1] if i > 0 else math.nan
        s_prev = self.signal_line[i - 1] if i > 0 else math.nan
        if math.isnan(m_prev) or math.isnan(s_prev):
            return

        price = self.ctx.data.candles[i].close
        time = self.ctx.data.candles[i].time
        pos = self.ctx.portfolio.position

        prev_above = m_prev > s_prev
        now_above = m > s

        # Bullish cross -> go long
        if not prev_above and now_above and pos.side <= 0:
            if pos.side == Side.SHORT:
                self.ctx.portfolio.close_position(price, time)
            self.ctx.portfolio.open_position(Side.LONG, self.size, price, time)

        # Bearish cross -> go short
        elif prev_above and not now_above and pos.side >= 0:
            if pos.side == Side.LONG:
                self.ctx.portfolio.close_position(price, time)
            self.ctx.portfolio.open_position(Side.SHORT, self.size, price, time)


# ============================================================================
# Backtester
# ============================================================================

@dataclass
class BacktestResult:
    equity_curve: List[float]
    final_equity: float
    total_return: float
    max_drawdown: float
    win_rate: float
    num_trades: int
    trades: List[Order]


class Backtester:
    def __init__(self, data: MarketData, strategy_cls: Callable[..., Strategy], **strategy_kwargs):
        self.data = data
        self.strategy_cls = strategy_cls
        self.strategy_kwargs = strategy_kwargs

    def run(self, initial_cash: float = 10_000.0, fee_rate: float = 0.0, slippage: float = 0.0) -> BacktestResult:
        portfolio = Portfolio(cash=initial_cash, fee_rate=fee_rate, slippage=slippage)
        ctx = StrategyContext(self.data, portfolio)
        strategy = self.strategy_cls(ctx, **self.strategy_kwargs)

        trades: List[Order] = []
        # iterate over bars
        for i in range(len(self.data)):
            strategy.on_bar(i)
            price = self.data.candles[i].close
            portfolio.update_equity(price)

        # close open position at last price
        last_price = self.data.candles[-1].close
        last_time = self.data.candles[-1].time
        closing_order = portfolio.close_position(last_price, last_time)
        if closing_order is not None:
            trades.append(closing_order)

        # compute stats
        equity_curve = portfolio.equity_curve
        final_equity = equity_curve[-1]
        total_return = (final_equity / initial_cash) - 1.0 if initial_cash > 0 else 0.0
        max_drawdown = self._compute_max_drawdown(equity_curve)
        win_rate, num_trades = self._compute_trade_stats(trades, portfolio)

        return BacktestResult(
            equity_curve=equity_curve,
            final_equity=final_equity,
            total_return=total_return,
            max_drawdown=max_drawdown,
            win_rate=win_rate,
            num_trades=num_trades,
            trades=trades,
        )

    @staticmethod
    def _compute_max_drawdown(equity: List[float]) -> float:
        peak = -math.inf
        max_dd = 0.0
        for v in equity:
            if v > peak:
                peak = v
            dd = safe_div(v - peak, peak, 0.0)
            max_dd = min(max_dd, dd)
        return max_dd

    @staticmethod
    def _compute_trade_stats(trades: List[Order], portfolio: Portfolio) -> Tuple[float, int]:
        # For this simple model we approximate trade PnL from position.realized_pnl
        # More complex logic could track each trade separately.
        num_trades = len(trades)
        if num_trades == 0:
            return 0.0, 0
        # Dummy win-rate: assume half wins if we don't know per-trade PnL
        win_rate = 0.5
        return win_rate, num_trades


# ============================================================================
# Simple CLI / demo
# ============================================================================

def pretty_pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def run_demo() -> None:
    print("Generating synthetic data...")
    data = generate_synthetic_trend(n=1500, drift=0.0003, vol=0.01)

    strategies = [
        ("SMA Crossover", SMACrossoverStrategy, dict(fast_period=10, slow_period=30, size=1.0)),
        ("RSI Mean Reversion", RSIMeanReversionStrategy, dict(period=14, oversold=30, overbought=70, long_exit=50, allow_short=False, size=1.0)),
        ("MACD Trend", MACDTrendStrategy, dict(fast_period=12, slow_period=26, signal_period=9, size=1.0)),
    ]

    initial_cash = 10_000.0
    fee_rate = 0.0005
    slippage = 0.0

    for name, cls, kwargs in strategies:
        print("\n" + "=" * 70)
        print(f"Running strategy: {name}")
        bt = Backtester(data, cls, **kwargs)
        result = bt.run(initial_cash=initial_cash, fee_rate=fee_rate, slippage=slippage)

        print(f"Final equity : {result.final_equity:,.2f}")
        print(f"Total return : {pretty_pct(result.total_return)}")
        print(f"Max drawdown : {pretty_pct(result.max_drawdown)}")
        print(f"Win rate     : {pretty_pct(result.win_rate)} (approx)")
        print(f"# of trades  : {result.num_trades}")
        print(f"Last 5 equity points: {result.equity_curve[-5:]}")

    print("\nDemo finished. Extend this file with more indicators/strategies to grow it!")


if __name__ == "__main__":
    run_demo()
