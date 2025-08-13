from pybit.unified_trading import WebSocket
from pybit.unified_trading import HTTP
from datetime import datetime
import time
import pytz

import logging

import smtplib,ssl
from email.mime.text import MIMEText
YOUR_GOOGLE_EMAIL = 'xautechnology@gmail.com'  # The email you setup to send the email using app password
YOUR_GOOGLE_EMAIL_APP_PASSWORD = 'zpow lwnx nqoe fbyx'  # The app password you generated
sender = YOUR_GOOGLE_EMAIL
recipients = ["mauroalci@gmail.com", "drop.digital82@gmail.com"]
#recipients = ["mauroalci@gmail.com"]

TIMEFRAME=15
ALERT=0.39

# --- NUOVO: variabili per la gestione del rischio ---
LEVERAGE = 20  # Leva da usare per le transazioni
ORDER_PERCENT = 0.10  # Percentuale del bilancio per l'apertura dell'ordine (2%)
SL_PERCENT = 0.65  # Percentuale per il calcolo dello stop loss (60%)
TP_PERCENT = 0.115  # Percentuale per il calcolo del take profit (10%)

last_output_btc = ""
last_output_avax = ""
delta_btc=0.0
delta_timestamp=0.0 
# --- AGGIUNGI vicino agli import / config ---
last_trade_ts = {}  # es: {"AVAXUSDT": 1720000000000}


# Logging su file
logging.basicConfig(filename="bot.log", level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

# Connessione al WebSocket (privato, ma non serve autenticazione per kline pubbliche)
ws = WebSocket(
    testnet=False,
    channel_type="linear",
    api_key="Bc5jAXTcZSYrDv6ifQ",
    ping_interval=None, 
    api_secret="P5NlADKvjZNE1lsmsu2hxhrGxTmXBgI5KCSt",
    trace_logging=False,
)

# Connessione al WebSocket (privato, ma non serve autenticazione per kline pubbliche)
wsdemo = WebSocket(
    testnet=True,
    channel_type="linear",
    api_key="Iz8VjZXy5fCMhTgwts",
    ping_interval=None, 
    api_secret="nxC75PkZhvQq2thOyw0ZPu83mZx1UuemY7p5",
    trace_logging=False,
)

httpdemo = HTTP(
    api_key="Iz8VjZXy5fCMhTgwts",
    api_secret="nxC75PkZhvQq2thOyw0ZPu83mZx1UuemY7p5",
)

http = HTTP(
    api_key="NGZ4WnPGi7vzmPMd2q",  
    api_secret="lssBuYfP61yind7taU5YpkVMXupUDoDOy4Sj",  
)


# --- AGGIUNGI utility ---
def _round_to_step(value, step):
    try:
        step = float(step)
        if step <= 0:
            return value
        return round((int(value / step)) * step, 8)
    except Exception:
        return value

def _get_filters(client, symbol):
    try:
        info = client.get_instruments_info(category="linear", symbol=symbol)["result"]["list"][0]
        lot = float(info["lotSizeFilter"]["qtyStep"])
        tick = float(info["priceFilter"]["tickSize"])
        min_qty = float(info["lotSizeFilter"]["minOrderQty"])
        return lot, tick, min_qty
    except Exception as e:
        logging.error(f"Errore get_instruments_info: {e}")
        # fallback prudenziale
        return 0.001, 0.01, 0.001

def _has_open_position(client, symbol):
    """Ritorna (True, pos) se c'è una posizione aperta su symbol."""
    try:
        pos = client.get_positions(category="linear", symbol=symbol)["result"]["list"]
        for p in pos:
            size = float(p.get("size") or 0)
            if size > 0:
                return True, p
        return False, None
    except Exception as e:
        logging.error(f"Errore get_positions: {e}")
        return False, None
    
# -----

def esegui_trade_live_avax(delta_percent, ts_ms):
    symbol = "AVAXUSDT"

    # evita riaperture sulla stessa candela
    if last_trade_ts.get(symbol) == ts_ms:
        print(f"⏭️ Trade già eseguito per {symbol} sulla candela {ts_ms}, salto.")
        return

    try:
        # Se c'è già una posizione aperta, non aprirne una nuova
        already_open, pos = _has_open_position(http, symbol)
        if already_open:
            side_open = pos.get("side")
            size_open = pos.get("size")
            print(f"🔒 Posizione già aperta su {symbol} (side={side_open}, size={size_open}). Niente nuova apertura.")
            logging.info(f"Skip apertura: posizione già aperta su {symbol}.")
            return

        # saldo disponibile (UNIFIED)
        wallet = http.get_wallet_balance(accountType="UNIFIED")["result"]["list"][0]["coin"]
        usdt = next((c for c in wallet if c["coin"] == "USDT"), None)
        if not usdt:
            print("Saldo USDT non trovato.")
            return
        disponibile = float(usdt.get("availableToTrade") or usdt.get("walletBalance") or 0.0)
        if disponibile <= 5:
            print("Saldo insufficiente per aprire posizione.")
            return

        # direzione: candela BTC positiva ⇒ long, altrimenti short
        side = "Buy" if delta_percent > 0 else "Sell"

        # Ottieni il prezzo corrente con il metodo aggiornato
        last_price = get_ticker_price(http, symbol)  # Usa il nuovo metodo per il ticker
        if last_price is None:
            print("Errore nel recupero del prezzo. Impossibile eseguire il trade.")
            return

        qty_step, tick_size, min_qty = _get_filters(http, symbol)

        # Imposta la leva se necessario
        if set_leverage_if_needed(http, "AVAXUSDT", LEVERAGE):
            # Procedi con l'apertura del trade
            print("Leva correttamente impostata, procedo con l'ordine.")


        # imposta leva (idempotente)
        #http.set_leverage(category="linear", symbol=symbol, buyLeverage=str(LEVERAGE), sellLeverage=str(LEVERAGE))

        # calcolo quantità: 2% del balance * leva
        order_value = max(disponibile * ORDER_PERCENT * LEVERAGE, 5)  # minimo prudenziale
        
        qty_raw = order_value / last_price
        
        qty = max(_round_to_step(qty_raw, qty_step), min_qty)        
        # calcola SL (60% dal prezzo)
        qt= (order_value / LEVERAGE ) / last_price
        valore_sl=(last_price *  ( SL_PERCENT / LEVERAGE ))
        valore_tp=(last_price *  ( TP_PERCENT / LEVERAGE ))
        print(f"🚀 Saldo: {disponibile} \nUSDT impegnati {disponibile * ORDER_PERCENT}\n USDT (Leva) {order_value}\n AVAX reali {qt}\n AVAX (leva) {qty_raw}\n  ")
        if side == "Buy":            
            sl_price = last_price - valore_sl
            tp_price = last_price + valore_tp
        else:
            sl_price = last_price + valore_sl
            tp_price = last_price - valore_tp

        # arrotonda SL al tick
        print(f" valore_sl {valore_sl} valore_tp {valore_tp} \n last_price {last_price} \n sl_price {sl_price} tp_price {tp_price}")
        logging.warning(f" valore_sl {valore_sl} valore_tp {valore_tp} \n last_price {last_price} \n sl_price {sl_price} tp_price {tp_price}")
        #print(f"STOP LOSS CALCOLATO-> {sl_price} \n TAKE PROFIT CALCOLATO -> {tp_price} ")
        # sl_price = _round_to_step(sl_price, tick_size)
        # tp_price = _round_to_step(tp_price, tick_size)
        #print(f"sl_price {sl_price} {tp_price}") 

        print(f"🚀 LIVE {side} {symbol} | qty={qty} | px≈{last_price} | SL={sl_price} | TP={tp_price} | leva={LEVERAGE}")
        logging.warning(f"LIVE {side} {symbol} qty={qty} price≈{last_price} SL={sl_price} TP={tp_price} leverage={LEVERAGE}")

        #ordine MARKET con stop loss
        http.place_order(
            category="linear",
            symbol=symbol,
            side=side,
            orderType="Market",
            qty=str(qty),               # Bybit accetta string
            timeInForce="GoodTillCancel",
            stopLoss=str(sl_price),      # SL a livello di prezzo
            takeProfit=str(tp_price)
        )

        last_trade_ts[symbol] = ts_ms  # segna la candela
        print(f"✅ Ordine inviato su {symbol}.")
        logging.warning(f"Ordine inviato su {symbol} (side={side}, qty={qty}, SL={sl_price}, TP={tp_price})")

        try:
            summ_transaction = (
                f"Ordine {side} su {symbol}\n Quantità: {qty} \nPrezzo: {last_price} \nSL: {sl_price} {SL_PERCENT}\nTP: {tp_price} {TP_PERCENT}\nLeva: {LEVERAGE}\n\n\nUSDT realmente impegnati: {disponibile * ORDER_PERCENT}\nUSDT (Leva) {order_value}\n AVAX reali {qt}\n AVAX (leva) {qty_raw}\n Saldo del conto: {disponibile}"
            )
            invia_email_transaction(summ_transaction)
        except Exception as e:
            logging.error(f"Errore nell'invio dell'email per la transazione: {e}")
        
    except Exception as e:
        print(f"❌ Errore eseguendo trade live: {e}")
        logging.error(f"Errore trade live AVAX: {e}")


# def timestamp_to_datetime(ms_timestamp):
#     # Converte i millisecondi in secondi e poi in formato leggibile UTC
#     dt = datetime.utcfromtimestamp(ms_timestamp / 1000.0)
#     return dt.strftime("%Y-%m-%d %H:%M:%S UTC")

def timestamp_to_datetime(ms_timestamp):
    dt_utc = datetime.fromtimestamp(ms_timestamp / 1000.0, tz=pytz.UTC)
    dt_rome = dt_utc.astimezone(pytz.timezone("Europe/Rome"))
    return f"{dt_utc.strftime('%Y-%m-%d %H:%M:%S UTC')} / {dt_rome.strftime('%H:%M:%S Europe/Rome')}"


# Funzione di callback: viene chiamata ad ogni aggiornamento kline
def handle_kline(message):
    try:
        if message["type"] in ["snapshot", "delta"]:
            kline = message["data"][0]
            confirm_value = kline.get("confirm", False)
            #print(f"Ricevuta candela - Confirm: {confirm_value}")

            required_keys = ["confirm", "interval", "open", "high", "low", "close", "volume"]
            if not all(k in kline for k in required_keys):
                print("Messaggio kline incompleto, ignorato", kline)
                return
            
            if confirm_value is True:
                #print(kline)
                # Converti i valori a float (vengono come stringhe)
                open_price = float(kline['open'])
                close_price = float(kline['close'])

                # Calcola variazione percentuale
                delta_percent = ((close_price - open_price) / open_price) * 100
                #print(f"{timestamp_to_datetime(kline['timestamp'])} Candela chiusa BTC - Variazione percentuale: {delta_percent:.2f}% ({delta_percent:.3f}%)" + get_balance_usdt_demo())
                print(f"{timestamp_to_datetime(kline['timestamp'])} Candela chiusa BTC - Variazione percentuale: {delta_percent:.2f}% ({delta_percent:.3f}%)")

                logging.info(f"{timestamp_to_datetime(kline['timestamp'])} Candela chiusa BTC - Variazione percentuale: {delta_percent:.2f}% ({delta_percent:.3f}%)")

                global delta_btc
                delta_btc = delta_percent  # salva la variazione percentuale BTC
                global delta_timestamp
                delta_timestamp = kline['timestamp']  # salva il timestamp della candela

                if abs(delta_btc) >= ALERT:
                    global last_output_btc
                    
                    output = (
                        "\n====================[ Candela 15m chiusa - BTCUSDT ]====================\n"
                        f"Timestamp        : {kline['timestamp']} ({timestamp_to_datetime(kline['timestamp'])})\n"
                        #f"Symbol           : {kline['symbol']}\n"
                        f"Interval         : {kline['interval']}\n"
                        f"Open             : {kline['open']}\n"
                        f"High             : {kline['high']}\n"
                        f"Low              : {kline['low']}\n"
                        f"Close            : {kline['close']}\n"
                        f"Volume           : {kline['volume']}\n"
                        f"Turnover         : {kline['turnover']}\n"
                        f"Open Interest    : {kline.get('openInterest', 'N/A')}\n"
                        f"Trade Count      : {kline.get('tradeCount', 'N/A')}\n"
                        f"Confirm          : {kline['confirm']}\n"
                        f"Start Timestamp  : {kline['start']}\n"
                        f"End Timestamp    : {kline['end']}\n"
                        #f"Period (seconds) : {kline['period']}\n"
                        "========================================================================\n"
                    )
                    last_output_btc = output  # salva l'ultimo output BTC
                    print(output)
                    logging.warning(output)
                    invia_email_alert("BTCUSDT", delta_btc, delta_timestamp)
                    print(f"Email inviata per BTCUSDT: {delta_btc:.2f}% alle {timestamp_to_datetime(delta_timestamp)}"  )
                    logging.warning(f"Email inviata per BTCUSDT: {delta_btc:.2f}% alle {timestamp_to_datetime(delta_timestamp)}" )                        




    except Exception as e:
        print("Errore nella callback handle_kline:", e)            


def handle_kline_avax(message):
    try:
        if message["type"] in ["snapshot", "delta"]:
            kline = message["data"][0]
            confirm_value = kline.get("confirm", False)

            required_keys = ["confirm", "interval", "open", "high", "low", "close", "volume"]
            if not all(k in kline for k in required_keys):
                print("Messaggio AVAX incompleto, ignorato", kline)
                return

            if confirm_value is True:
                open_price = float(kline['open'])
                close_price = float(kline['close'])
                delta_percent = ((close_price - open_price) / open_price) * 100
                print(f"{timestamp_to_datetime(kline['timestamp'])} Candela chiusa AVAX - Variazione percentuale: {delta_percent:.2f}% ({delta_percent:.3f}%)")            
                logging.info(f"{timestamp_to_datetime(kline['timestamp'])} Candela chiusa AVAX - Variazione percentuale: {delta_percent:.2f}% ({delta_percent:.3f}%)")
        
                output = (
                    "\n====================[ Candela 15m chiusa - AVAXUSDT ]====================\n"
                    f"Timestamp        : {kline['timestamp']} ({timestamp_to_datetime(kline['timestamp'])})\n"
                    f"Interval         : {kline['interval']}\n"
                    f"Open             : {kline['open']}\n"
                    f"High             : {kline['high']}\n"
                    f"Low              : {kline['low']}\n"
                    f"Close            : {kline['close']}\n"
                    f"Volume           : {kline['volume']}\n"
                    f"Turnover         : {kline['turnover']}\n"
                    f"Open Interest    : {kline.get('openInterest', 'N/A')}\n"
                    f"Trade Count      : {kline.get('tradeCount', 'N/A')}\n"
                    f"Confirm          : {kline['confirm']}\n"
                    f"Start Timestamp  : {kline['start']}\n"
                    f"End Timestamp    : {kline['end']}\n"
                    "========================================================================\n"
                )
                #print(output)
                global last_output_avax
                last_output_avax = output
               
    except Exception as e:
        print("Errore nella callback handle_kline_avax:", e)

def set_leverage_if_needed(client, symbol, leverage):
    try:
        # Ottieni la leva attuale per il simbolo
        current_leverage = get_current_leverage(client, symbol)
        
        if current_leverage is None:
            print(f"Impossibile recuperare la leva per {symbol}")
            return False

        # Se la leva è già quella desiderata, non fare nulla
        if current_leverage == leverage:
            print(f"La leva per {symbol} è già impostata su {leverage}. Nessuna modifica.")
            return True  # La leva è già impostata correttamente

        # imposta leva (idempotente): ignora 110043
        try:
            resp = http.set_leverage(
                category="linear",
                symbol=symbol,
                buyLeverage=str(LEVERAGE),
                sellLeverage=str(LEVERAGE),
            )
            rc = resp.get("retCode", -1)
            # 0 = ok, 110043 = "leverage not modified" => ok da ignorare
            if rc not in (0, 110043):
                print(f"Impossibile impostare la leva: {resp.get('retMsg')}")
                return
        except Exception as e:
            msg = str(e)
            if "110043" in msg or "leverage not modified" in msg:
                pass  # già impostata: continua
            else:
                print(f"Errore set_leverage: {e}")
                return

        
        # Verifica la risposta
        if resp.get("retCode") == 0:
            print(f"Leva per {symbol} impostata a {leverage} con successo.")
            return True
        else:
            print(f"Errore nell'impostazione della leva: {resp.get('retMsg')}")
            return False
    except Exception as e:
        print(f"Errore nel recupero o impostazione della leva: {e}")
        return False


def get_current_leverage(client, symbol):
    try:
        # Ottieni le informazioni del simbolo
        response = client.get_instruments_info(category="linear", symbol=symbol)
        
        # Se la risposta contiene il risultato, prendi la leva
        if "result" in response and response["result"]:
            # Cerca la leva attuale nel risultato
            leverage = response["result"][0]["leverage"]
            return leverage
        else:
            print(f"Impossibile ottenere la leva per {symbol}. Risposta: {response}")
            return None
    except Exception as e:
        print(f"Errore nel recupero della leva: {e}")
        return None


# --- Aggiorna per utilizzare query_symbol o get_symbol_info --- 
def get_ticker_price(client, symbol):
    try:
        resp = client.get_tickers(category="linear", symbol=symbol)
        lst = resp["result"]["list"]
        if not lst:
            return None
        return float(lst[0]["lastPrice"])
    except Exception as e:
        print(f"Errore nel recupero ticker: {e}")
        return None



def invia_email_alert(symbol, delta_percent, timestamp_ms):
    data_str = timestamp_to_datetime(timestamp_ms)
    soglia = f"{ALERT:.2f}%"
    variazione = f"{delta_percent:.2f}%"
    
    corpo = (
        f"⚠️ ALERT - {symbol} ha superato la soglia di variazione {soglia}\n\n"
        f"Variazione rilevata: {variazione}\n"
        f"Orario candela: {data_str}\n"
        f"Simbolo: {symbol}\n"
        f"Timeframe: {TIMEFRAME} minuti\n\n\n"
        f"{last_output_btc}\n\n"
        # f"{last_output_avax}\n"
    )

    # print("\n------ ESEMPIO EMAIL ------")
    # print(f"Oggetto: ALERT {symbol} {variazione}")
    # print(corpo)
    # print("---------------------------\n")  

    msg = MIMEText(corpo)
    # Set the subject of the email.
    msg['Subject'] = "BOT HAWK: NEW SIGNAL"
    # Set the sender's email.
    msg['From'] = sender
    # Join the list of recipients into a single string separated by commas.
    msg['To'] = ', '.join(recipients)
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp_server:
            # Login to the SMTP server using the sender's credentials.
            # smtp_server.starttls(context=ssl.create_default_context())
            # smtp_server.login(sender, password)
            smtp_server.ehlo()
            smtp_server.login(YOUR_GOOGLE_EMAIL, YOUR_GOOGLE_EMAIL_APP_PASSWORD)
            # Send the email. The sendmail function requires the sender's email, the list of recipients, and the email message as a string.
            smtp_server.sendmail(sender, recipients, msg.as_string())
            esegui_trade_live_avax(delta_percent, timestamp_ms)
    
def invia_email_transaction(transaction_summary):
   
    corpo = (
        f"⚠️ ALERT - E' stata aperta una transazione! \n\n"
        f"{transaction_summary}\n"
    )

    msg = MIMEText(corpo)
    # Set the subject of the email.
    msg['Subject'] = "BOT HAWK: NEW TRANSACTION ALERT"    
    # Set the sender's email.
    msg['From'] = sender
    # Join the list of recipients into a single string separated by commas.
    msg['To'] = ', '.join(recipients)
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp_server:
            # Login to the SMTP server using the sender's credentials.
            # smtp_server.starttls(context=ssl.create_default_context())
            # smtp_server.login(sender, password)
            smtp_server.ehlo()
            smtp_server.login(YOUR_GOOGLE_EMAIL, YOUR_GOOGLE_EMAIL_APP_PASSWORD)
            # Send the email. The sendmail function requires the sender's email, the list of recipients, and the email message as a string.
            smtp_server.sendmail(sender, recipients, msg.as_string())


print("Avvio con valori")
print("=========================")
print(f"Timeframe: {TIMEFRAME} minuti")
print(f"Soglia di alert: {ALERT:.2f}%")
print("=========================\n")

# try:
#     #result = httpdemo.get_wallet_balance(accountType="UNIFIED")
#     result = httpdemo.get_wallet_balance(accountType="UNIFIED")["result"]["list"][0]["coin"]

#     print(result)
# except Exception as e:
#     print("Errore di autenticazione:", e)

try:
    # Tutta la configurazione WebSocket
    # ws.kline_stream(
    #     symbol="AVAXUSDT",
    #     interval=TIMEFRAME,
    #     callback=handle_kline_avax
    # )


    ws.kline_stream(
        symbol="BTCUSDT",
        interval=TIMEFRAME,
        callback=handle_kline
    )


    while True:
        time.sleep(1)

except Exception as e:
    print("Errore:", e)
