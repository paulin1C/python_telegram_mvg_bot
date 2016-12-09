# coding=utf-8

import logging, os, time, subprocess, re, sys, time
sys.path.append('python_mvg_departures')
from datetime import *
from telegram import *
from telegram.ext import *
from mvg import *
import key, plans

plans = plans.plans
updater = Updater(key.key) #api key from file "key.py", create your's as shown in "key_sample.py"
timer = updater.job_queue
refresh = ([])

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)

logger = logging.getLogger(__name__)

def start(bot, update):
    bot.sendMessage(update.message.chat_id, text='Hallo, sende mir den Name einer Haltestelle oder teile deinen Standort, um die Abfahrten für eine Haltestelle zu sehen.\nBenutze /help um mehr Informationen zu erhalten (z.B. über die Routenplanung)')
    logger.info('start used by %s', update.message.from_user)

def help(bot, update):
    #bot.sendMessage(update.message.chat_id, text='This bot will send you the departure times of public transport stations in Munich (Germany).')
    bot.sendMessage(update.message.chat_id, text='sende mir den Name einer Haltestelle oder teile deinen Standort, um die Abfahrten für eine Haltestelle zu sehen.\n\nRouten können z.B. so geplant werden:\nMarienpaltz nach Obersendling um 20:00\noder\nOdensplatz nach Siemenswerke bis 21:00\noder\nTrudering nach Kreillerstraße\n\nFormel:\nfromStation [nach|to] toStation ([ab|um|bis|at|until] hh:mm)')
    logger.info('help used by %s', update.message.from_user)

def gps(bot, update):
    stations = get_nearby_stations(update.message.location.latitude, update.message.location.longitude)
    if stations == []:
        bot.sendMessage(update.message.chat_id, text='Keine Stationen in der Nähe gefunden')
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
            split = "station|split|"
            buttons[row].append(InlineKeyboardButton(name, callback_data=split+str(station_id)))
            row += 1
    bot.sendMessage(update.message.chat_id, text="Suche eine Station aus:\nName, Entfernung, Produkte", reply_markup=InlineKeyboardMarkup(buttons))
    logger.info('Sending %s gps station select buttons', update.message.from_user)

def buttonHandler(bot, update):
    update = update.callback_query
    response = update.data.split('|split|')
    dataType = response[0]
    data = response[1]
    if dataType == "station":
        sendDepsforStation(bot, update, data, update.message.message_id)
    elif dataType == "planBack":
        plan(bot, update, edit=True)
    elif dataType == "planCategoryId":
        sendPlanCategory(bot, update, int(data))
    elif dataType == "planPlanId":
        data = data.split('|wurst|')
        sendPlanPlan(bot, update, int(data[1]), int(data[0]))
    else:
        logger.error("Something went wrong with the buttonHandler, no matching dataType")

def msg(bot, update):
    #thanks to @uberardy for these regulare expressions
    pattern1 = "(?:von )?(.+) (nach|to) (.*)"
    pattern2 = "(?:von )?(.+) (nach|to) (.*)(?: (um|ab|bis|at|until) ([0-9]{1,2}:?[0-9]{2}))"
    text = update.message.text.encode('utf8')
    result1 = re.match(pattern1, text)
    if result1 == None:
        station = text
        sendDepsforStation(bot, update, station)
    else:
        result2 = re.match(pattern2, text)
        if result2 == None:
            result = result1
            b_time = False
        else:
            result = result2
            b_time = True
        sendRoutes(bot, update, result, b_time)

def idFromXY(bot, update, station_raw):
    try:
        station_id = int(station_raw)
    except(ValueError):
        station = get_stations(station_raw)[0]
        station_id = int(station['id'])
    return station_id

def nameFromXY(bot, update, station_raw):
    try:
        station_id = int(station_raw)
    except:
        station = get_stations(station_raw)[0]
        station_name = station['name']
    else:
        try:
            station_name = bodgeName(station_id)
        except(ValueError):
            station_name = "Id: "
            bot.sendMessage(update.message.chat_id, text='Leider gibt die MVG API keine Stationsnamen mehr für ids zurück.')
    return station_name

def bodgeName(from_id):
    for to_id in [6,5,10]:
        try:
            station_name = get_route(from_id, to_id)[0]['connectionPartList'][0]['from']['name']
        except:
            pass
        else:
            logger.info("Bodged name for %i with %i", from_id, to_id)
            return station_name
    raise(ValueError) #höhö

def sendDepsforStation(bot, update, station_raw, message_id = -1):
    if message_id > -1:
        from_user = update.from_user
        refresh = True
    else:
        from_user = update.message.from_user
        refresh = False
        try:
            station_name = nameFromXY(bot, update, station_raw)
            station_id = idFromXY(bot, update, station_raw)
        except:
            bot.sendMessage(update.message.chat_id, text="Station nicht gefunden :(")
            logger.warn('Not matching station name in deps used by %s', update.message.from_user)
        else:
            # station_name = "testname" #get_stations(station_id)[0]['name']
            departures = get_departures(station_id)
            if departures == []: #checking if there are deps for the station
                bot.editMessageText(chat_id=update.message.chat_id, text='Keine Abfahrten für diese Station', message_id=update.message.message_id)
                logger.info('No departures for %s, requested by %s', station_raw, from_user)
            else:
                logger.info('deps for %s (%s) to %s. Refresh = %s', station_id, station_name, from_user, refresh)

                now = datetime.datetime.now()
                header="minutes, service, destination"
                body = ""

                times=[]
                products=[]
                destinations=[]
                i=0
                for departure in departures:
                    len_dTM = len(str(departure['departureTimeMinutes']))
                    if not len_dTM > 3:
                        times.append(str(departure['departureTimeMinutes']))
                        product = build_label(departure['product'], departure['label'])
                        products.append(product)
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
                    body = "\n<i>Keine Abfahrt in den nächsten 999 Minuten</i>"
                else:
                    body="<code>" + body + "</code>\n"


                zeit = now.strftime("%H:%M:%S")

                buttons = []
                buttons.append([])
                now = datetime.datetime.now()
                split = "station|split|"
                buttons[0].append(InlineKeyboardButton(zeit + " - tap to refresh", callback_data=split+str(station_id)))
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

def sendRoutes(bot, update, result, b_time):
    # try:
        from_station_id = idFromXY(bot,update,result.group(1))
        to_station_id = idFromXY(bot,update,result.group(3))
    # except:
        # bot.sendMessage(update.message.chat_id, text="Station nicht gefunden :(")
        # logger.warn('Not matching station name in journeys used by %s', update.message.from_user)
    # else:
        arrival_time = False
        i_time = datetime_to_mvgtime(datetime.datetime.now())
        if b_time:
            if result.group(4) in ["bis","until"]:
                arrival_time = True
            try:
                i_time = datetime.datetime.combine(datetime.datetime.now(), datetime.datetime.strptime(result.group(5), "%H:%M").time())
            except:
                bot.sendMessage(update.message.chat_id, text="Zeit ungültig, bitte im Format hh:mm angeben\nAktuelle Zeit wird jetzt als Alternative verwendet")
                logger.warn('invalid time used by %s', update.message.from_user)
        route = get_route(from_station_id, to_station_id, i_time, arrival_time)

        msg = buildRouteMsg(route)

        bot.sendMessage(update.message.chat_id, text=msg, parse_mode=ParseMode.HTML)
        logger.info('journey from %s to %s sent to %s, b_time=%s', str(from_station_id), str(to_station_id), update.message.from_user, str(b_time))

def plan(bot, update, edit = False):
    """ Loop to test plans.py
    msg = "Test Planausgabe, wird noch zu buttons"
    for category in plans:
        msg += "\n" + str(category['category_id']) + ": "
        msg += category['name']
        for plan in category['content']:
            msg += "\n  "+str(plan['plan_id'])+": "
            msg += plan['name']
    bot.sendMessage(update.message.chat_id, text=msg)
    """

    split = "planCategoryId|split|"
    row = 0
    buttons = []
    for category in plans:
        buttons.append([])
        callback_data = split+str(category['category_id'])
        buttons[row].append(InlineKeyboardButton(category['name'], callback_data=callback_data))
        row += 1
    if edit:
        bot.editMessageText(chat_id=update.message.chat_id,  text="Wähle eine Kategorie aus:", reply_markup=InlineKeyboardMarkup(buttons), message_id=update.message.message_id)
        logger.info('Sending plan category select buttons to %s', update.from_user)
    else:
        logger.info('Sending plan category select buttons to %s', update.message.from_user)
        bot.sendMessage(update.message.chat_id, text="Wähle eine Kategorie aus:", reply_markup=InlineKeyboardMarkup(buttons))

def sendPlanCategory(bot, update, category_id):
    split = "planPlanId|split|"
    row = 0
    buttons = []
    category_name = plans[category_id]['name']
    for plan in plans[category_id]['content']:
        buttons.append([])
        callback_data = split+str(plan['plan_id'])+"|wurst|"+str(category_id)
        buttons[row].append(InlineKeyboardButton(plan['name'], callback_data=callback_data))
        row += 1
    buttons.append([])
    buttons[row].append(InlineKeyboardButton("< Zurück", callback_data="planBack|split|x"))
    bot.editMessageText(chat_id=update.message.chat_id, text="Wähle einen Plan ausd der Kategorie "+ category_name +":", reply_markup=InlineKeyboardMarkup(buttons), message_id=update.message.message_id)
    logger.info('Sending plan plan select buttons to %s', update.from_user)

def sendPlanPlan(bot, update, category_id, plan_id):
    file_id = plans[category_id]['content'][plan_id]['file_id']
    bot.editMessageText(chat_id=update.message.chat_id, text="Plan wird gesendet...", message_id=update.message.message_id)
    bot.send_document(update.message.chat_id, file_id)
    logger.info('Sending real plan select buttons to %s', update.from_user)

def buildRouteMsg(route):
    body=""
    counter=0
    for option in route:
        counter +=1
        body += "\n"
        body += "Option " + str(counter) + ":\n"
        # body += mvgtime_to_hrs(option['departure']) + " - " + option['from']['name'] + "\n"
        for part in option['connectionPartList']:
            body += mvgtime_to_hrs(part['departure']) + " - " + part['from']['name'] + "\n"
            if part['connectionPartType'] == "FOOTWAY":
                # lat = str(part['to']['latitude'])
                # lon = str(part['to']['longitude'])
                # station_name = part['to']['name']
                # link = MessageEntity("url", 20, str("geo:"+lat+","+lon))
                # bot.sendMessage(159521737, text=link)
                body += u"      walk to station\n"
            else:
                body += "      " + build_label(part['product'], part['label']) + " " + part['destination'] + "\n"
            body += mvgtime_to_hrs(part['arrival']) + " - " + part['to']['name'] + "\n"
        # body += mvgtime_to_hrs(option['arrival']) + " - " + option['to']['name'] + "\n"
    msg=body

    return msg

def build_label(part1,part2):
    service = {'t': "", 'u': "U", 'b': "", 's': "S"}
    try:
        label = service[part1]
    except:
        label = part1
    label += str(part2)
    return label

def escape_markdown(text):
    """Helper function to escape telegram markup symbols"""
    escape_chars = '\*_`\['
    return re.sub(r'([%s])' % escape_chars, r'\\\1', text)

def addspaces(n, string=""):
    while n > 0:
        string=string+" "
        n=n-1
    return string

def wasistdas(bdaot, update):
    bot.sendMessage(update.message.chat_id, text='All stations have unique station ids. They can be used instead of a station name. For example, you can write 5 instead of Ostbahnhof.')
    logger.info('wasistdas used by %s', update.message.from_user)

def mvgtime_to_hrs(time):
    time = datetime.datetime.fromtimestamp(time/1000).strftime("%H:%M")
    return time

def datetime_to_mvgtime(dtime):
    time = int(dtime.strftime("%s"))*1000
    return time

def error(bot, update, error):
    logger.warn('Update "%s" caused error "%s"' % (update, error))

def main():

    dp = updater.dispatcher #not double penetration

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("plan", plan))
    dp.add_handler(CommandHandler("Wasistdas", wasistdas))
    dp.add_handler(CommandHandler("help", help))
    dp.add_handler(MessageHandler([Filters.location], gps))
    dp.add_handler(MessageHandler([Filters.text], msg))
    dp.add_handler(CallbackQueryHandler(buttonHandler))

    dp.add_error_handler(error)

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
