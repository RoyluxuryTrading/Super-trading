import pandas as pd

def rsi_ema_trend_strategy(df, rsi_period=14, ema_period=50):
    """
    Buy when RSI < 30 and price above EMA
    Sell when RSI > 70 and price below EMA
    """

    df = df.copy()

    # EMA
    df["EMA"] = df["close"].ewm(span=ema_period, adjust=False).mean()

    # RSI
    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(rsi_period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(rsi_period).mean()
    rs = gain / loss
    df["RSI"] = 100 - (100 / (1 + rs))

    # Signals
    df["signal"] = 0
    df.loc[(df["RSI"] < 30) & (df["close"] > df["EMA"]), "signal"] = 1
    df.loc[(df["RSI"] > 70) & (df["close"] < df["EMA"]), "signal"] = -1

    return df
