# File: Super-trading-bot-V1.py
"""
Super-trading-bot-V1
Strategy: Simple Moving Average (SMA) crossover

BUY  when fast_sma crosses above slow_sma
SELL when fast_sma crosses below slow_sma
"""

from typing import List, Literal, Union

Price = Union[float, int]
Signal = Literal["BUY", "SELL", "FLAT"]


def simple_moving_average(prices: List[Price], period: int) -> List[float]:
    """Compute simple moving average for a list of prices."""
    if period <= 0:
        raise ValueError("period must be > 0")

    sma_values: List[float] = []
    window_sum = 0.0

    for i, p in enumerate(prices):
        window_sum += p
        if i >= period:
            window_sum -= prices[i - period]
        if i + 1 >= period:
            sma_values.append(window_sum / period)
        else:
            sma_values.append(float("nan"))  # Not enough data yet

    return sma_values


def generate_signals(
    prices: List[Price],
    fast_period: int = 10,
    slow_period: int = 20,
) -> List[Signal]:
    """Generate buy/sell signals based on SMA crossover."""
    if slow_period <= fast_period:
        raise ValueError("slow_period should be > fast_period")

    fast_sma = simple_moving_average(prices, fast_period)
    slow_sma = simple_moving_average(prices, slow_period)

    signals: List[Signal] = []
    prev_fast_above = None

    for f, s in zip(fast_sma, slow_sma):
        if any(map(lambda x: x != x, (f, s))):  # check NaN
            signals.append("FLAT")
            continue

        fast_above = f > s

        if prev_fast_above is None:
            signals.append("FLAT")
        elif not prev_fast_above and fast_above:
            signals.append("BUY")
        elif prev_fast_above and not fast_above:
            signals.append("SELL")
        else:
            signals.append("FLAT")

        prev_fast_above = fast_above

    return signals


def backtest(prices: List[Price], **params) -> float:
    """
    Very simple backtest:
    - Enter full long on BUY, flat on SELL.
    - Return cumulative PnL in points.
    """
    signals = generate_signals(prices, **params)
    position = 0  # 0=flat, 1=long
    entry_price = None
    pnl = 0.0

    for i in range(1, len(prices)):
        sig = signals[i]
        price = prices[i]

        if sig == "BUY" and position == 0:
            position = 1
            entry_price = price
        elif sig == "SELL" and position == 1:
            pnl += price - entry_price
            position = 0
            entry_price = None

    # Close any open position at last price
    if position == 1 and entry_price is not None:
        pnl += prices[-1] - entry_price

    return pnl


if _name_ == "_main_":
    # Example usage
    sample_prices = [i + (i % 5) for i in range(100)]
    result = backtest(sample_prices, fast_period=10, slow_period=30)
    print("Backtest PnL (points):", result)
