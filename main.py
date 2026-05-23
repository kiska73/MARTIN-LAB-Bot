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

# Inizializzazione sessione
session = HTTP(testnet=False, api_key=API_KEY, api_secret=API_SECRET)

GRID_SIZES = [2, 2, 2, 2, 5, 7, 9, 11, 15, 20, 25, 30, 50]
COOLDOWN = 10 

# Stato globale
last_trade_time = 0
last_checked_candle_ts = 0

def get_bollinger_bands(symbol, period=40, std_dev=2):
    # Recupera ultime 42 candele 4H (240 min)
    data = session.get_kline(category="linear", symbol=symbol, interval="240", limit=period + 2)
    df = pd.DataFrame(data['result']['list'], columns=['ts', 'open', 'high', 'low', 'close', 'vol', 'turnover'])
    df['close'] = df['close'].astype(float)
    df['low'] = df['low'].astype(float)
    df['ts'] = df['ts'].astype(int)
    
    sma = df['close'].rolling(window=period).mean()
    std = df['close'].rolling(window=period).std()
    lower_band = sma - (std * std_dev)
    
    # Restituisce: [0] ts ultima chiusa, [1] banda, [2] minimo candela chiusa
    return df['ts'].iloc[-2], lower_band.iloc[-2], df['low'].iloc[-2]

def has_open_tp(symbol):
    orders = session.get_open_orders(category="linear", symbol=symbol, side="Sell")
    return len(orders["result"]["list"]) > 0

print("🚀 BOT AVVIATO - MONITORAGGIO 4H ATTIVO")

while True:
    try:
        now = time.time()
        # Ottieni posizione
        pos_data = session.get_positions(category="linear", symbol=SYMBOL)["result"]["list"][0]
        size = float(pos_data["size"])
        avg = float(pos_data["avgPrice"])
        
        # 1. POSIZIONE APERTA
        if size > 0:
            # Controllo SL a chiusura candela 4H
            ts, lower_band, last_low = get_bollinger_bands(SYMBOL)
            
            # Se la candela è chiusa (ts diverso dal precedente) e sono passati 3 secondi
            if ts != last_checked_candle_ts:
                if now > (ts/1000 + 14400 + 3):
                    if last_low < lower_band:
                        print(f"🚨 SL TRIGGERED! Minimo {last_low} < Banda {round(lower_band, 4)}")
                        session.cancel_all_orders(category="linear", symbol=SYMBOL)
                        session.place_order(category="linear", symbol=SYMBOL, side="Sell", 
                                            orderType="Market", qty=str(size), positionIdx=0, reduceOnly=True)
                    last_checked_candle_ts = ts
            
            # Gestione TP (se non c'è, lo piazza)
            if not has_open_tp(SYMBOL):
                session.place_order(category="linear", symbol=SYMBOL, side="Sell", 
                                    orderType="Limit", qty=str(size), price=str(round(avg * 1.009, 4)), 
                                    positionIdx=0, reduceOnly=True)
        
        # 2. POSIZIONE CHIUSA -> NUOVA ENTRATA
        elif size == 0 and (now - last_trade_time > COOLDOWN):
            print("🧹 Nuovo ciclo di ingresso")
            session.cancel_all_orders(category="linear", symbol=SYMBOL)
            
            # Entry Market
            session.place_order(category="linear", symbol=SYMBOL, side="Buy", orderType="Market", 
                                qty=str(GRID_SIZES[0]), positionIdx=0)
            time.sleep(2)
            
            # Aggiorna avg prezzo dopo entry
            pos_data = session.get_positions(category="linear", symbol=SYMBOL)["result"]["list"][0]
            if float(pos_data["size"]) > 0:
                avg = float(pos_data["avgPrice"])
                for i in range(1, len(GRID_SIZES)):
                    price = avg * (1 - (1.2 * i) / 100)
                    session.place_order(category="linear", symbol=SYMBOL, side="Buy", orderType="Limit", 
                                        qty=str(GRID_SIZES[i]), price=str(round(price, 4)), positionIdx=0)
                last_trade_time = now

        time.sleep(5) 

    except Exception as e:
        print(f"⚠️ Errore critico: {e}")
        time.sleep(10)
