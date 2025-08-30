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
from dotenv import load_dotenv
load_dotenv()  # carica automaticamente le variabili dal file .env


from pybit.unified_trading import HTTP, WebSocket

# ============================
# CONFIG
# ============================
TESTNET = False  # True per testnet
CATEGORY = "linear"  # solo perpetual USDT

# Modalità dimensionamento size sul FOLLOWER
# - "multiplier": qty_follower = qty_master * QTY_MULTIPLIER
# - "wallet_ratio": scala in base al rapporto di USDT disponibili (follower/master)
SIZE_MODE = "wallet_ratio"  # oppure "wallet_ratio"
QTY_MULTIPLIER = 1.0

# Leva da impostare (se None non forza la leva)
LEVERAGE = 20

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
log.setLevel(logging.DEBUG)

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

import uuid

def generate_link_id(prefix="COPY"):
    return f"{prefix}_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"


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
        log.info(f"set_leverage {symbol}→{leverage} resp={resp}")
        # rc 0 = ok, 110043 = not modified (già impostata)
    except Exception as e:
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
    try:
        if SIZE_MODE == "multiplier":
            qty_follow = qty_master * float(QTY_MULTIPLIER)

        elif SIZE_MODE == "wallet_ratio":
            m = get_wallet_available_usdt(http_master)
            f = get_wallet_available_usdt(http_follower)
            if m <= 0 or f <= 0:
                return qty_master

            ticker_f = http_follower.get_tickers(category=CATEGORY, symbol=symbol)["result"]["list"][0]
            price_f = float(ticker_f["lastPrice"])

            ticker_m = http_master.get_tickers(category=CATEGORY, symbol=symbol)["result"]["list"][0]
            price_m = float(ticker_m["lastPrice"])

            notional_master = qty_master * price_m
            percent = notional_master / m
            notional_follow = f * percent
            qty_follow = notional_follow / price_f

        else:
            qty_follow = qty_master

        # 🔑 controlla notional minimo di 5 USDT
        price_chk = float(http_follower.get_tickers(category=CATEGORY, symbol=symbol)["result"]["list"][0]["lastPrice"])
        notional = qty_follow * price_chk
        if notional < 5:
            log.warning(f"Ordine troppo piccolo per {symbol}: qty={qty_follow}, price={price_chk}, notional={notional} (<5USDT) → SKIP")
            return 0  # forza skip

        return qty_follow

    except Exception as e:
        log.error(f"scale_quantity errore: {e}")
        return qty_master




def mirror_amend_order(follower_http: HTTP, ord_msg: dict):
    """
    Replica un amend di TP/SL/trigger su un ordine aperto (non ancora filled) dal MASTER al FOLLOWER.
    Usa la mappa masterOrderId -> followerOrderId (ID_MAP).
    """
    try:
        symbol = ord_msg.get("symbol")
        if not symbol or not should_copy_symbol(symbol):
            return

        master_oid = str(ord_msg.get("orderId") or ord_msg.get("orderLinkId"))
        follower_oid = ID_MAP.get(master_oid)

        # Se non abbiamo il mapping, proviamo con orderLinkId derivato o saltiamo
        params = dict(category=CATEGORY, symbol=symbol)
        if follower_oid:
            params["orderId"] = follower_oid
        else:
            # ultimo tentativo: proviamo ad usare un linkId coerente con la nostra convenzione
            # (se non lo usi, puoi rimuovere questo ramo)
            # params["orderLinkId"] = f"COPY_{master_oid[:20]}"
            pass

        # Campi ammendabili
        take_profit = ord_msg.get("takeProfit")
        stop_loss   = ord_msg.get("stopLoss")
        trigger_price = ord_msg.get("triggerPrice")
        tp_limit_price = ord_msg.get("tpLimitPrice")  # opzionale
        sl_limit_price = ord_msg.get("slLimitPrice")  # opzionale

        # Se non c'è niente da modificare, esci
        if not any([take_profit, stop_loss, trigger_price, tp_limit_price, sl_limit_price]):
            return

        if take_profit:
            params["takeProfit"] = str(take_profit)
        if stop_loss:
            params["stopLoss"] = str(stop_loss)
        if trigger_price:
            params["triggerPrice"] = str(trigger_price)
        if tp_limit_price and float(tp_limit_price) > 0:
            params["tpLimitPrice"] = str(tp_limit_price)
        if sl_limit_price and float(sl_limit_price) > 0:
            params["slLimitPrice"] = str(sl_limit_price)

        log.info(f"→ FOLLOW amend_order {params}")
        resp = follower_http.amend_order(**params)
        log.info(f"FOLLOWER AMEND RESPONSE: {resp}")

        # Se l'ordine non esiste più sul follower, potremmo doverlo ricreare (opzionale)
        if resp.get("retCode") not in (0, 110043):  # 110043: not modified
            log.warning(f"Amend fallito sul follower: {resp}")

    except Exception as e:
        log.error(f"mirror_amend_order errore: {e}")

def mirror_set_trading_stop(follower_http: HTTP, ord_msg: dict):
    """
    Replica TP/SL a livello POSIZIONE sul follower, utile quando l'ordine master è già Filled.
    """
    try:
        symbol = ord_msg.get("symbol")
        if not symbol or not should_copy_symbol(symbol):
            return

        take_profit = ord_msg.get("takeProfit")
        stop_loss   = ord_msg.get("stopLoss")

        if not (take_profit or stop_loss):
            return

        params = dict(category=CATEGORY, symbol=symbol)
        if take_profit:
            params["takeProfit"] = str(take_profit)
        if stop_loss:
            params["stopLoss"] = str(stop_loss)

        # opzionale: trigger mode (LastPrice/MarkPrice/IndexPrice)
        tp_trig = ord_msg.get("tpTriggerBy")
        sl_trig = ord_msg.get("slTriggerBy")
        if tp_trig:
            params["tpTriggerBy"] = tp_trig
        if sl_trig:
            params["slTriggerBy"] = sl_trig

        # one-way => positionIdx=0 (di solito non serve impostarlo, ma lo lasciamo commentato)
        # params["positionIdx"] = 0

        log.info(f"→ FOLLOW set_trading_stop {params}")
        resp = follower_http.set_trading_stop(**params)
        log.info(f"FOLLOWER set_trading_stop RESPONSE: {resp}")
        if resp.get("retCode") not in (0, 110043):
            log.warning(f"set_trading_stop fallito sul follower: {resp}")

    except Exception as e:
        log.error(f"mirror_set_trading_stop errore: {e}")


def mirror_place_order(master_http: HTTP, follower_http: HTTP, order: dict):
    try:
        symbol = order.get("symbol")
        if not symbol or not should_copy_symbol(symbol):
            return

        side = order.get("side")                 # "Buy"/"Sell"
        order_type = order.get("orderType")      # "Market"/"Limit"
        status = order.get("orderStatus") or order.get("status")
        tif = order.get("timeInForce") or "GoodTillCancel"
        reduce_only = bool(order.get("reduceOnly") or False)

        # quantità dal master
        qty_master = float(order.get("qty") or order.get("orderQty") or order.get("cumExecQty") or 0.0)
        if qty_master <= 0:
            log.info(f"Skip: qty_master<=0 | RAW={order}")
            return

        # filtri follower
        qty_step, px_step, min_qty = get_filters(follower_http, symbol)

        # scala quantità (wallet_ratio o multiplier) e arrotonda
        qty_follow = max(scale_quantity(qty_master, master_http, follower_http, symbol), min_qty)
        qty_follow = _round_to_step(qty_follow, qty_step)

        # prezzo (se LIMIT) arrotondato al tick del follower
        price = order.get("price")
        if order_type == "Limit":
            try:
                price = float(price)
                price = _round_to_step(price, px_step)
            except Exception:
                log.warning(f"Limit senza price valido, skip. RAW={order}")
                return

        # imposta la leva prima del place
        ensure_leverage(follower_http, symbol, LEVERAGE)

        params = dict(
            category=CATEGORY,
            symbol=symbol,
            side=side,
            orderType=order_type,
            qty=str(qty_follow),
            timeInForce=tif,
            reduceOnly=reduce_only,
            orderLinkId=generate_link_id("COPY"),
        )

        if order_type == "Limit":
            params["price"] = str(price)

        # TP/SL se presenti sull'ordine
        if order.get("takeProfit"): params["takeProfit"] = str(order["takeProfit"])
        if order.get("stopLoss"):   params["stopLoss"]   = str(order["stopLoss"])

        # eventuale trigger (conditional/stop)
        if order.get("triggerPrice"):
            params["triggerPrice"] = str(order["triggerPrice"])
            if order.get("triggerDirection"):
                params["triggerDirection"] = order["triggerDirection"]

        log.info(f"MASTER→FOLLOW {symbol} {side} {order_type} qty {qty_master}→{qty_follow} px={price} tif={tif}")
        log.info(f"→ FOLLOW place_order {params}")

        resp = follower_http.place_order(**params)
        log.info(f"FOLLOWER RESPONSE: {resp}")
        rc = resp.get("retCode", -1)
        if rc != 0:
            log.error(f"place_order follower KO: retCode={rc} retMsg={resp.get('retMsg')} params={params}")
            return

        follower_oid = resp["result"].get("orderId")
        master_oid_key = master_key_from(order)  # usa la tua funzione di chiave composita, vedi sotto
        if master_oid_key and follower_oid:
            ID_MAP[master_oid_key] = follower_oid
            save_map(ID_MAP)

    except Exception as e:
        log.error(f"mirror_place_order errore: {e}")

def master_key_from(ord_msg: dict) -> str:
    # costruisci una chiave composita stabile per il mapping
    sym = ord_msg.get("symbol", "")
    oid = ord_msg.get("orderId", "") or ord_msg.get("orderLinkId", "")
    ct  = str(ord_msg.get("createdTime", "")) or str(ord_msg.get("updatedTime", ""))
    side = ord_msg.get("side","")
    # es: "BTCUSDT|Buy|272d...|17557..."
    return f"{sym}|{side}|{oid}|{ct}"


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
    """Replica un ordine Market già eseguito sul MASTER aprendo un Market equivalente sul FOLLOWER."""
    try:

        link_id_source = str(exec_msg.get("orderId") or int(time.time()*1000))
        link_id_short = link_id_source[:20]  # taglia a max 20 caratteri
        link_id = f"COPY_{link_id_short}"
        #link_id = generate_link_id("COPY")        

        symbol = exec_msg.get("symbol")
        if not symbol or not should_copy_symbol(symbol):
            return

        side = exec_msg.get("side")  # Buy/Sell

        # Prova a prendere la size dall'execution o dall'ordine
        exec_qty = float(
            exec_msg.get("execQty") or
            exec_msg.get("cumExecQty") or
            exec_msg.get("qty") or 0
        )
        if exec_qty <= 0:
            log.warning(f"⚠️ Nessuna quantità valida nell'evento Market Filled: {exec_msg}")
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
            orderLinkId=generate_link_id("COPY"),
        )

        log.info(f"→ FOLLOW market(place) from exec {params}")
        resp = follower_http.place_order(**params)
        log.info(f"FOLLOWER RESPONSE: {resp}")
    except Exception as e:
        log.error(f"mirror_market_from_execution errore: {e}")

# ============================
# WEBSOCKET HANDLERS (MASTER)
# ============================

def on_order(message: dict, master_http: HTTP, follower_http: HTTP):
    try:
        data = message.get("data") or []
        if not data:
            log.debug(f"Nessun ordine in messaggio: {message}")
            return

        for ord_msg in data:
            try:
                status = ord_msg.get("orderStatus") or ord_msg.get("status")
                symbol = ord_msg.get("symbol")
                oid = ord_msg.get("orderId")
                log.info(f"MASTER order event {symbol} {status} oid={oid}")

                # 1) Ordine nuovo / non eseguito ⇒ replica creazione
                if status in ("Created", "New", "Untriggered", "PartiallyFilled"):
                    mirror_place_order(master_http, follower_http, ord_msg)
                    continue

                # 2) Amend su ordine aperto ⇒ amend_order sul follower
                if status == "Amended":
                    mirror_amend_order(follower_http, ord_msg)
                    continue

                # 3) Filled (market/limit) ⇒ se TP/SL presenti ⇒ aggiorna posizione sul follower
                if status == "Filled":
                    if ord_msg.get("takeProfit") or ord_msg.get("stopLoss"):
                        mirror_set_trading_stop(follower_http, ord_msg)
                    # NB: per i Market Filled immediati apriamo già la copia con mirror_market_from_execution altrove

                # 4) Cancellazioni e rifiuti ⇒ cancella sul follower
                if status in ("Cancelled", "Rejected"):
                    mirror_cancel_order(follower_http, ord_msg)

            except Exception as inner:
                log.error(f"Errore interno processando ord_msg: {inner} | RAW={ord_msg}")

    except Exception as e:
        log.error(f"on_order errore: {e} | RAW={message}")

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
    try:
        if message.get("type") not in ("snapshot", "delta"):
            return
        for ex in (message.get("data") or []):
            log.debug(f"RAW EXECUTION: {json.dumps(ex, ensure_ascii=False)}")
            exec_type = ex.get("execType")
            if exec_type != "Trade":
                continue
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
