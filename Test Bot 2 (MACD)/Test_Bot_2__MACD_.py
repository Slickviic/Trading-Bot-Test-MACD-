import vectorbt as vbt
import pandas as pd
import pandas_ta as ta
from datetime import datetime
from alpaca_trade_api.rest import REST, TimeFrame
import Config

#Generate Alpaca REST
alpaca = REST(Config.API_KEY, Config.SECRET_KEY, 'https://paper-api.alpaca.markets')

#Account Information
account = alpaca.get_account()
account_size = float(account.cash)
risk_per_trade = .02

#Initialize position quantity
in_position_quantity = 0.0

positions = alpaca.list_positions()

if positions is not None:
    for position in positions:
        if position.asset_id == '64bbff51-59d6-4b3c-9351-13ad85e3c752':
            in_position_quantity += float(position.qty)

#Create pending orders list
pending_orders = {}

#Create file to log trades in
logfile = 'trade.log'

#Misc Trade Functions

def position_size(last_close, last_ema_60):
    dollar_risk = account_size * risk_per_trade
    trade_risk = (last_close - last_ema_60) / last_ema_60
    position_size_in_dollars = dollar_risk / trade_risk
    position_size_in_units = round(position_size_in_dollars / last_close, 2)
    return position_size_in_units

#API Communication Functions

def check_order_status():
    global in_position_quantity

    removed_order_ids = []

    print("{} - Checking order status".format(datetime.now().strftime('%y/%m/%d %H:%M:%S')))

    if len(pending_orders.keys()) > 0:
        for order_id in pending_orders:
            order = alpaca.get_order(order_id)

            if order.filled_at is not None:
                filled_message = "order to {} {} {} was filled {} at price {}\n".format(order.side, order.qty, order.symbol, order.filled_at, order.filled_avg_price)
                print(filled_message)
                with open(logfile, 'a') as f:
                    f.write(str(order))
                    f.write(filled_message)
            
                if order.side == 'buy':
                    in_position_quantity = float(order.qty)
                else:
                    in_position_quantity = 0

                removed_order_ids.append(order_id)
            else:
                print("Pending Order: Order has not been filled yet")

    for order_id in removed_order_ids:
        del pending_orders[order_id]

def send_order(symbol, quantity, side):
    print("{} - sending {} order".format(datetime.now().strftime('%y/%m/%d %H:%M:%S'), side))
    order = alpaca.submit_order(symbol, quantity, side, 'market')
    print(order)
    pending_orders[order.id] = order

#Order Condition Functions

def in_sr_zone_long(last_low, last_ema_30, last_ema_60):
    return last_low < last_ema_30 and last_low > last_ema_60

def above_htf_emas():
    #TODO: Get Higher Timeframe df and check if current low is above all EMAs
    return True

def profit_coeff(last_close, entry_price, stop_price, side):
    #TODO: TEST THIS
    if side == 'Long':
        pl_diff = last_close - entry_price
        sp_diff = entry_price - stop_price
        return abs( pl_diff / sp_diff )
    if side == 'Short':
        pl_diff = entry_price - last_close
        sp_diff = stop_price - entry_price
        return abs( pl_diff / sp_diff )

def long_buy_conditions(last_low, last_ema_30, last_ema_60, last_ema_365):

    buy_bool = False

    #Check if last low is in the MTF Support/Resistance Band
    if in_sr_zone_long(last_low, last_ema_30, last_ema_60):
        #Check if last low is greater than MTF 365 EMA
        if last_low > last_ema_365:
            #Check if last low is above HTF EMAs
            if above_htf_emas():
                buy_bool = True

    return buy_bool

def long_sell_conditions(last_close, last_ema_60):

    sell_bool = False

    if last_close < last_ema_60:
        sell = True

    return sell_bool

def check_conditions(df):

    #Store last indicator/price values
    last_close = df['Close'].iloc[-1]
    last_high = df['High'].iloc[-1]
    last_low = df['Low'].iloc[-1]
    last_macd = df['MACD Histogram'].iloc[-1]
    last_ema_30 = df['30 EMA'].iloc[-1]
    last_ema_60 = df['60 EMA'].iloc[-1]
    last_ema_365 = df['365 EMA'].iloc[-1]

    #Long Buy conditions
    if long_buy_conditions(last_low, last_ema_30, last_ema_60, last_ema_365):
        if in_position_quantity == 0:
            # buy
            qty = round((account_size * risk_per_trade) / last_close, 4)
            send_order('BTCUSD', qty, 'buy')
        else:
            print("== already in position, nothing to do ==")
    
    #Long Sell conditions
    #TODO: Add profit coefficient > 3 condition
    if long_sell_conditions(last_close, last_ema_60):
        if in_position_quantity > 0:
            # sell
            send_order('BTCUSD', in_position_quantity, 'sell')
        else:
            print("== You have nothing to sell ==")

#Data fill function

def get_bars():
    #Update User
    print("{} - getting bars".format(datetime.now().strftime('%y/%m/%d %H:%M:%S')))

    #Get data
    data = vbt.CCXTData.download(['BTCUSDT'], start='12 hours ago', timeframe='1m')

    df = data.get()

    #Generate Indicator Values
    macd = ta.macd(df['Close'])
    ema_30 = ta.ema(df['Close'], length = 30)
    ema_60 = ta.ema(df['Close'], length = 60)
    ema_365 = ta.ema(df['Close'], length = 365)

    #Store Indicator Values to Data Frame
    df["MACD Histogram"] = macd["MACDh_12_26_9"]
    df["30 EMA"] = ema_30
    df["60 EMA"] = ema_60
    df["365 EMA"] = ema_365
    
    #Pass Data Frame to check for stratagy conditions
    check_conditions(df)

    #Clean up unused data
    del macd
    del ema_30
    del ema_60
    del ema_365
    

#Initialize Vectorbt Scheduler
manager = vbt.ScheduleManager()

#Task: Check Order Status
manager.every().do(check_order_status)

#Task: Get Bars
manager.every().minute.at(':00').do(get_bars)

#Start Manager
manager.start()
