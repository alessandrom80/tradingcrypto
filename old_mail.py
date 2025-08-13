from telethon import TelegramClient, events, sync
import subprocess
from subprocess import Popen,PIPE

from pybit.unified_trading import HTTP

# from time import sleep

# Import WebSocket from the unified_trading module.
from pybit.unified_trading import WebSocket

# Set up logging (optional)
import logging



# These example values won't work. You must get your own api_id and
# api_hash from https://my.telegram.org, under API Development.
api_id = 26719267
api_hash = 'af0bba5d6a47f192dd9f5951a7321398'

client = TelegramClient('pycpt', api_id, api_hash)


# print(client.get_me().stringify())
# messages = client.get_messages('@GIOTHOBI')

# print(messages)

@client.on(events.NewMessage)
async def handler(event):
    # print(event.message)
    # print(event.raw_text[:300])
    signal = event.raw_text[:300]
    signalsArray = signal.splitlines(True)
    
    for idx, sA in enumerate(signalsArray):
        #print(idx,sA)
        if idx == 0 :
            symbol =sA.split()[0]
        if idx == 1:
            # sA.replace("(", "").replace(")", "").replace("x", "")
            tradeMode = sA.split()[0].replace("(", "")
            shortLong =  sA.split()[1]
            leverage  = sA.split()[2].replace("x)", "")
        if idx == 3:
            price = sA.split()[3]
        if 'TP3:' in sA:
            takeProfit = sA.split()[1]
        if 'STOP LOSS:' in sA:
            stopLoss = sA.split()[2]

    # print(symbol + '-' + tradeMode + '-' + shortLong + '-' + leverage +'-' + price + '-' + takeProfit +'-'+ stopLoss)

    side = "Sell" if shortLong == "SHORT" else "Buy"
    qty =  100 if float(price)<1  else 10
    
    # print(f"python ricky_pybybit.py {symbol} {side} {qty} {price} {stopLoss} {takeProfit}")
    # process = subprocess.Popen(["python", "ricky_pybybit.py",symbol,side,qty,price,stopLoss,takeProfit], stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=True)
    ricky_pybybit = subprocess.Popen([f"python ricky_pybybit.py {symbol} {side} {qty} {price} {stopLoss} {takeProfit}"], stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=True)
    # process_2 = subprocess.Popen([f"python ricky_pybybit.py {symbol} {side} {qty} {price} {stopLoss} {takeProfit}"], stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=True)
    

client.start()
client.run_until_disconnected()
# import time
# import cv2
# import mss
# import numpy
# import pytesseract
# import re

# pattern = r"\b\w+\b"  # Matches all words
# mon = {'top': 50, 'left': 0, 'width': 250, 'height': 1000}

# first_im = numpy.asarray(mss.mss().grab(mon))
# first_text = pytesseract.image_to_string(first_im)
# print(first_text)
# # matches = re.findall(pattern, first_text)
# # print(matches)

# with mss.mss() as sct:
#     while True:
#         im = numpy.asarray(sct.grab(mon))
#         # im = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)

#         text = pytesseract.image_to_string(im)
#         if(first_text != text):
#             print(text)
            # first_text=text
            # matches = re.findall(pattern, text)
            # print(matches)
            
        

        # cv2.imshow('Image', im)

        # Press "q" to quit
        # if cv2.waitKey(25) & 0xFF == ord('q'):
        #     cv2.destroyAllWindows()
        #     break

        # One screenshot per second
        # time.sleep(1)
