import time
import logging
from pybit.unified_trading import HTTP

# Configura il logging
logging.basicConfig(filename="active_positions.log", level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

# Parametri di connessione e API
http = HTTP(
    api_key="NGZ4WnPGi7vzmPMd2q",  
    api_secret="lssBuYfP61yind7taU5YpkVMXupUDoDOy4Sj",  
)
def get_last_price(client, symbol):
    """Last/mark price via v5 tickers (usa lastPrice)."""
    try:
        resp = client.get_tickers(category="linear", symbol=symbol)
        return float(resp["result"]["list"][0]["lastPrice"])
    except Exception as e:
        print(f"Errore nel recupero prezzo per {symbol}: {e}")
        return None

def get_tick_size(client, symbol):
    """Tick/pip size dal contratto (useremo il tick come 'pip')."""
    try:
        info = client.get_instruments_info(category="linear", symbol=symbol)
        return float(info["result"]["list"][0]["priceFilter"]["tickSize"])
    except Exception as e:
        print(f"Errore nel recupero tickSize per {symbol}: {e}")
        return 0.01  # fallback sensato per molte alt



def get_ticker_price(client, symbol):
    try:
        # Usa il metodo get_ticker per ottenere informazioni sul simbolo
        ticker = client.get_ticker(category="linear", symbol=symbol)["result"]["list"][0]
        last_price = float(ticker["lastPrice"])  # Estrae il prezzo corrente
        return last_price
    except Exception as e:
        print(f"Errore nel recupero del prezzo per {symbol}: {e}")
        return None

def get_active_positions(client):
    try:
        positions = client.get_positions(category="linear", settleCoin="USDT")["result"]["list"]
        if not positions:
            print("Nessuna posizione attiva.")
            return

        print("\nPosizioni attive:")
        for pos in positions:
            symbol = pos["symbol"]
            side = pos.get("side", "N/A")
            size = float(pos.get("size") or 0.0)
            if size <= 0:
                continue  # salta slot vuoti

            # entry: usa avgPrice (fallback a entryPrice)
            entry_raw = (pos.get("avgPrice") or pos.get("entryPrice") or "")
            entry = float(entry_raw) if entry_raw not in ("", "0", None) else None

            sl = pos.get("stopLoss") or "N/A"
            tp = pos.get("takeProfit") or "N/A"
            lev_raw = pos.get("leverage", "N/A")
            liq = pos.get("liqPrice") or "N/A"
            upnl_api = pos.get("unrealisedPnl", "N/A")

            last = get_last_price(client, symbol)   # via get_tickers(...)
            tick = get_tick_size(client, symbol)    # via get_instruments_info(...)

            status = "Sconosciuta"
            pip_diff = "N/A"
            pnl_usdt = "N/A"
            pnl_pct_str = "N/A"   # % sul margine (≈ USDT investiti)

            if entry is not None and last is not None and tick and tick > 0:
                # pip = numero di tick
                pip_diff_val = (last - entry) / tick
                pip_diff = f"{abs(pip_diff_val):.1f} pip"

                # PnL (linear USDT): Δprezzo * size
                if side == "Buy":
                    pnl_val = (last - entry) * size
                    status = "Positiva" if last > entry else "Negativa"
                else:
                    pnl_val = (entry - last) * size
                    status = "Positiva" if last < entry else "Negativa"
                pnl_usdt = f"{pnl_val:.2f} USDT"

                # ===== % rispetto agli USDT investiti (margine) =====
                # prova a leggere il margine dalla posizione (se disponibile),
                # altrimenti approx: (entry*size)/leverage
                margin_used = None
                pos_im = pos.get("positionIM") or pos.get("positionMargin")
                try:
                    if pos_im not in (None, "", "0"):
                        margin_used = float(pos_im)
                except:
                    margin_used = None

                # fallback: calcolo da notional/leverage
                if margin_used is None:
                    try:
                        lev_f = float(lev_raw)
                    except:
                        lev_f = None
                    notional = entry * size
                    if lev_f and lev_f > 0:
                        margin_used = notional / lev_f
                    else:
                        # ultimo fallback: usa il notional (meno accurato ma coerente)
                        margin_used = notional

                if margin_used and margin_used > 0:
                    pnl_pct = (pnl_val / margin_used) * 100.0
                    pnl_pct_str = f"{pnl_pct:.2f}%"
                # =====================================================

            print(
                f"\n==========================="
                f"\nSimbolo: {symbol}"
                f"\nDirezione: {side}"
                f"\nQuantità: {size}"
                f"\nPrezzo di ingresso (avgPrice): {entry_raw if entry is not None else 'N/A'}"
                f"\nPrezzo corrente: {last if last is not None else 'N/A'}"
                f"\nDelta (pip): {pip_diff}"
                f"\nLeva: {lev_raw}"
                f"\nStop Loss: {sl if sl not in ('0','0.0','') else 'N/A'}"
                f"\nTake Profit: {tp if tp not in ('0','0.0','') else 'N/A'}"
                f"\nPrezzo di liquidazione: {liq}"
                f"\nPnL non realizzato (API): {upnl_api}"
                f"\nStato (calcolato): {status}"
                f"\nPnL calcolato: {pnl_usdt} ({pnl_pct_str} su margine)"
                f"\n==========================="
            )

    except Exception as e:
        print(f"Errore nel recupero delle posizioni attive: {e}")


# Funzione principale che esegue la lettura ogni minuto
def monitor_active_positions():
    while True:
        print("==== Controllo posizioni attive ====")
        logging.info("==== Controllo posizioni attive ====")
        get_active_positions(http)  # Ottieni e mostra le posizioni attive
        time.sleep(60)  # Attendi 60 secondi (1 minuto) prima di ripetere il controllo

# Avvia il monitoraggio delle posizioni attive
monitor_active_positions()
