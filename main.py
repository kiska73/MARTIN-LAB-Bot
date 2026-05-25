import os
import time
import pandas as pd
from pybit.unified_trading import HTTP
from datetime import datetime, timezone

# ==========================================================
# CONFIG
# ==========================================================
API_KEY = os.environ.get("BYBIT_API_KEY")
API_SECRET = os.environ.get("BYBIT_API_SECRET")
SYMBOL = "LABUSDT"

session = HTTP(testnet=False, api_key=API_KEY, api_secret=API_SECRET)

current_mode = "AGGRESSIVE"
pause_until_next_candle = False
last_candle_ts = 0
last_trade_time = 0

GRID_SIZES = [2, 2, 2, 3, 4, 5, 6, 8, 10, 13, 16, 20, 25]

COOLDOWN = 20

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
        
        bb_width_percent = ((sma.iloc[-1] - lower_band.iloc[-1]) / sma.iloc[-1]) * 100
        
        return {
            'ts': df['ts'].iloc[-1],
            'bb_width': round(bb_width_percent, 2),
            'candle_low': round(df['low'].iloc[-1], 4),
            'lower_band': round(lower_band.iloc[-1], 4),
        }
    except Exception as e:
        print(f"Errore Kline: {e}")
        return None


def get_spacing(i, mode):
    """Fasce di spacing"""
    if mode == "AGGRESSIVE":
        if i <= 3:   return 1.0
        elif i <= 6: return 1.2
        elif i <= 9: return 1.5
        else:        return 1.8
    else:
        if i <= 3:   return 2.0
        elif i <= 6: return 2.4
        elif i <= 9: return 2.8
        else:        return 3.2


def should_check_candle():
    now_utc = datetime.now(timezone.utc)
    if now_utc.hour % 4 == 0 and now_utc.minute == 0 and 5 <= now_utc.second <= 25:
        return True
    return False


# ==========================================================
print("🚀 BOT MASTER - Griglia a Fasce Corretta + Pausa con Cancel")
print(f"Symbol: {SYMBOL} | Modalità iniziale: {current_mode}\n")

while True:
    try:
        now = time.time()
        price = get_current_price()

        # Posizione attuale
        pos = session.get_positions(category="linear", symbol=SYMBOL)["result"]["list"][0]
        size = float(pos["size"])
        avg_price = float(pos.get("avgPrice", 0))

        # Ordini attivi
        active_orders = session.get_open_orders(category="linear", symbol=SYMBOL)["result"]["list"]
        tp_orders = [o for o in active_orders if o["side"] == "Sell" and o["orderType"] == "Limit"]
        sl_orders = [o for o in active_orders if o.get("triggerPrice")]

        distance = 0.0

        # ==================== CONTROLLO CANDela 4H ====================
        if should_check_candle():
            vol_data = get_volatility_data(SYMBOL)
            if vol_data and vol_data['ts'] != last_candle_ts:
                print(f"📌 Candela 4H chiusa → {datetime.now().strftime('%H:%M:%S')}")

                # Cambio modalità
                new_mode = "CONSERVATIVE" if vol_data.get('bb_width', 0) > 40 else "AGGRESSIVE"
                if new_mode != current_mode:
                    print(f"🔄 CAMBIO MODALITÀ → {new_mode}")
                    current_mode = new_mode

                # Calcolo distanza dal Lower Band
                if price and vol_data.get('lower_band'):
                    distance = ((price - vol_data['lower_band']) / vol_data['lower_band']) * 100

                    if distance <= 3.0:
                        if not pause_until_next_candle:
                            print(f"⛔️ ATTIVAZIONE PAUSA - Prezzo troppo vicino al Lower Band ({distance:.2f}%)")
                            session.cancel_all_orders(category="linear", symbol=SYMBOL)
                            pause_until_next_candle = True
                    else:
                        if pause_until_next_candle:
                            print(f"✅ FINE PAUSA - Distanza tornata accettabile ({distance:.2f}%)")
                        pause_until_next_candle = False

                last_candle_ts = vol_data['ts']

        # ==================== GESTIONE POSIZIONE APERTA ====================
        if size > 0:
            tp_percent = 1.20 if current_mode == "CONSERVATIVE" else 0.90
            target_tp = round(avg_price * (1 + tp_percent/100), 4)
            
            if not tp_orders or abs(float(tp_orders[0]["price"]) - target_tp) > 0.0002:
                if tp_orders:
                    session.cancel_order(category="linear", symbol=SYMBOL, orderId=tp_orders[0]["orderId"])
                session.place_order(
                    category="linear", 
                    symbol=SYMBOL, 
                    side="Sell", 
                    orderType="Limit", 
                    qty=str(size), 
                    price=str(target_tp), 
                    reduceOnly=True
                )

        # ==================== NUOVA ENTRATA ====================
        elif size == 0 and (now - last_trade_time > COOLDOWN):
            if pause_until_next_candle:
                print(f"⏳ In pausa fino alla prossima candela 4H... (Distanza: {distance:.2f}%)")
            else:
                print(f"🧹 Nuova entrata in modalità {current_mode}")
                
                # Cancella tutto prima di entrare
                session.cancel_all_orders(category="linear", symbol=SYMBOL)
                time.sleep(1.5)

                # Market Buy iniziale
                session.place_order(
                    category="linear", 
                    symbol=SYMBOL, 
                    side="Buy", 
                    orderType="Market", 
                    qty=str(GRID_SIZES[0])
                )
                time.sleep(2.5)

                new_pos = session.get_positions(category="linear", symbol=SYMBOL)["result"]["list"][0]
                if float(new_pos["size"]) > 0:
                    avg = float(new_pos["avgPrice"])
                    print(f"✅ Entrata eseguita @ {avg:.4f} | Modalità: {current_mode}")

                    accumulated_drop = 0.0
                    for i in range(1, 13):
                        spacing = get_spacing(i, current_mode)
                        accumulated_drop += spacing
                        entry_price = round(avg * (1 - accumulated_drop / 100), 4)
                        qty = GRID_SIZES[i] if i < len(GRID_SIZES) else 15
                        
                        session.place_order(
                            category="linear", 
                            symbol=SYMBOL, 
                            side="Buy",
                            orderType="Limit", 
                            qty=str(qty), 
                            price=str(entry_price)
                        )
                    
                    last_trade_time = now

        time.sleep(5)

    except Exception as e:
        print(f"⚠️ Errore generale: {e}")
        time.sleep(10)
