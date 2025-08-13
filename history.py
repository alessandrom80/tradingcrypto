# backtest_btc_avax.py
# ---------------------
# Backtests the strategy: when BTC 15m close change |Δ| >= ALERT, open AVAXUSDT perp in same direction.
# Exit via SL/TP computed like in your live bot. One position at a time.
#
# Requirements:
#   pip install pandas numpy ccxt matplotlib
#
# Usage example:
#   python backtest_btc_avax.py --start "2024-01-01" --end "2025-08-01" --timeframe 15m --alert 0.39 --leverage 20 \
#       --order_percent 0.25 --sl_percent 0.65 --tp_percent 0.115 --initial_balance 1000 --taker_fee 0.00055
#
# Notes:
# - Fetches Bybit USDT-perp futures via ccxt: BTC/USDT:USDT and AVAX/USDT:USDT
# - Entries are at the *next candle open* after the BTC signal (more realistic than same-candle close).
# - If both TP and SL are hit in the same candle, we assume worst-case (SL first) for conservatism.
# - Position size matches your formula: order_value = balance * ORDER_PERCENT * LEVERAGE; qty = order_value / entry_price.
# - SL/TP replicate your approach: delta_price = entry_price * (PERCENT / LEVERAGE).
# - Fees: taker fee applied on entry and exit (you can adjust).

import argparse
from datetime import datetime, timezone
import time
import pandas as pd
import numpy as np
import ccxt
import math
import sys
import matplotlib.pyplot as plt

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--start', type=str, required=True, help='Start date (YYYY-MM-DD) UTC')
    p.add_argument('--end', type=str, required=True, help='End date (YYYY-MM-DD) UTC')
    p.add_argument('--timeframe', type=str, default='15m')
    p.add_argument('--alert', type=float, default=0.39)
    p.add_argument('--leverage', type=int, default=20)
    p.add_argument('--order_percent', type=float, default=0.25)
    p.add_argument('--sl_percent', type=float, default=0.65)
    p.add_argument('--tp_percent', type=float, default=0.115)
    p.add_argument('--initial_balance', type=float, default=10000.0)
    p.add_argument('--taker_fee', type=float, default=0.00055)
    p.add_argument('--plot', action='store_true')
    return p.parse_args()

def ms(ts: str) -> int:
    # Convert YYYY-MM-DD to ms epoch (UTC)
    dt = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
    return int(dt.timestamp()*1000)

def fetch_ohlcv_by_range(exchange, symbol, timeframe, since_ms, end_ms, limit=1000, sleep_sec=0.5):
    all_rows = []
    last = since_ms
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=last, limit=limit)
        if not batch:
            break
        # ccxt returns [ms, open, high, low, close, vol]
        all_rows.extend(batch)
        last_new = batch[-1][0]
        # Stop if we've reached or passed our end
        if last_new >= end_ms:
            break
        # Otherwise advance. Add 1ms to avoid overlap.
        last = last_new + 1
        time.sleep(sleep_sec)
    if not all_rows:
        return pd.DataFrame(columns=['timestamp','open','high','low','close','volume'])
    df = pd.DataFrame(all_rows, columns=['timestamp','open','high','low','close','volume'])
    # Ensure within range
    df = df[(df['timestamp'] >= since_ms) & (df['timestamp'] <= end_ms)].copy()
    return df

def prepare_data(start, end, timeframe):
    ex = ccxt.bybit({'enableRateLimit': True})
    sym_btc = 'BTC/USDT:USDT'
    sym_avax = 'AVAX/USDT:USDT'
    since_ms = ms(start)
    end_ms = ms(end)
    print(f'Fetching {sym_btc} {timeframe} from {start} to {end} ...', flush=True)
    btc = fetch_ohlcv_by_range(ex, sym_btc, timeframe, since_ms, end_ms)
    print(f'BTC candles: {len(btc)}')
    print(f'Fetching {sym_avax} {timeframe} from {start} to {end} ...', flush=True)
    avax = fetch_ohlcv_by_range(ex, sym_avax, timeframe, since_ms, end_ms)
    print(f'AVAX candles: {len(avax)}')
    # align to timestamps
    btc.set_index('timestamp', inplace=True)
    avax.set_index('timestamp', inplace=True)
    # forward fill missing candles to align? we will inner join to be strict
    btc.columns = [f'btc_{c}' for c in btc.columns]
    avax.columns = [f'avax_{c}' for c in avax.columns]
    df = btc.join(avax, how='inner')
    df.reset_index(inplace=True)
    return df

def simulate(df, alert, leverage, order_percent, sl_percent, tp_percent, initial_balance, taker_fee):
    # Compute BTC candle return (close/prev close - 1) * 100
    # We need the *closed* candle % change on BTC to trigger. Use close vs open of *the same* candle.
    df['btc_delta_pct'] = (df['btc_close'] - df['btc_open']) / df['btc_open'] * 100.0
    # Signal at close of candle: we'll enter AVAX at next candle open
    mask = df['btc_delta_pct'].abs() >= alert
    df['signal'] = np.sign(df['btc_delta_pct']).where(mask, 0).astype(int)
    # Shift signal by 1 to enter on next candle open (avoid look-ahead)
    df['entry_signal'] = df['signal'].shift(1).fillna(0)

    equity = initial_balance
    balance = initial_balance
    positions = []  # list of dicts with trade details
    in_position = False
    last_entry_ts = None

    for i in range(1, len(df)):
        row = df.iloc[i]
        ts = int(row['index']) if 'index' in row else int(row['timestamp'])
        # If not in position and there's a signal, open
        if (not in_position) and (row['entry_signal'] != 0):
            direction = int(row['entry_signal'])  # 1 long, -1 short
            entry_price = row['avax_open']  # next candle open
            # position sizing
            order_value = max(balance * order_percent * leverage, 5.0)
            qty = order_value / entry_price
            # SL/TP mirroring your code
            delta_sl = entry_price * (sl_percent / leverage)
            delta_tp = entry_price * (tp_percent / leverage)
            if direction > 0:
                sl_price = entry_price - delta_sl
                tp_price = entry_price + delta_tp
            else:
                sl_price = entry_price + delta_sl
                tp_price = entry_price - delta_tp

            # Apply entry fee
            fee_entry = order_value * taker_fee
            balance -= fee_entry

            positions.append({
                'entry_ts': df.iloc[i]['timestamp'],
                'direction': direction,
                'entry_price': entry_price,
                'qty': qty,
                'order_value': order_value,
                'sl_price': sl_price,
                'tp_price': tp_price,
                'fee_entry': fee_entry,
                'exit_ts': None,
                'exit_price': None,
                'pnl': None,
                'fee_exit': None,
                'result': None
            })
            in_position = True
            last_entry_ts = ts
            continue

        # If in position, check SL/TP sequentially from candle i (high/low includes open-close range)
        if in_position:
            pos = positions[-1]
            high = row['avax_high']
            low = row['avax_low']

            hit_tp = hit_sl = False
            if pos['direction'] > 0:
                hit_tp = high >= pos['tp_price']
                hit_sl = low <= pos['sl_price']
            else:
                hit_tp = low <= pos['tp_price']
                hit_sl = high >= pos['sl_price']

            # If both hit in same candle, assume SL (conservative)
            exit_price = None
            result = None
            if hit_tp and hit_sl:
                exit_price = pos['sl_price']
                result = 'SL-both-hit'
            elif hit_tp:
                exit_price = pos['tp_price']
                result = 'TP'
            elif hit_sl:
                exit_price = pos['sl_price']
                result = 'SL'

            if exit_price is not None:
                # Apply exit fee on notional of exit
                fee_exit = pos['order_value'] * taker_fee
                # Realized PnL (without leverage double-count): qty * (exit - entry) * sign
                pnl_gross = pos['qty'] * (exit_price - pos['entry_price']) * pos['direction']
                pnl = pnl_gross - pos['fee_entry'] - fee_exit

                balance += pnl
                pos.update({
                    'exit_ts': df.iloc[i]['timestamp'],
                    'exit_price': exit_price,
                    'pnl': pnl,
                    'fee_exit': fee_exit,
                    'result': result
                })
                in_position = False

    # Close any open position at last close (mark-to-market)
    if in_position:
        row = df.iloc[-1]
        pos = positions[-1]
        exit_price = row['avax_close']
        fee_exit = pos['order_value'] * taker_fee
        pnl_gross = pos['qty'] * (exit_price - pos['entry_price']) * pos['direction']
        pnl = pnl_gross - pos['fee_entry'] - fee_exit
        balance += pnl
        pos.update({
            'exit_ts': row['timestamp'],
            'exit_price': exit_price,
            'pnl': pnl,
            'fee_exit': fee_exit,
            'result': 'EOD'
        })
        in_position = False

    trades = pd.DataFrame(positions)
    if len(trades) == 0:
        return df, trades, {
            'initial_balance': initial_balance,
            'final_balance': balance,
            'n_trades': 0,
            'winrate': None,
            'avg_pnl': None,
            'max_drawdown': None,
            'sharpe': None
        }

    # Build equity curve
    equity_curve = [initial_balance]
    cur = initial_balance
    for _, t in trades.iterrows():
        cur += t['pnl']
        equity_curve.append(cur)
    equity_curve = pd.Series(equity_curve)

    # Metrics
    wins = trades['pnl'] > 0
    winrate = wins.mean()
    avg_pnl = trades['pnl'].mean()
    # Max drawdown
    cummax = equity_curve.cummax()
    dd = equity_curve / cummax - 1.0
    max_dd = dd.min()
    # Sharpe (simple, dailyization approximated): use trade-to-trade returns vs equity
    rets = trades['pnl'] / equity_curve[:-1].values
    if rets.std(ddof=1) > 0:
        sharpe = np.sqrt(52) * rets.mean() / rets.std(ddof=1)  # ~weekly cadence if many signals; rough
    else:
        sharpe = np.nan

    stats = {
        'initial_balance': initial_balance,
        'final_balance': float(balance),
        'n_trades': int(len(trades)),
        'winrate': float(winrate) if winrate==winrate else None,
        'avg_pnl': float(avg_pnl) if avg_pnl==avg_pnl else None,
        'max_drawdown': float(max_dd) if max_dd==max_dd else None,
        'sharpe': float(sharpe) if sharpe==sharpe else None
    }

    # Attach for convenience
    trades['entry_time'] = pd.to_datetime(trades['entry_ts'], unit='ms', utc=True)
    trades['exit_time']  = pd.to_datetime(trades['exit_ts'], unit='ms', utc=True)
    trades = trades[['entry_time','exit_time','direction','entry_price','exit_price','sl_price','tp_price','qty','pnl','result','fee_entry','fee_exit']]
    return df, trades, stats, equity_curve

def main():
    args = parse_args()
    df = prepare_data(args.start, args.end, args.timeframe)
    if df.empty:
        print("No data fetched. Check date range / network.", file=sys.stderr)
        sys.exit(1)

    df, trades, stats, equity_curve = simulate(
        df=df,
        alert=args.alert,
        leverage=args.leverage,
        order_percent=args.order_percent,
        sl_percent=args.sl_percent,
        tp_percent=args.tp_percent,
        initial_balance=args.initial_balance,
        taker_fee=args.taker_fee
    )

    # Save outputs
    trades.to_csv('trades.csv', index=False)
    pd.DataFrame([stats]).to_csv('stats.csv', index=False)
    pd.DataFrame({'equity': equity_curve}).to_csv('equity_curve.csv', index=False)
    print("=== STATS ===")
    for k,v in stats.items():
        print(f"{k}: {v}")
    print("\nSaved: trades.csv, stats.csv, equity_curve.csv")

    if args.plot:
        plt.figure()
        plt.plot(equity_curve.values)
        plt.title('Equity Curve')
        plt.xlabel('Trade #')
        plt.ylabel('Balance (USDT)')
        plt.tight_layout()
        plt.show()

if __name__ == '__main__':
    main()
