from pybit.unified_trading import HTTP
import pandas as pd
from datetime import datetime, timedelta, timezone

# === API KEYS (valuta di ruotarle se sono state esposte) ===
API_KEY = "NGZ4WnPGi7vzmPMd2q"
API_SECRET = "lssBuYfP61yind7taU5YpkVMXupUDoDOy4Sj"

# Parametri
SYMBOL = "AVAXUSDT"
DAYS_BACK = 365
PIP_MULTIPLIER = 10_000  # 1 pip = 0.0001

http = HTTP(
    testnet=False,
    api_key=API_KEY,
    api_secret=API_SECRET
)

def get_closed_pnl_all(symbol="AVAXUSDT", limit=200):
    results = []
    cursor = None
    while True:
        params = {"category": "linear", "symbol": symbol, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        resp = http.get_closed_pnl(**params)

        if resp.get("retMsg") != "OK":
            print("Errore API:", resp.get("retMsg"))
            break

        result = resp.get("result", {}) or {}
        rows = result.get("list", []) or []
        results.extend(rows)

        cursor = result.get("nextPageCursor")
        if not cursor:
            break
    return results

if __name__ == "__main__":
    trades = get_closed_pnl_all(SYMBOL)

    if not trades:
        print("Nessun trade trovato.")
        raise SystemExit

    df = pd.DataFrame(trades)

    # updatedTime -> numeric -> datetime UTC
    df["updatedTime"] = pd.to_numeric(df["updatedTime"], errors="coerce")
    df["updated_dt"] = pd.to_datetime(df["updatedTime"], unit="ms", utc=True)

    # Finestra ultimo anno (aware vs aware)
    one_year_ago = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
    df = df[df["updated_dt"] >= one_year_ago]
    if df.empty:
        print("Nessun trade nell’ultimo anno.")
        raise SystemExit

    # Conversioni numeriche sicure
    df["entry_price"] = pd.to_numeric(df["avgEntryPrice"], errors="coerce")
    df["exit_price"]  = pd.to_numeric(df["avgExitPrice"],  errors="coerce")
    df["qty"]         = pd.to_numeric(df["closedSize"],    errors="coerce")
    df["pnl"]         = pd.to_numeric(df["closedPnl"],     errors="coerce")

    # Direzione: Buy = +1 (long), Sell = -1 (short)
    df["direction"] = df["side"].map({"Buy": 1, "Sell": -1}).fillna(0).astype(int)

    # Pips con segno: (exit - entry) * direction * 10_000
    df["pips"] = (df["exit_price"] - df["entry_price"]) * df["direction"] * PIP_MULTIPLIER
    df["pips_abs"] = df["pips"].abs()

    # Ordinamento e output finale
    df = df.sort_values("updated_dt")
    out = df.assign(
        time=df["updated_dt"].dt.tz_convert("UTC").dt.tz_localize(None).dt.strftime("%Y-%m-%d %H:%M:%S")
    )[["time", "side", "entry_price", "exit_price", "qty", "pnl", "pips", "pips_abs"]]

    # Salva CSV
    out.to_csv("avax_closed_trades_pips_1year.csv", index=False)
    print(f"\nStorico 1 anno salvato in avax_closed_trades_pips_1year.csv ({len(out)} record)\n")

    # Stampa tutte le righe e i totali
    pd.set_option("display.max_rows", None)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", None)
    print(out)

    print("\n=== Totali ultimo anno ===")
    print("Totale PnL (USDT):", out["pnl"].sum())
    print("Totale Pips:", out["pips"].sum())
