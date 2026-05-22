import os
import time
from pybit.unified_trading import HTTP

# =====================================================================
# CONFIGURAZIONE
# =====================================================================
API_KEY = os.environ.get("BYBIT_API_KEY")
API_SECRET = os.environ.get("BYBIT_API_SECRET")
SYMBOL = "LABUSDT"

session = HTTP(testnet=False, demo=False, api_key=API_KEY, api_secret=API_SECRET)
GRID_SIZES_STANDARD = [2, 2, 2, 2, 5, 7, 9, 11, 15, 20, 25, 30, 50]

# =====================================================================
# FUNZIONI DI SUPPORTO
# =====================================================================
def get_config_volatilita():
    try:
        klines = session.get_kline(category="linear", symbol=SYMBOL, interval="240", limit=21)
        data = klines["result"]["list"]
        h_last, l_last = float(data[0][2]), float(data[0][3])
        vol_last = (h_last - l_last) / l_last
        ranges = [(float(k[2]) - float(k[3])) / float(k[3]) for k in data[1:]]
        vol_avg = sum(ranges) / len(ranges)
        return [2] * 13 if vol_last > (vol_avg * 1.5) else GRID_SIZES_STANDARD
    except: return GRID_SIZES_STANDARD

def get_bollinger_banda_inf_4h():
    try:
        klines = session.get_kline(category="linear", symbol=SYMBOL, interval="240", limit=20)
        closes = [float(k[4]) for k in klines["result"]["list"]]
        media = sum(closes) / len(closes)
        std_dev = (sum([(x - media)**2 for x in closes]) / len(closes))**0.5
        return media - (2 * std_dev)
    except: return 0.0

def recupera_stato_posizione():
    try:
        response = session.get_positions(category="linear", symbol=SYMBOL)
        if response and "list" in response["result"]:
            for pos in response["result"]["list"]:
                if float(pos.get("size", 0)) > 0:
                    return float(pos["size"]), float(pos["avgPrice"])
    except: pass
    return 0.0, 0.0

def aggiorna_tp_limit_chirurgico(size, tp):
    # Cancella solo i Sell, non tutti gli ordini, per evitare di segare i Buy della griglia!
    try:
        ordini = session.get_open_orders(category="linear", symbol=SYMBOL)["result"]["list"]
        for o in ordini:
            if o["side"] == "Sell": 
                session.cancel_order(category="linear", symbol=SYMBOL, orderId=o["orderId"])
        
        if size > 0:
            session.place_order(category="linear", symbol=SYMBOL, side="Sell", orderType="Limit", 
                                qty=str(size), price=str(round(tp, 4)), positionIdx=0, reduceOnly=True)
    except: pass

# =====================================================================
# CICLO PRINCIPALE
# =====================================================================
ultima_size = -1.0
prezzo_ingresso = 0.0
ultimo_trade_time = 0 

print("🚀 BOT LIVE AVVIATO (Versione Anti-Cancellazione)")

while True:
    try:
        size, avg_price = recupera_stato_posizione()
        
        # 1. LOGICA SL (Solo se abbiamo una size reale)
        if size > 0:
            ticker = session.get_tickers(category="linear", symbol=SYMBOL)
            prezzo = float(ticker["result"]["list"][0]["lastPrice"])
            
            # Se siamo entrati ora, inizializziamo prezzo ingresso
            if prezzo_ingresso == 0: prezzo_ingresso = avg_price

            klines = session.get_kline(category="linear", symbol=SYMBOL, interval="240", limit=2)
            low_candela = float(klines["result"]["list"][1][3])
            banda_inf = get_bollinger_banda_inf_4h()
            pnl = (prezzo / prezzo_ingresso) - 1
            
            if (prezzo < banda_inf and prezzo <= low_candela) or pnl <= -0.60:
                print("🚨 SL INNESCATO")
                session.place_order(category="linear", symbol=SYMBOL, side="Sell", orderType="Market", qty=str(size), positionIdx=0, reduceOnly=True)
                ultima_size = -1.0
                prezzo_ingresso = 0.0
                ultimo_trade_time = time.time()
                time.sleep(15)
                continue

            # Aggiornamento TP chirurgico (solo se la size cambia)
            if size != ultima_size:
                aggiorna_tp_limit_chirurgico(size, avg_price * 1.007)
                ultima_size = size

        # 2. APERTURA GRIGLIA (Solo se siamo flat)
        elif size == 0 and ultima_size != 0:
            if (time.time() - ultimo_trade_time) < 20: # Aumentato a 20s per sicurezza
                time.sleep(5)
                continue
                
            print("🧹 Analisi nuova griglia...")
            lista_sizes = get_config_volatilita()
            
            # Non cancellare tutto a caso! Cancella solo se strettamente necessario
            session.place_order(category="linear", symbol=SYMBOL, side="Buy", orderType="Market", qty=str(lista_sizes[0]), positionIdx=0)
            ultimo_trade_time = time.time()
            time.sleep(5)
            
            # Recupera nuova size post-market order
            s_nuova, p_ing = recupera_stato_posizione()
            if s_nuova > 0:
                prezzo_ingresso = p_ing
                for i in range(1, len(lista_sizes)):
                    prezzo_livello = p_ing * (1 - (1.2 * i) / 100)
                    session.place_order(category="linear", symbol=SYMBOL, side="Buy", orderType="Limit", qty=str(lista_sizes[i]), price=str(round(prezzo_livello, 4)), positionIdx=0)
                aggiorna_tp_limit_chirurgico(s_nuova, p_ing * 1.007)
                ultima_size = s_nuova

        time.sleep(5)
    except Exception as e:
        print(f"⚠️ Errore: {e}")
        time.sleep(10)
