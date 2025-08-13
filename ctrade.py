"""
Bybit Copy-Trader (Unified Trading / Linear Perp)
-------------------------------------------------
- Ascolta gli eventi PRIVATI (ordine/esecuzione/stop) dell'account MASTER
  e li replica sull'account FOLLOWER.
- Replica ordini **Market/Limit** e ordini condizionati (trigger/Stop*), 
  oltre a cancellazioni e modifiche TP/SL base.
- Gestisce arrotondamenti su step quantità/prezzo e mappa orderId master→follower.

⚠️ Note importanti
- Imposta le API KEY del MASTER e del FOLLOWER via variabili d'ambiente
  oppure inseriscile nel blocco CONFIG (sconsigliato). Non condividere mai le chiavi!
- Per semplicità si assume modalità **one-way** e categoria **linear (USDT Perp)**.
- Testato con pybit.unified_trading.

Dipendenze: pip install pybit==5.* pytz
"""

import json
import os
import time
import logging
from pathlib import Path
from datetime import datetime
import pytz

from pybit.unified_trading import HTTP, WebSocket

# ============================
# CONFIG
# ============================
TESTNET = False  # True per testnet
CATEGORY = "linear"  # solo perpetual USDT

# Modalità dimensionamento size sul FOLLOWER
# - "multiplier": qty_follower = qty_master * QTY_MULTIPLIER
# - "wallet_ratio": scala in base al rapporto di USDT disponibili (follower/master)
SIZE_MODE = "multiplier"  # oppure "wallet_ratio"
QTY_MULTIPLIER = 1.0

# Leva da impostare (se None non forza la leva)
LEVERAGE = 10

# Whitelist simboli da copiare (None per tutti i simboli linear, es. ["BTCUSDT", "ETHUSDT"])
SYMBOL_WHITELIST = None

# File persistenza mapping orderId master→follower
MAP_FILE = Path("copy_map.json")

# API KEY/SECRET dal sistema (preferibile) — altrimenti inserisci stringhe direttamente (sconsigliato)
MASTER_API_KEY = os.getenv("BYBIT_MASTER_API_KEY", "")
MASTER_API_SECRET = os.getenv("BYBIT_MASTER_API_SECRET", "")
FOLLOW_API_KEY = os.getenv("BYBIT_FOLLOW_API_KEY", "")
FOLLOW_API_SECRET = os.getenv("BYBIT_FOLLOW_API_SECRET", "")

# ============================
# LOGGING
# ============================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler("copy_trader.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("copy_trader")

# ============================
# UTILS
# ============================

def ts_rome(ts_ms: int) -> str:
    dt_utc = datetime.fromtimestamp(ts_ms/1000, tz=pytz.UTC)
    dt_rome = dt_utc.astimezone(pytz.timezone("Europe/Rome"))
    return dt_rome.strftime("%Y-%m-%d %H:%M:%S %Z")


def load_map():
    if MAP_FILE.exists():
        try:
            return json.loads(MAP_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_map(m: dict):
    try:
        MAP_FILE.write_text(json.dumps(m))
    except Exception as e:
        log.warning(f"Impossibile salvare map file: {e}")


ID_MAP = load_map()  # { masterOrderId: followerOrderId }


def _round_to_step(value: float, step: float) -> float:
    try:
        step = float(step)
        if step <= 0:
            return value
        # floor allo step
        return round((int(value / step)) * step, 8)
    except Exception:
        return value


def get_filters(http: HTTP, symbol: str):
    try:
        info = http.get_instruments_info(category=CATEGORY, symbol=symbol)["result"]["list"][0]
        qty_step = float(info["lotSizeFilter"]["qtyStep"])  # step quantità
        px_step = float(info["priceFilter"]["tickSize"])   # tick prezzo
        min_qty = float(info["lotSizeFilter"]["minOrderQty"])  # qty minima
        return qty_step, px_step, min_qty
    except Exception as e:
        log.error(f"get_filters fallita per {symbol}: {e}")
        return 0.001, 0.01, 0.001


def get_wallet_available_usdt(http: HTTP) -> float:
    try:
        wallet = http.get_wallet_balance(accountType="UNIFIED")["result"]["list"][0]["coin"]
        usdt = next((c for c in wallet if c["coin"] == "USDT"), None)
        if not usdt:
            return 0.0
        avail = float(usdt.get("availableToTrade") or usdt.get("walletBalance") or 0.0)
        return avail
    except Exception as e:
        log.error(f"Errore get_wallet_available_usdt: {e}")
        return 0.0


def ensure_leverage(http: HTTP, symbol: str, leverage: int | None) -> None:
    if not leverage:
        return
    try:
        resp = http.set_leverage(category=CATEGORY, symbol=symbol,
                                 buyLeverage=str(leverage), sellLeverage=str(leverage))
        rc = resp.get("retCode")
        if rc in (0, 110043):  # 110043 = leverage not modified
            return
        log.warning(f"set_leverage non applicata per {symbol}: {resp}")
    except Exception as e:
        # non bloccante
        log.warning(f"set_leverage errore {symbol}: {e}")


# ============================
# CORE COPY LOGIC
# ============================

def should_copy_symbol(symbol: str) -> bool:
    if CATEGORY != "linear":
        return True
    if SYMBOL_WHITELIST is None:
        return symbol.endswith("USDT")  # semplice filtro per perp USDT
    return symbol in SYMBOL_WHITELIST


def scale_quantity(qty_master: float, http_master: HTTP, http_follower: HTTP, symbol: str) -> float:
    if SIZE_MODE == "multiplier":
        return qty_master * float(QTY_MULTIPLIER)
    # wallet_ratio
    try:
        m = get_wallet_available_usdt(http_master)
        f = get_wallet_available_usdt(http_follower)
        if m <= 0:
            return qty_master  # fallback 1:1
        factor = max(0.0, f / m)
        return qty_master * factor
    except Exception:
        return qty_master


def mirror_place_order(master_http: HTTP, follower_http: HTTP, order: dict):
    """Replica la creazione di un ordine dal MASTER al FOLLOWER.
    Supporta Market/Limit e ordini con trigger (stop/conditional)."""
    try:
        symbol = order.get("symbol")
        if not symbol or not should_copy_symbol(symbol):
            return

        side = order.get("side")  # "Buy"/"Sell"
        order_type = order.get("orderType")  # "Market"/"Limit"
        qty_master = float(order.get("qty") or order.get("orderQty") or 0)
        price = order.get("price")
        tif = order.get("timeInForce") or "GoodTillCancel"
        reduce_only = order.get("reduceOnly") or False
        take_profit = order.get("takeProfit")
        stop_loss = order.get("stopLoss")

        # Trigger / Conditional
        trigger_price = order.get("triggerPrice")
        trigger_direction = order.get("triggerDirection")  # 1 up, 2 down (Bybit)

        if qty_master <= 0:
            return

        qty_step, px_step, min_qty = get_filters(follower_http, symbol)

        # dimensionamento
        qty_follow = max(scale_quantity(qty_master, master_http, follower_http, symbol), min_qty)
        qty_follow = _round_to_step(qty_follow, qty_step)

        # normalizza prezzo se Limit
        if order_type == "Limit" and price is not None:
            try:
                price = float(price)
                price = _round_to_step(price, px_step)
            except Exception:
                pass

        ensure_leverage(follower_http, symbol, LEVERAGE)

        link_id = f"COPY_{order.get('orderId') or order.get('orderLinkId') or int(time.time()*1000)}"

        params = dict(
            category=CATEGORY,
            symbol=symbol,
            side=side,
            orderType=order_type,
            qty=str(qty_follow),
            timeInForce=tif,
            reduceOnly=bool(reduce_only),
            orderLinkId=link_id,
        )

        if order_type == "Limit" and price is not None:
            params["price"] = str(price)

        # TP/SL al livello ordine (Bybit applica a posizione in one-way)
        if take_profit:
            params["takeProfit"] = str(take_profit)
        if stop_loss:
            params["stopLoss"] = str(stop_loss)

        # Conditional/Stop
        if trigger_price:
            params["triggerPrice"] = str(trigger_price)
            if trigger_direction:
                params["triggerDirection"] = trigger_direction

        log.info(f"→ FOLLOW place_order {params}")
        resp = follower_http.place_order(**params)
        rc = resp.get("retCode")
        if rc != 0:
            log.warning(f"place_order follower KO: {resp}")
            return
        follower_oid = resp["result"].get("orderId")
        master_oid = str(order.get("orderId") or order.get("orderLinkId"))
        if master_oid and follower_oid:
            ID_MAP[master_oid] = follower_oid
            save_map(ID_MAP)
    except Exception as e:
        log.error(f"mirror_place_order errore: {e}")


def mirror_cancel_order(follower_http: HTTP, order: dict):
    """Replica la cancellazione dell'ordine."""
    try:
        symbol = order.get("symbol")
        master_oid = str(order.get("orderId") or order.get("orderLinkId"))
        follower_oid = ID_MAP.get(master_oid)

        params = dict(category=CATEGORY, symbol=symbol)
        if follower_oid:
            params["orderId"] = follower_oid
        else:
            # fallback su link id se presente
            link_id = f"COPY_{master_oid}"
            params["orderLinkId"] = link_id

        log.info(f"→ FOLLOW cancel_order {params}")
        resp = follower_http.cancel_order(**params)
        if resp.get("retCode") == 0 and follower_oid:
            # pulisci mapping
            try:
                del ID_MAP[master_oid]
                save_map(ID_MAP)
            except KeyError:
                pass
    except Exception as e:
        log.error(f"mirror_cancel_order errore: {e}")


def mirror_market_from_execution(master_http: HTTP, follower_http: HTTP, exec_msg: dict):
    """Se vediamo un'esecuzione MARKET sul master (p.es. ordine piazzato e riempito al volo),
    apriamo un MARKET equivalente sul follower per "agganciare" la posizione."""
    try:
        symbol = exec_msg.get("symbol")
        if not symbol or not should_copy_symbol(symbol):
            return
        side = exec_msg.get("side")  # Buy/Sell
        exec_qty = float(exec_msg.get("execQty") or 0)
        if exec_qty <= 0:
            return
        qty_step, _, min_qty = get_filters(follower_http, symbol)
        qty_follow = max(scale_quantity(exec_qty, master_http, follower_http, symbol), min_qty)
        qty_follow = _round_to_step(qty_follow, qty_step)

        params = dict(
            category=CATEGORY,
            symbol=symbol,
            side=side,
            orderType="Market",
            qty=str(qty_follow),
            timeInForce="ImmediateOrCancel",
            orderLinkId=f"COPY_EXEC_{exec_msg.get('orderId') or int(time.time()*1000)}",
        )
        log.info(f"→ FOLLOW market(place) from exec {params}")
        follower_http.place_order(**params)
    except Exception as e:
        log.error(f"mirror_market_from_execution errore: {e}")


# ============================
# WEBSOCKET HANDLERS (MASTER)
# ============================

def on_order(message: dict, master_http: HTTP, follower_http: HTTP):
    """Gestisce stream PRIVATO "order" del MASTER.
    Gli eventi tipici includono ordini nuovi, aggiornati, cancellati."""
    try:
        if message.get("type") not in ("snapshot", "delta"):
            return
        data = message.get("data") or []
        for ord_msg in data:
            status = ord_msg.get("orderStatus") or ord_msg.get("status")
            symbol = ord_msg.get("symbol")
            oid = ord_msg.get("orderId")
            log.info(f"MASTER order event {symbol} {status} oid={oid}")

            if status in ("Created", "New", "Untriggered", "PartiallyFilled"):
                mirror_place_order(master_http, follower_http, ord_msg)
            elif status in ("Cancelled", "Rejected"):
                mirror_cancel_order(follower_http, ord_msg)
            # Modifiche TP/SL basiche
            elif status == "Amended":
                # strategia semplice: cancella e reinvia (facile, non ottimale)
                mirror_cancel_order(follower_http, ord_msg)
                mirror_place_order(master_http, follower_http, ord_msg)
    except Exception as e:
        log.error(f"on_order errore: {e}")


def on_stop_order(message: dict, master_http: HTTP, follower_http: HTTP):
    """Gestione stop/conditional (alcune versioni della API inviano separato)."""
    try:
        if message.get("type") not in ("snapshot", "delta"):
            return
        for ord_msg in (message.get("data") or []):
            status = ord_msg.get("orderStatus") or ord_msg.get("status")
            if status in ("Created", "New", "Untriggered"):
                mirror_place_order(master_http, follower_http, ord_msg)
            elif status in ("Cancelled", "Rejected"):
                mirror_cancel_order(follower_http, ord_msg)
    except Exception as e:
        log.error(f"on_stop_order errore: {e}")


def on_execution(message: dict, master_http: HTTP, follower_http: HTTP):
    """Gestione stream "execution" del MASTER: utile per MARKET riempiti al volo."""
    try:
        if message.get("type") not in ("snapshot", "delta"):
            return
        for ex in (message.get("data") or []):
            exec_type = ex.get("execType")  # Trade, Funding, BustTrade, etc.
            if exec_type != "Trade":
                continue
            # se l'ordine era market, potremmo non aver visto un evento "order Created"
            ord_type = ex.get("orderType")
            if ord_type == "Market":
                mirror_market_from_execution(master_http, follower_http, ex)
    except Exception as e:
        log.error(f"on_execution errore: {e}")


# ============================
# MAIN
# ============================

def main():
    if not MASTER_API_KEY or not MASTER_API_SECRET or not FOLLOW_API_KEY or not FOLLOW_API_SECRET:
        raise SystemExit("⚠️ Configura BYBIT_MASTER_API_KEY/_SECRET e BYBIT_FOLLOW_API_KEY/_SECRET nelle variabili d'ambiente prima di avviare.")

    http_master = HTTP(api_key=MASTER_API_KEY, api_secret=MASTER_API_SECRET, testnet=TESTNET)
    http_follow = HTTP(api_key=FOLLOW_API_KEY, api_secret=FOLLOW_API_SECRET, testnet=TESTNET)

    # Stampa info di contesto
    try:
        mb = get_wallet_available_usdt(http_master)
        fb = get_wallet_available_usdt(http_follow)
        log.info(f"MASTER USDT avail: {mb} | FOLLOWER USDT avail: {fb}")
    except Exception:
        pass

    # WebSocket PRIVATI MASTER
    ws_master = WebSocket(
        testnet=TESTNET,
        channel_type="private",
        api_key=MASTER_API_KEY,
        api_secret=MASTER_API_SECRET,
        ping_interval=20,
        trace_logging=False,
    )

    # Sottoscrizioni: order / stop_order / execution
    ws_master.order_stream(lambda msg: on_order(msg, http_master, http_follow))
    # Alcuni ambienti separano gli stop/conditional
    try:
        ws_master.stop_order_stream(lambda msg: on_stop_order(msg, http_master, http_follow))
    except Exception:
        log.info("stop_order_stream non disponibile in questa build di pybit, si gestisce via order_stream.")

    ws_master.execution_stream(lambda msg: on_execution(msg, http_master, http_follow))

    log.info("Copy-Trader avviato. In ascolto degli eventi del MASTER…")
    # loop vivo
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Arresto richiesto dall'utente.")


if __name__ == "__main__":
    main()
