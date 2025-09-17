# -----------------------------
# ATR Grid Strategy Backtester with Real Binance Data
# -----------------------------
import pandas as pd
import numpy as np
import ccxt
import key_file as k # <-- your file with API keys

# -----------------------------
# Config
# -----------------------------
class Config:
    symbol = "BTC/USDT"       # Binance trading pair
    timeframe = "1m"          # "1m", "5m", "1h", "1d"
    limit = 1500              # candles to fetch (max ~1500 per request with ccxt)
    initial_balance = 10000
    volume = 0.001
    grid_multiplier = 0.1
    num_of_grids = 2
    take_profit_percent = 0.5
    stop_loss_percent = 0.5
    atr_period = 14
    risk_free_rate = 0.0

# -----------------------------
# Indicator: ATR
# -----------------------------
def calculate_atr(df, period=14):
    df["H-L"] = df["high"] - df["low"]
    df["H-C"] = abs(df["high"] - df["close"].shift())
    df["L-C"] = abs(df["low"] - df["close"].shift())
    df["TR"] = df[["H-L", "H-C", "L-C"]].max(axis=1)
    df["ATR"] = df["TR"].rolling(period).mean()
    return df

# -----------------------------
# Metrics Helpers
# -----------------------------
def max_drawdown(equity_curve):
    roll_max = np.maximum.accumulate(equity_curve)
    dd = (equity_curve - roll_max) / roll_max
    return dd.min()

def sharpe_ratio(returns, rf=0.0):
    return 0 if returns.std() == 0 else (returns.mean() - rf) / returns.std() * np.sqrt(252*24*60)

def sortino_ratio(returns, rf=0.0):
    downside = returns[returns < 0]
    return 0 if downside.std() == 0 else (returns.mean() - rf) / downside.std() * np.sqrt(252*24*60)

def calmar_ratio(returns, equity_curve):
    mdd = abs(max_drawdown(equity_curve))
    return 0 if mdd == 0 else returns.mean() / mdd

def ulcer_index(equity_curve):
    roll_max = np.maximum.accumulate(equity_curve)
    drawdown = (equity_curve - roll_max) / roll_max
    return np.sqrt(np.mean(drawdown**2))

# -----------------------------
# Fetch Binance Data
# -----------------------------
import ccxt

def fetch_data(cfg):
    # Use public API (no keys required)
    exchange = ccxt.binance({
        'enableRateLimit': True,
    })

    # Fetch OHLCV from public endpoint
    ohlcv = exchange.fetch_ohlcv(cfg.symbol, timeframe=cfg.timeframe, limit=cfg.limit)

    df = pd.DataFrame(ohlcv, columns=["timestamp","open","high","low","close","volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df


# -----------------------------
# Backtesting Engine
# -----------------------------
def run_backtest():
    cfg = Config()

    # Load OHLCV
    df = fetch_data(cfg)
    df = calculate_atr(df, cfg.atr_period)

    balance = cfg.initial_balance
    equity_curve = []
    trades = []
    position = None

    for i in range(cfg.atr_period, len(df)):
        price = df["close"].iloc[i]
        atr = df["ATR"].iloc[i]
        grid_spacing = atr * cfg.grid_multiplier

        buy_levels = [price - (j+1)*grid_spacing for j in range(cfg.num_of_grids)]
        sell_levels = [price + (j+1)*grid_spacing for j in range(cfg.num_of_grids)]

        if not position:
            if df["low"].iloc[i] <= buy_levels[0]:
                position = {"side":"long","entry":buy_levels[0]}
            elif df["high"].iloc[i] >= sell_levels[0]:
                position = {"side":"short","entry":sell_levels[0]}
        else:
            if position["side"] == "long":
                tp = position["entry"] * (1 + cfg.take_profit_percent/100)
                sl = position["entry"] * (1 - cfg.stop_loss_percent/100)
                if df["high"].iloc[i] >= tp:
                    pnl = (tp - position["entry"]) * (1/cfg.volume)
                    balance += pnl
                    trades.append(pnl)
                    position = None
                elif df["low"].iloc[i] <= sl:
                    pnl = (sl - position["entry"]) * (1/cfg.volume)
                    balance += pnl
                    trades.append(pnl)
                    position = None
            elif position["side"] == "short":
                tp = position["entry"] * (1 - cfg.take_profit_percent/100)
                sl = position["entry"] * (1 + cfg.stop_loss_percent/100)
                if df["low"].iloc[i] <= tp:
                    pnl = (position["entry"] - tp) * (1/cfg.volume)
                    balance += pnl
                    trades.append(pnl)
                    position = None
                elif df["high"].iloc[i] >= sl:
                    pnl = (position["entry"] - sl) * (1/cfg.volume)
                    balance += pnl
                    trades.append(pnl)
                    position = None

        equity_curve.append(balance)

    equity_curve = np.array(equity_curve)
    returns = pd.Series(trades)

    metrics = {
        "Initial Balance": cfg.initial_balance,
        "Final Balance": round(balance, 2),
        "Total Return (%)": round(((balance - cfg.initial_balance)/cfg.initial_balance)*100, 2),
        "Number of Trades": len(trades),
        "Win Rate (%)": round((returns[returns > 0].count()/len(returns))*100,2) if len(returns)>0 else 0,
        "Average Win": round(returns[returns > 0].mean(),2) if len(returns[returns>0])>0 else 0,
        "Average Loss": round(returns[returns < 0].mean(),2) if len(returns[returns<0])>0 else 0,
        "Max Win": round(returns.max(),2) if len(returns)>0 else 0,
        "Max Loss": round(returns.min(),2) if len(returns)>0 else 0,
        "Max Drawdown (%)": round(max_drawdown(equity_curve)*100,2),
        "Ulcer Index": round(ulcer_index(equity_curve),4),
        "Sharpe Ratio": round(sharpe_ratio(returns),2) if len(returns)>1 else 0,
        "Sortino Ratio": round(sortino_ratio(returns),2) if len(returns)>1 else 0,
        "Calmar Ratio": round(calmar_ratio(returns, equity_curve),2) if len(returns)>1 else 0,
        "Profit Factor": round(abs(returns[returns > 0].sum() / returns[returns < 0].sum()),2) if len(returns[returns<0])>0 else np.inf,
        "Expectancy": round(returns.mean(),2) if len(returns)>0 else 0,
        "Std Dev of Returns": round(returns.std(),2) if len(returns)>0 else 0,
        "Skewness": round(returns.skew(),2) if len(returns)>0 else 0,
        "Kurtosis": round(returns.kurtosis(),2) if len(returns)>0 else 0
    }

    print("\n--- Backtest Results on Real Data ---")
    for k,v in metrics.items():
        print(f"{k}: {v}")

# -----------------------------
# Run
# -----------------------------
if __name__ == "__main__":
    run_backtest()
