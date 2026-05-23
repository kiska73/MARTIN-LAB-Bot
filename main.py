import os
import time
import pandas as pd
from pybit.unified_trading import HTTP
from datetime import datetime

# ==========================================================
# CONFIG MASTER + MODALITÀ VOLATILITÀ
# ==========================================================
API_KEY = os.environ.get("BYBIT_API_KEY")
API_SECRET = os.environ.get("BYBIT_API_SECRET")
SYMBOL = "LABUSDT"

session = HTTP(testnet=False, api_key=API_KEY, api_secret=API_SECRET)

# ==================== MODALITÀ ====================
current_mode = "AGGRESSIVE"   # Default

# Modalità Aggressiva (quella che usavi prima)
AGGRESSIVE_GRID = [2, 2, 2, 3, 5, 7, 9, 11, 15, 20, 30, 45]
AGGRESSIVE_TP = 0.90
AGGRESSIVE_SPACING = 1.25   # %

# Modalità Conservativa (come hai chiesto)
CONSERVATIVE_QTY = 3
CONSERVATIVE_LEVELS = 20
CONSERVATIVE_SPACING = 1.50   # %
CONSERVATIVE_TP = 1.20

COOLDOWN = 18
last_candle_ts = 0
last_trade_time = 0

def get_current_price():
    try:
        ticker = session.get_tickers(category="linear", symbol=SYMBOL)
        return float(ticker['result']['list'][0]['lastPrice'])
    except:
        return None

def get_volatility_data(symbol):
    try:
        data = session.get_kline(category="linear", symbol=symbol, interval="240", limit=42)
        df = pd.DataFrame(data['result']['list'], columns=['ts', 'open', 'high', 'low', 'close', 'vol', 'turnover'])
        
        df['close'] = df['close'].astype(float)
        df['low'] = df['low'].astype(float)
        df['ts'] = df['ts'].astype(int)
        
        sma = df['close'].rolling(window=40).mean()
        std = df['close'].rolling(window=40).std()
        lower_band = sma - (std * 2)
        
        # Calcolo larghezza Bollinger in % rispetto alla SMA
        bb_width_percent = ((sma.iloc[-1] - lower_band.iloc[-1]) / sma.iloc[-1]) * 100   # Distanza Lower Band da SMA
        
        return {
            'ts': df['ts'].iloc[-1],
            'bb_width': round(bb_width_percent, 2),
            'candle_low': round(df['low'].iloc[-1], 4),
            'candle_close_time': df['ts'].iloc[-1] / 1000 + 14400,
            'sma': round(sma.iloc[-1], 4)
        }
    except Exception as e:
        print(f"Errore Volatilità: {e}")
        return None


print("🚀 BOT MASTER + MODALITÀ VOLATILITÀ ATTIVATO")

while True:
    try:
        now = time.time()
        price = get_current_price()

        pos = session.get_positions(category="linear", symbol=SYMBOL)["result"]["list"][0]
        size = float(pos["size"])
        avg_price = float(pos.get("avgPrice", 0))

        active_orders = session.get_open_orders(category="linear", symbol=SYMBOL)["result"]["list"]
        tp_orders = [o for o in active_orders if o["side"] == "Sell" and o["orderType"] == "Limit"]
        sl_orders = [o for o in active_orders if o.get("triggerPrice")]

        # ==================== CALCOLO VOLATILITÀ & CAMBIO MODALITÀ ====================
        vol_data = get_volatility_data(SYMBOL)
        
        if vol_data and vol_data['ts'] != last_candle_ts:
            if now > vol_data['candle_close_time'] + 6:
                bb_width = vol_data['bb_width']
                
                if bb_width > 30:
                    new_mode = "CONSERVATIVE"
                else:
                    new_mode = "AGGRESSIVE"
                
                if new_mode != current_mode:
                    print(f"🔄 CAMBIO MODALITÀ → {new_mode} (BB Width: {bb_width}%)")
                    current_mode = new_mode
                
                last_candle_ts = vol_data['ts']

        # ==================== POSIZIONE APERTA ====================
        if size > 0:
            # SL SENTINELLA
            if vol_data and vol_data['candle_low'] < vol_data['sma'] * 0.96:
                if price and price <= vol_data['candle_low'] * 0.997:
                    print(f"🚨 FLASH CRASH → Chiusura immediata")
                    session.place_order(category="linear", symbol=SYMBOL, side="Sell", 
                                      orderType="Market", qty=str(size), reduceOnly=True)
                elif not sl_orders:
                    print(f"📉 SL Sentinella @ {vol_data['candle_low']}")
                    session.place_order(
                        category="linear", symbol=SYMBOL, side="Sell", orderType="Market",
                        qty=str(size), triggerPrice=str(vol_data['candle_low']),
                        triggerDirection=2, triggerBy="LastPrice", reduceOnly=True
                    )

            # TP DINAMICO
            tp_percent = CONSERVATIVE_TP if current_mode == "CONSERVATIVE" else AGGRESSIVE_TP
            target_tp = round(avg_price * (1 + tp_percent/100), 4)
            
            if tp_orders:
                if abs(float(tp_orders[0]["price"]) - target_tp) > 0.0002:
                    session.cancel_order(category="linear", symbol=SYMBOL, orderId=tp_orders[0]["orderId"])
                    session.place_order(category="linear", symbol=SYMBOL, side="Sell",
                                      orderType="Limit", qty=str(size), price=str(target_tp), reduceOnly=True)
            else:
                session.place_order(category="linear", symbol=SYMBOL, side="Sell",
                                  orderType="Limit", qty=str(size), price=str(target_tp), reduceOnly=True)

        # ==================== NUOVA ENTRATA ====================
        elif size == 0 and (now - last_trade_time > COOLDOWN):
            print(f"🧹 Nuova entrata in modalità {current_mode}")
            session.cancel_all_orders(category="linear", symbol=SYMBOL)
            time.sleep(1.2)

            if current_mode == "CONSERVATIVE":
                entry_qty = CONSERVATIVE_QTY
                spacing = CONSERVATIVE_SPACING
                max_levels = CONSERVATIVE_LEVELS
            else:
                entry_qty = AGGRESSIVE_GRID[0]
                spacing = AGGRESSIVE_SPACING
                max_levels = 12

            # Entrata iniziale
            session.place_order(category="linear", symbol=SYMBOL, side="Buy", 
                              orderType="Market", qty=str(entry_qty))
            
            time.sleep(2.5)
            
            new_pos = session.get_positions(category="linear", symbol=SYMBOL)["result"]["list"][0]
            if float(new_pos["size"]) > 0:
                avg = float(new_pos["avgPrice"])
                print(f"✅ Entrata @ {avg:.4f} | Modalità: {current_mode}")

                # Piazza la grid
                for i in range(1, max_levels):
                    entry_price = round(avg * (1 - (spacing * i) / 100), 4)
                    qty = CONSERVATIVE_QTY if current_mode == "CONSERVATIVE" else AGGRESSIVE_GRID[i] if i < len(AGGRESSIVE_GRID) else 10
                    
                    session.place_order(
                        category="linear", symbol=SYMBOL, side="Buy",
                        orderType="Limit", qty=str(qty), price=str(entry_price)
                    )
                
                last_trade_time = now

        time.sleep(5)

    except Exception as e:
        print(f"⚠️ Errore: {e}")
        time.sleep(10)
