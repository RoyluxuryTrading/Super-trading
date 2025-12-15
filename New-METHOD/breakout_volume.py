import pandas as pd

def breakout_volume_strategy(df, lookback=20, volume_multiplier=1.5):
    """
    Buy on breakout with strong volume
    Sell on breakdown with strong volume
    """

    df = df.copy()

    df["high_level"] = df["high"].rolling(lookback).max()
    df["low_level"] = df["low"].rolling(lookback).min()
    df["avg_volume"] = df["volume"].rolling(lookback).mean()

    df["signal"] = 0

    df.loc[
        (df["close"] > df["high_level"].shift(1)) &
        (df["volume"] > df["avg_volume"] * volume_multiplier),
        "signal"
    ] = 1

    df.loc[
        (df["close"] < df["low_level"].shift(1)) &
        (df["volume"] > df["avg_volume"] * volume_multiplier),
        "signal"
    ] = -1

    return df
