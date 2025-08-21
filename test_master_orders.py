import os, json, time
from dotenv import load_dotenv
from pybit.unified_trading import WebSocket

load_dotenv()  # carica le chiavi dal .env

MASTER_API_KEY = os.getenv("BYBIT_MASTER_API_KEY", "")
MASTER_API_SECRET = os.getenv("BYBIT_MASTER_API_SECRET", "")

if not MASTER_API_KEY or not MASTER_API_SECRET:
    raise SystemExit("⚠️ Configura le variabili BYBIT_MASTER_API_KEY e BYBIT_MASTER_API_SECRET nel .env")

# Connessione al WebSocket privato del MASTER
ws = WebSocket(
    testnet=False,                 # True se usi testnet
    channel_type="private",
    api_key=MASTER_API_KEY,
    api_secret=MASTER_API_SECRET,
    ping_interval=20,
    trace_logging=False,
)

def handle_order(message):
    print("📩 RAW ORDER MESSAGE:")
    print(json.dumps(message, indent=2, ensure_ascii=False))

ws.order_stream(handle_order)

print("✅ In ascolto sugli ordini del MASTER...")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("Uscita manuale.")
