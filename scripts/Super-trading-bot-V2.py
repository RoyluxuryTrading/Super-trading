# File: Super-trading-bot-V2.py
"""
Super-trading-bot-V2
Strategy: SMA crossover + RSI filter
- Only BUY if RSI < 70
- Only SELL if RSI > 30
"""

from typing import List, Literal, Union

Price = Union[float, int]
Signal = Literal["BUY", "SELL", "FLAT"]


def sma(prices: List[Price], period: int) -> List[float]:
    window_sum = 0.0
    values: List[float] = []
    for i, p in enumerate(prices):
        window_sum += p
        if i >= period:
            window_sum -= prices[i - period]
        if i + 1 >= period:
            values.append(window_sum / period)
        else:
            values.append(float("nan"))
    return values


def rsi(prices: List[Price], period: int = 14) -> List[float]:
    """Very simple RSI calculation."""
    if period <= 0:
        raise ValueError("period must be > 0")

    gains: List[float] = [0.0]
    losses: List[float] = [0.0]

    for i in range(1, len(prices)):
        change = prices[i] - prices[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain: List[float] = []
    avg_loss: List[float] = []
    rsi_values: List[float] = []

    gain_sum = 0.0
    loss_sum = 0.0

    for i in range(len(prices)):
        if i == 0:
            avg_gain.append(float("nan"))
            avg_loss.append(float("nan"))
            rsi_values.append(float("nan"))
            continue

        gain_sum += gains[i]
        loss_sum += losses[i]

        if i < period:
            avg_gain.append(float("nan"))
            avg_loss.append(float("nan"))
            rsi_values.append(float("nan"))
            continue

        if i == period:
            avg_gain_value = gain_sum / period
            avg_loss_value = loss_sum / period
        else:
            avg_gain_value = (avg_gain[-1] * (period - 1) + gains[i]) / period
            avg_loss_value = (avg_loss[-1] * (period - 1) + losses[i]) / period

        avg_gain.append(avg_gain_value)
        avg_loss.append(avg_loss_value)

        if avg_loss_value == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gain_value / avg_loss_value
            rsi_values.append(100.0 - (100.0 / (1 + rs)))

    return rsi_values


def generate_signals(
    prices: List[Price],
    fast_period: int = 10,
    slow_period: int = 30,
    rsi_period: int = 14,
    rsi_buy_limit: float = 70.0,
    rsi_sell_limit: float = 30.0,
) -> List[Signal]:
    fast = sma(prices, fast_period)
    slow = sma(prices, slow_period)
    rsi_values = rsi(prices, rsi_period)

    signals: List[Signal] = []
    prev_fast_above = None

    for f, s, r in zip(fast, slow, rsi_values):
        if any(map(lambda x: x != x, (f, s, r))):  # NaN
            signals.append("FLAT")
            continue

        fast_above = f > s

        if prev_fast_above is None:
            signals.append("FLAT")
        elif not prev_fast_above and fast_above and r < rsi_buy_limit:
            signals.append("BUY")
        elif prev_fast_above and not fast_above and r > rsi_sell_limit:
            signals.append("SELL")
        else:
            signals.append("FLAT")

        prev_fast_above = fast_above

    return signals


def backtest(prices: List[Price], **params) -> float:
    signals = generate_signals(prices, **params)
    position = 0
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

    if position == 1 and entry_price is not None:
        pnl += prices[-1] - entry_price

    return pnl


if _name_ == "_main_":
    sample_prices = [100 + (i % 7) - 3 for i in range(200)]
    print("V2 PnL:", backtest(sample_prices))
