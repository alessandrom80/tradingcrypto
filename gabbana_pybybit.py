from pybit.unified_trading import HTTP

import logging
logging.basicConfig(filename="gabbana_pybybit.log", level=logging.DEBUG,
                    format="%(asctime)s %(levelname)s %(message)s")

import sys

symbol = sys.argv[1]
side = sys.argv[2]
qty = sys.argv[3]
price = sys.argv[4]
stopLoss = sys.argv[5]
takeProfit = sys.argv[6]
leverage = sys.argv[7]
tradeMode = sys.argv[8]

# print(sys.argv)

session = HTTP(
    testnet=False,
    api_key="ROf1fzWGHnxBvnAwVp",
    api_secret="iuBJW7Ti4scQFQOCOoxjlcK6hVEy7rXzgwYC",
)

tickers = session.get_tickers(
    category="linear",
    symbol=symbol,
)


wallet = session.get_wallet_balance(
    accountType="UNIFIED",
    coin="USDT",
)
# print(tickers)
price = tickers['result']['list'][0]['lastPrice']

# print(wallet['result']['list'][0]['coin'][0]['usdValue'])
# print(wallet['result']['list'][0]['totalAvailableBalance'])
# trading_balance =(25/100) * float(wallet['result']['list'][0]['totalAvailableBalance']) 
# print(wallet['result']['list'][0]['coin'][0]['usdValue'])
trading_balance = float((10/100)) * float(wallet['result']['list'][0]['coin'][0]['usdValue']) 
# print(trading_balance)
trading_balance=f'{trading_balance:.9f}'
# tarding_qty = (trading_balance/float(price))*float(leverage)
tarding_qty = (float(trading_balance)/float(price))*float(leverage)
# tarding_qty = (float(trading_balance)/float(price))
# print(trading_balance,float(price),float(leverage))
# print(session.upgrade_to_unified_trading_account())
# print(round(tarding_qty))
# print(session.upgrade_to_unified_trading_account())

# session.switch_margin_mode(
#     category="linear",
#     symbol=symbol,
#     tradeMode= 0  if tradeMode == "Cross" else 1,
#     buyLeverage=leverage,
#     sellLeverage=leverage,
# )

session.place_order(
    category="linear",
    symbol=symbol,
    side=side,
    orderType="Market",
    # orderType="Limit",
    qty=round(tarding_qty),
    # minPrice="10",
    price=price,
    # timeInForce="PostOnly",
    # orderLinkId="linear-t2",
    isLeverage=1,
    orderFilter="Order",
    stopLoss=stopLoss,
    #slLimitPrice=stopLoss,
    #tpslMode="Partial",
    # slOrderType="Limit",
    # tpOrderType="Limit",
    #tpLimitPrice=takeProfit,
    marketUnit="quoteCoin",
    # positionIdx= 1 if side == "Buy" else 0,
    takeProfit=takeProfit,
) 


position = session.get_positions(
    category="linear",
    symbol=symbol,
)

if position['result']['list'][0]['leverage'] != leverage :

    session.set_leverage(
        category="linear",
        symbol=symbol,
        buyLeverage=leverage,
        sellLeverage=leverage,
    )

    
response = session.get_open_orders(category="linear",symbol=symbol)
order = response["result"]["list"]
print(order)

if len(order) == 0:
    subprocess.Popen([f"python3 gabbana_pybybit.py {symbol} {side} {qty} {price} {stopLoss} {takeProfit} {leverage} {tradeMode}"], stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=True)
