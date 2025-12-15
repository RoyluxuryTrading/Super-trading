import pandas as pd

def liquidity_sweep_strategy(df, lookback=10):
    """
    Detects liquidity sweep and reversal
    """

    df = df.copy()

    df["recent_high"] = df["high"].rolling(lookback).max()
    df["recent_low"] = df["low"].rolling(lookback).min()

    df["signal"] = 0

    # Sell after buy-side liquidity sweep
    df.loc[
        (df["high"] > df["recent_high"].shift(1)) &
        (df["close"] < df["open"]),
        "signal"
    ] = -1

    # Buy after sell-side liquidity sweep
    df.loc[
        (df["low"] < df["recent_low"].shift(1)) &
        (df["close"] > df["open"]),
        "signal"
    ] = 1

    return df
