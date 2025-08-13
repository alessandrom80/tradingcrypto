from telethon import TelegramClient, events, sync
import subprocess
from subprocess import Popen,PIPE

from pybit.unified_trading import HTTP

# Import WebSocket from the unified_trading module.
from pybit.unified_trading import WebSocket

import smtplib,ssl
from email.mime.text import MIMEText

# YOUR_GOOGLE_EMAIL = 'xautechnology@gmail.com'  # The email you setup to send the email using app password
YOUR_GOOGLE_EMAIL = 'xautechnology@gmail.com'  # The email you setup to send the email using app password
YOUR_GOOGLE_EMAIL_APP_PASSWORD = 'zpow lwnx nqoe fbyx'  # The app password you generated
# Define the subject and body of the email.
subject = "New Siganl"
body = ""
# Define the sender's email address.
# sender = "oreder@dev.xautechnology.com"
sender = YOUR_GOOGLE_EMAIL
# List of recipients to whom the email will be sent.
# recipients = ["riccardo.volpone@gmail.com", "drop.digital82@gmail.com", "gabrieleclaudioizzi@gmail.com","infonovasistemi@gmail.com","graphicprint24@gmail.com,michele.denardis1@gmail.com","peppe.roscio@gmail.com","lucasallustro1989@gmail.com","giona982@gmail.com","mariotersigni@gmail.com","sandrotersigni53@gmail.com"]
recipients = ["riccardo.volpone@gmail.com", "drop.digital82@gmail.com"]
# Password for the sender's email account.
# password = "md-iPuuFKXN5BjoJV1Kas4SlQ"
password = YOUR_GOOGLE_EMAIL_APP_PASSWORD

def send_email(subject, body, sender, recipients, password):
    # Create a MIMEText object with the body of the email.
    msg = MIMEText(body)
    # Set the subject of the email.
    msg['Subject'] = subject
    # Set the sender's email.
    msg['From'] = sender
    # Join the list of recipients into a single string separated by commas.
    msg['To'] = ', '.join(recipients)
   
    # Connect to Gmail's SMTP server using SSL.
    # with smtplib.SMTP_SSL('dev.xautechnology.com', 465) as smtp_server:
    # with smtplib.SMTP_SSL('smtp.mandrillapp.com', 587) as smtp_server:
    # with smtplib.SMTP('smtp.mandrillapp.com', 587) as smtp_server:
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp_server:
        # Login to the SMTP server using the sender's credentials.
        # smtp_server.starttls(context=ssl.create_default_context())
        # smtp_server.login(sender, password)
        smtp_server.ehlo()
        smtp_server.login(YOUR_GOOGLE_EMAIL, YOUR_GOOGLE_EMAIL_APP_PASSWORD)
        # Send the email. The sendmail function requires the sender's email, the list of recipients, and the email message as a string.
        smtp_server.sendmail(sender, recipients, msg.as_string())
    # Print a message to console after successfully sending the email.
    # print("Message sent!")
# Set up logging (optional)
# import logging

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

    signal = event.raw_text[:300]
    signalsArray = signal.splitlines(True)
    
    with open("all_messages.txt", "a") as all_messages:
                # siganl_file.write(signalsArray)
                all_messages.write(signal+ "\n")
                
    
    if len(signalsArray) != 0 : 
        
        if "USDT Perpetual" in signalsArray[0]:
            
            with open("signal.txt", "a") as siganl_file:
                # siganl_file.write(signalsArray)
                siganl_file.write(''.join(map(str, signalsArray))+ "\n")   
                send_email(subject, ''.join(map(str, signalsArray)), sender, recipients, password)           

            for sA in signalsArray:
                if "USDT Perpetual" in sA:
                    symbol = sA.split()[0]
                if "x)" in sA:
                    tradeMode = sA.split()[0].replace("(", "")
                    shortLong = sA.split()[1]
                    leverage  = sA.split()[2].replace("x)", "")
                if "ORDER PRICE" in sA:
                    price = sA.split()[3]
                if 'TP3:' in sA:
                    takeProfit = sA.split()[1]
                if 'STOP LOSS:' in sA:
                    stopLoss = sA.split()[2]
       
            side = "Sell" if shortLong == "SHORT" else "Buy"
            qty =  100 if float(price)<1  else 10
                    
            with open("call.txt", "a") as call_file:
                call_file.write(f"python3 ricky_pybybit.py {symbol} {side} {qty} {price} {stopLoss} {takeProfit} {leverage} {tradeMode}"+ "\n")
            # print(f"python3 ricky_pybybit.py {symbol} {side} {qty} {price} {stopLoss} {takeProfit} {leverage} {tradeMode}")

            ricky_pybybit = subprocess.Popen([f"python3 ricky_pybybit.py {symbol} {side} {qty} {price} {stopLoss} {takeProfit} {leverage} {tradeMode}"], stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=True)
            with open("err_ricky_pybybit.txt", "a") as err_ricky_pybybit:
                err_ricky_pybybit.write(str(ricky_pybybit.communicate())+ "\n")
                #send_email('New Order', str(ricky_pybybit.communicate()), sender, ['riccardo.volpone@gmail.com'], password)

            giothobi_pybybit = subprocess.Popen([f"python3 giothobi_pybybit.py {symbol} {side} {qty} {price} {stopLoss} {takeProfit} {leverage} {tradeMode}"], stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=True)
            with open("err_giothobi_pybybit.txt", "a") as err_giothobi_pybybit:
                err_giothobi_pybybit.write(str(giothobi_pybybit.communicate())+ "\n")
                send_email('New Order', str(giothobi_pybybit.communicate()), sender, ['drop.digital82@gmail.com'], password)
            
            gabbana_pybybit = subprocess.Popen([f"python3 gabbana_pybybit.py {symbol} {side} {qty} {price} {stopLoss} {takeProfit} {leverage} {tradeMode}"], stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=True)
            with open("err_gabbana_pybybit.txt", "a") as err_gabbana_pybybit:
                err_gabbana_pybybit.write(str(gabbana_pybybit.communicate())+ "\n")
                # send_email('New Order', str(gabbana_pybybit.communicate()), sender, ['gabrieleclaudioizzi@gmail.com'], password)
            
            # dottore_pybybit = subprocess.Popen([f"python3 dottore_pybybit.py {symbol} {side} {qty} {price} {stopLoss} {takeProfit} {leverage} {tradeMode}"], stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=True)
            # with open("err_dottore_pybybit.txt", "a") as err_dottore_pybybit:
            #     err_dottore_pybybit.write(str(dottore_pybybit.communicate())+ "\n")
            #     send_email('New Order', str(dottore_pybybit.communicate()), sender, ['infonovasistemi@gmail.com'], password)
            
            # montinaro_pybybit = subprocess.Popen([f"python3 montinaro_pybybit.py {symbol} {side} {qty} {price} {stopLoss} {takeProfit} {leverage} {tradeMode}"], stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=True)
            # with open("err_montinaro_pybybit.txt", "a") as err_montinaro_pybybit:
            #     err_montinaro_pybybit.write(str(montinaro_pybybit.communicate())+ "\n")
            #     send_email('New Order', str(montinaro_pybybit.communicate()), sender, ['graphicprint24@gmail.com'], password)
            
            denardis_pybybit = subprocess.Popen([f"python3 denardis_pybybit.py {symbol} {side} {qty} {price} {stopLoss} {takeProfit} {leverage} {tradeMode}"], stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=True)
            with open("err_denardis_pybybit.txt", "a") as err_denardis_pybybit:
                err_denardis_pybybit.write(str(denardis_pybybit.communicate())+ "\n")
                # send_email('New Order', str(denardis_pybybit.communicate()), sender, ['michele.denardis1@gmail.com'], password)
            
            pepperoscio_pybybit = subprocess.Popen([f"python3 pepperoscio_pybybit.py {symbol} {side} {qty} {price} {stopLoss} {takeProfit} {leverage} {tradeMode}"], stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=True)
            with open("err_pepperoscio_pybybit.txt", "a") as err_pepperoscio_pybybit:
                err_pepperoscio_pybybit.write(str(pepperoscio_pybybit.communicate())+ "\n")
                # send_email('New Order', str(pepperoscio_pybybit.communicate()), sender, ['peppe.roscio@gmail.com'], password)
            
            lucasallustro_pybybit = subprocess.Popen([f"python3 lucasallustro_pybybit.py {symbol} {side} {qty} {price} {stopLoss} {takeProfit} {leverage} {tradeMode}"], stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=True)
            with open("err_lucasallustro_pybybit.txt", "a") as err_lucasallustro_pybybit:
                err_lucasallustro_pybybit.write(str(lucasallustro_pybybit.communicate())+ "\n")
                # send_email('New Order', str(lucasallustro_pybybit.communicate()), sender, ['lucasallustro1989@gmail.com'], password)
            
            giona982_pybybit = subprocess.Popen([f"python3 giona982_pybybit.py {symbol} {side} {qty} {price} {stopLoss} {takeProfit} {leverage} {tradeMode}"], stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=True)
            with open("err_giona982_pybybit.txt", "a") as err_giona982_pybybit:
                err_giona982_pybybit.write(str(giona982_pybybit.communicate())+ "\n")
                # send_email('New Order', str(giona982_pybybit.communicate()), sender, ['giona982@gmail.com'], password)

            mariotersigni_pybybit = subprocess.Popen([f"python3 mariotersigni_pybybit.py {symbol} {side} {qty} {price} {stopLoss} {takeProfit} {leverage} {tradeMode}"], stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=True)
            with open("err_mariotersigni_pybybit.txt", "a") as err_mariotersigni_pybybit:
                err_mariotersigni_pybybit.write(str(mariotersigni_pybybit.communicate())+ "\n")
                # send_email('New Order', str(mariotersigni_pybybit.communicate()), sender, ['mariotersigni@gmail.com"'], password)

            sandrotersigni53_pybybit = subprocess.Popen([f"python3 sandrotersigni53_pybybit.py {symbol} {side} {qty} {price} {stopLoss} {takeProfit} {leverage} {tradeMode}"], stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=True)
            with open("err_sandrotersigni53_pybybit.txt", "a") as err_sandrotersigni53_pybybit:
                err_sandrotersigni53_pybybit.write(str(sandrotersigni53_pybybit.communicate())+ "\n")
                # send_email('New Order', str(sandrotersigni53_pybybit.communicate()), sender, ['sandrotersigni53@gmail.com"'], password)
        
client.start()
client.run_until_disconnected()