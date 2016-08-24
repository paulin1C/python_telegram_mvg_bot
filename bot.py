# coding=utf-8

import logging, os, time, subprocess, re, sys
sys.path.append('python_mvg_departures')
from datetime import *
from telegram import *
from telegram.ext import *
from mvg import *
import key

updater = Updater(key.key) #api key from file "key.py", create your's as shown in "key_sample.py"
timer = updater.job_queue
refresh = ([])

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)

logger = logging.getLogger(__name__)

def start(bot, update):
    bot.sendMessage(update.message.chat_id, text='Hi, send me the name of a public transport station or just share your location.')
    logger.info('start used by %s', update.message.from_user)

def help(bot, update):
    bot.sendMessage(update.message.chat_id, text='This bot will send you the departure times of public transport stations in Munich (Germany).')
    bot.sendMessage(update.message.chat_id, text='Just share your location and select a nearby station or send the name of the station.')
    logger.info('help used by %s', update.message.from_user)

def gps(bot, update):
    stations = get_nearby_stations(update.message.location.latitude, update.message.location.longitude)
    if stations == []:
        bot.sendMessage(update.message.chat_id, text='No nearby station found')
        logger.info('No station found near %s', update.message.from_user)
    else:
        row = 0
        buttons = []
        for station in stations:
            buttons.append([])
            service = {'t': "Tram", 'u': "U-Bahn", 'b': "Bus", 's': "S-Bahn"}
            products=""
            count = 0
            for product in station['products']:
                spacing = ""
                if count > 0:
                    spacing = ", "
                try:
                    products = products + spacing + service[product]
                except:
                    products = products+  ", " + product
                count += 1
            products = "(" + products + ")"
            name =  station['name'] + "  " + str(station['distance']) + "m  "+ products
            station_id = station['id']
            buttons[row].append(InlineKeyboardButton(name, callback_data=str(station_id)))
            row += 1
    bot.sendMessage(update.message.chat_id, text="Select a station\nname, distance, services", reply_markup=InlineKeyboardMarkup(buttons))
    logger.info('Sending %s gps station select buttons', update.message.from_user)

def gps_answer(bot, update):
    update = update.callback_query
    station_id_str = update.data

    sendDepsforStation(bot, update, station_id_str, update.message.message_id)

def msg(bot, update):
    station = update.message.text
    sendDepsforStation(bot, update, station)

def sendDepsforStation(bot, update, station_raw, message_id = -1):
    if message_id > -1:
        from_user = update.from_user
        refresh = True
    else:
        from_user = update.message.from_user
        refresh = False

    try: #checking if station exists
        station_id = get_id_for_station(station_raw.encode('utf8'))
        station = Station(station_id)
    except:
        bot.sendMessage(update.message.chat_id, text='No matching station found.')
        logger.info('Not matching station name sent by: %s', from_user)
    else:
        station_name = get_station(station_id)['name']
        departures = station.get_departures()
        if departures == []: #checking if there are deps for the station
            bot.editMessageText(chat_id=update.message.chat_id, text='At the moment there seem to be no departures for this station :(', message_id=update.message.message_id)
            logger.info('No departures for %s, requested by %s', station_raw, from_user)
        else:
            logger.info('deps for %s (%s) to %s. Refresh = %s', station_id, station_name, from_user, refresh)

            now = datetime.datetime.now()
            header="minutes, service, destination"
            body = ""
            service = {'t': "", 'u': "U", 'b': "", 's': "S"}

            times=[]
            products=[]
            destinations=[]
            i=0
            for departure in departures:
                len_dTM = len(str(departure['departureTimeMinutes']))
                if not len_dTM > 3:
                    times.append(str(departure['departureTimeMinutes']))
                    try:
                        product = service[departure['product']]
                    except:
                        product = departure['product']
                    products.append(product+str(departure['label']))
                    destinations.append(departure['destination'])
                    i=i+1

            maxlen={}
            maxlen['times'] = max(len(s) for s in times)
            maxlen['products'] = max(len(s) for s in products)
            maxlen['destinations'] = max(len(s) for s in destinations)
            if maxlen['destinations'] > 18:
                maxlen['destinations'] = 18

            c = 0
            while(i > 0):
                row=products[c]
                row=addspaces(maxlen['products']-len(products[c])+1, row)
                if len(destinations[c]) > 18:
                    row1 = destinations[c][:18] + "\n"
                    row2 = addspaces(maxlen['products']+1)
                    row2 = row2 + destinations[c][18:]
                    row2 = addspaces(maxlen['destinations']-len(destinations[c][18:])+1, row2)
                    row = row + row1 + row2
                else:
                    row=row+destinations[c]
                    row=addspaces(maxlen['destinations']-len(destinations[c])+1,row)
                row=row+times[c]
                body=body+"\n"+row
                i=i-1
                c=c+1

            if body == "":
                body = "\n<i>No departures in the next 999 minutes</i>"
            else:
                body="<code>" + body + "</code>\n"


            zeit = now.strftime("%H:%M:%S")

            buttons = []
            buttons.append([])
            now = datetime.datetime.now()
            buttons[0].append(InlineKeyboardButton(zeit + " - tap to refresh", callback_data=str(station_id)))
            reply_markup=InlineKeyboardMarkup(buttons)

            station_name = "<b>"+station_name+"</b>"
            station_id_text = "("+str(station_id)+")"

            msg=station_name+" "+station_id_text+" "+body

            if refresh:
                try:
                    bot.editMessageText(chat_id=update.message.chat_id, text=msg, message_id=message_id, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
                except:
                    bot.sendMessage(update.message.chat_id, text="Stop spamming!")
                    logger.warn('User used refresh more than once per second: %s' % (from_user))
            else:
                bot.sendMessage(update.message.chat_id, text=msg, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

def escape_markdown(text):
    """Helper function to escape telegram markup symbols"""
    escape_chars = '\*_`\['
    return re.sub(r'([%s])' % escape_chars, r'\\\1', text)

def addspaces(n, string=""):
    while n > 0:
        string=string+" "
        n=n-1
    return string

def wasistdas(bot, update):
    bot.sendMessage(update.message.chat_id, text='All stations have unique station ids. They can be used instead of a station name. For example, you can write 5 instead of Ostbahnhof.')
    logger.info('wasistdas used by %s', update.message.from_user)

def error(bot, update, error):
    logger.warn('Update "%s" caused error "%s"' % (update, error))

def main():

    dp = updater.dispatcher #not double penetration

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("Wasistdas", wasistdas))
    dp.add_handler(CommandHandler("help", help))
    dp.add_handler(MessageHandler([Filters.location], gps))
    dp.add_handler(MessageHandler([Filters.text], msg))
    dp.add_handler(CallbackQueryHandler(gps_answer))

    dp.add_error_handler(error)

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
