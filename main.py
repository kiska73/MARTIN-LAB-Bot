import os
import time
import pandas as pd
from pybit.unified_trading import HTTP

# ==========================================================
# CONFIG
# ==========================================================
API_KEY = os.environ.get("BYBIT_API_KEY")
API_SECRET = os.environ.get("BYBIT_API_SECRET")
SYMBOL = "LABUSDT"

session = HTTP(testnet=False, api_key=API_KEY, api_secret=API_SECRET)

GRID_SIZES = [2, 2, 2, 2, 5, 7, 9, 11, 15, 20, 25, 30, 50]
COOLDOWN = 18 

# Stato globale
last_trade_time = 0
last_checked_candle_ts = 0

def get_bollinger_bands(symbol, period=40, std_dev=2):
    data = session.get_kline(category="linear", symbol=symbol, interval="240", limit=period + 2)
    df = pd.DataFrame(data['result']['list'], columns=['ts', 'open', 'high', 'low', 'close', 'vol', 'turnover'])
    df['close'] = df['close'].astype(float)
    df['low'] = df['low'].astype(float)
    df['ts'] = df['ts'].astype(int)
    
    sma = df['close'].rolling(window=period).mean()
    std = df['close'].rolling(window=period).std()
    lower_band = sma - (std * std_dev)
    return df['ts'].iloc[-2], lower_band.iloc[-2], df['low'].iloc[-2]

print("🚀 BOT AVVIATO - TP DINAMICO, SENTINELLA SL E EMERGENZA LIVE")

while True:
    try:
        now = time.time()
        # Ottieni posizione e prezzo attuale
        pos_list = session.get_positions(category="linear", symbol=SYMBOL)["result"]["list"]
        pos = pos_list[0]
        size = float(pos["size"])
        avg = float(pos["avgPrice"])
        
        ticker = session.get_tickers(category="linear", symbol=SYMBOL)["result"]["list"][0]
        current_price = float(ticker["lastPrice"])
        
        active_orders = session.get_open_orders(category="linear", symbol=SYMBOL)["result"]["list"]
        tp_orders = [o for o in active_orders if o["side"] == "Sell" and o["orderType"] == "Limit"]
        sl_orders = [o for o in active_orders if o["side"] == "Sell" and o["orderType"] == "Market" and "triggerPrice" in o]

        # 1. POSIZIONE APERTA
        if size > 0:
            ts, lower_band, last_low = get_bollinger_bands(SYMBOL)
            
            # --- A. CONTROLLO EMERGENZA (Chiusura immediata se sotto il minimo) ---
            if current_price <= last_low:
                print(f"🚨 EMERGENZA: Prezzo {current_price} <= Minimo {last_low}. Chiusura a mercato!")
                session.place_order(
                    category="linear", symbol=SYMBOL, side="Sell", orderType="Market",
                    qty=str(size), positionIdx=0, reduceOnly=True
                )
                last_trade_time = now
                time.sleep(2)
                continue

            # --- B. SL Sentinella (a chiusura candela 4H) ---
            if ts != last_checked_candle_ts:
                if now > (ts/1000 + 14400 + 3):
                    if last_low < lower_band and not sl_orders:
                        print(f"📉 Chiusura sotto banda! Imposto SL Sentinella a: {last_low}")
                        session.place_order(
                            category="linear", symbol=SYMBOL, side="Sell", orderType="Market",
                            qty=str(size), triggerPrice=str(round(last_low, 4)), 
                            triggerDirection="BelowPrice", triggerBy="LastPrice",
                            positionIdx=0, reduceOnly=True
                        )
                    last_checked_candle_ts = ts
            
            # --- C. TP Dinamico ---
            target_price = round(avg * 1.009, 4)
            if tp_orders:
                current_tp = float(tp_orders[0]["price"])
                if abs(current_tp - target_price) > 0.0001:
                    print(f"🔄 Aggiorno TP: {target_price}")
                    session.cancel_order(category="linear", symbol=SYMBOL, orderId=tp_orders[0]["orderId"])
                    session.place_order(category="linear", symbol=SYMBOL, side="Sell", 
                                        orderType="Limit", qty=str(size), price=str(target_price), 
                                        positionIdx=0, reduceOnly=True)
            else:
                session.place_order(category="linear", symbol=SYMBOL, side="Sell", 
                                    orderType="Limit", qty=str(target_price), price=str(target_price), 
                                    positionIdx=0, reduceOnly=True)
        
        # 2. POSIZIONE CHIUSA -> NUOVA ENTRATA
        elif size == 0 and (now - last_trade_time > COOLDOWN):
            print("🧹 Reset ciclo e nuova entrata")
            session.cancel_all_orders(category="linear", symbol=SYMBOL)
            session.place_order(category="linear", symbol=SYMBOL, side="Buy", orderType="Market", 
                                qty=str(GRID_SIZES[0]), positionIdx=0)
            time.sleep(2)
            
            new_pos = session.get_positions(category="linear", symbol=SYMBOL)["result"]["list"][0]
            if float(new_pos["size"]) > 0:
                avg = float(new_pos["avgPrice"])
                for i in range(1, len(GRID_SIZES)):
                    price = avg * (1 - (1.2 * i) / 100)
                    session.place_order(category="linear", symbol=SYMBOL, side="Buy", orderType="Limit", 
                                        qty=str(GRID_SIZES[i]), price=str(round(price, 4)), positionIdx=0)
                last_trade_time = now

        time.sleep(5) 

    except Exception as e:
        print(f"⚠️ Errore critico: {e}")
        time.sleep(10)
