from pybit.unified_trading import HTTP

from time import sleep

# Import WebSocket from the unified_trading module.
from pybit.unified_trading import WebSocket

# Set up logging (optional)
import logging
logging.basicConfig(filename="pybit.log", level=logging.DEBUG,
                    format="%(asctime)s %(levelname)s %(message)s")

session = HTTP(
    testnet=False,
    api_key="iaQ7a5FC69KcoTqX1R",
    api_secret="S5jMtSKV5Qxa41FHMGgVPhYgphN4la0TJJsL",
)


#TradeMOde  0 = Cross, 1 = Isolated
# session.switch_margin_mode(
#     category="linear",
#     symbol="HBARUSDT",
#     tradeMode=0,
#     buyLeverage="20",
#     sellLeverage="20",
# )

# session.set_leverage(
#     category="linear",
#     symbol="HBARUSDT",
#     buyLeverage="20",
#     sellLeverage="20",
# )


# session.place_order(
# category="linear",
# symbol="HBARUSDT",
# side="Buy",
# orderType="Limit",
# qty="100",
# price="0.180",
# timeInForce="GTC",
# positionIdx=0,
# orderLinkId="usdt-test-01",
# reduceOnly=False,
# takeProfit="0.186",
# stopLoss="0.15",
# #tpslMode="Partial",
# tpOrderType="Limit",
# slOrderType="Limit",
# tpLimitPrice="0.186",
# slLimitPrice="0.15"
# )
session.place_order(
    category="linear",
    symbol="HBARUSDT",
    side="Buy",
    orderType="Limit",
    qty="100",
    # minPrice="10",
    price="0.172",
    # timeInForce="PostOnly",
    orderLinkId="linear-test",
    isLeverage=1,
    orderFilter="Order",
    stopLoss="0.15",
    slLimitPrice="0.15",
    #tpslMode="Partial",
    slOrderType="Limit",
    tpOrderType="Limit",
    tpLimitPrice="0.176",
    marketUnit="quoteCoin",
)

response = session.get_open_orders(
    category="linear",
    symbol="HBARUSDT",
)

orders = response["result"]["list"]
print(orders)

ws = WebSocket(
    testnet=False,
    channel_type="linear",
)

ws_private = WebSocket(
    testnet=False,
    # channel_type="private",
    channel_type="linear",
    api_key="iaQ7a5FC69KcoTqX1R",
    api_secret="S5jMtSKV5Qxa41FHMGgVPhYgphN4la0TJJsL",
    trace_logging=True,
)


# Let's fetch the orderbook for BTCUSDT. First, we'll define a function.
def handle_orderbook(message):
    # I will be called every time there is new orderbook data!
    print(message)
    orderbook_data = message["data"]

# Now, we can subscribe to the orderbook stream and pass our arguments:
# our depth, symbol, and callback function.
# ws.orderbook_stream(50, "BTCUSDT", handle_orderbook)


# To subscribe to private data, the process is the same:
def handle_position(message):
    # I will be called every time there is new position data!
    print(message)

# ws_private.position_stream(handle_position)


while True:
    # This while loop is required for the program to run. You may execute
    # additional code for your trading logic here.
    sleep(1)