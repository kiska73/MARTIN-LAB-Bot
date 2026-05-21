import os
import time
from pybit.unified_trading import HTTP

# =====================================================================
# CONFIGURAZIONE (La tua originale)
# =====================================================================
API_KEY = os.environ.get("BYBIT_API_KEY")
API_SECRET = os.environ.get("BYBIT_API_SECRET")
SYMBOL = "LABUSDT"
SOGLIA_SL = -0.16 

session = HTTP(
    testnet=False,
    demo=True,
    api_key=API_KEY,
    api_secret=API_SECRET
)

GRID_SIZES = [2, 2, 2, 2, 5, 7, 9, 11, 15, 20, 25, 30, 50] 
SIZE_LIVELLO_1 = GRID_SIZES[0]
RESTANTI_LIVELLI = GRID_SIZES[1:]
ratio_volatilità = 0.73

# =====================================================================
# FUNZIONI
# =====================================================================

def recupera_stato_posizione():
    try:
        response = session.get_positions(category="linear", symbol=SYMBOL)
        if response and "list" in response["result"] and len(response["result"]["list"]) > 0:
            pos = response["result"]["list"][0]
            return float(pos.get("size", 0)), float(pos.get("avgPrice", 0))
    except: pass
    return 0.0, 0.0

def aggiorna_tp_limit_chirurgico(size_posizione, quota_tp):
    try:
        ordini = session.get_open_orders(category="linear", symbol=SYMBOL)["result"]["list"]
        for o in ordini:
            if o["side"] == "Sell":
                session.cancel_order(category="linear", symbol=SYMBOL, orderId=o["orderId"])
    except: pass
        
    if size_posizione > 0:
        session.place_order(
            category="linear", symbol=SYMBOL, side="Sell",
            orderType="Limit", qty=str(size_posizione),
            price=str(round(quota_tp, 4)),
            positionIdx=0, reduceOnly=True
        )

# =====================================================================
# CICLO PRINCIPALE
# =====================================================================

ultima_size_tracciata = -1.0 
prezzo_ingresso_iniziale = 0.0 # Per tenere fisso lo SL

print("🚀 BOT IN ESECUZIONE (Griglia originale + SL -16% fisso)...")

while True:
    try:
        size_attuale, prezzo_medio = recupera_stato_posizione()
        
        # 0. MONITORAGGIO CONTINUO SL (Sempre attivo)
        if size_attuale > 0 and prezzo_ingresso_iniziale > 0:
            ticker = session.get_tickers(category="linear", symbol=SYMBOL)
            prezzo_corrente = float(ticker["result"]["list"][0]["lastPrice"])
            pnl_perc = (prezzo_corrente / prezzo_ingresso_iniziale) - 1
            
            if pnl_perc <= SOGLIA_SL:
                print(f"🚨 SL -16% RAGGIUNTO! Chiusura Market.")
                session.place_order(category="linear", symbol=SYMBOL, side="Sell", 
                                    orderType="Market", qty=str(size_attuale), positionIdx=0, reduceOnly=True)
                ultima_size_tracciata = -1.0
                prezzo_ingresso_iniziale = 0.0
                continue

        # 1. Se la size cambia (nuovo livello preso)
        if size_attuale > 0 and size_attuale != ultima_size_tracciata:
            nuovo_tp = prezzo_medio * (1 + ratio_volatilità / 100)
            aggiorna_tp_limit_chirurgico(size_attuale, nuovo_tp)
            ultima_size_tracciata = size_attuale
            
        # 2. Se siamo a zero, resetta e piazza TUTTO
        elif size_attuale == 0 and ultima_size_tracciata != 0:
            print("🧹 Reset completo: piazzamento massivo...")
            try: session.cancel_all_orders(category="linear", symbol=SYMBOL)
            except: pass
            
            session.place_order(category="linear", symbol=SYMBOL, side="Buy", 
                                orderType="Market", qty=str(SIZE_LIVELLO_1), positionIdx=0)
            
            time.sleep(3)
            s_nuova, p_ingresso = recupera_stato_posizione()
            
            if s_nuova > 0:
                prezzo_ingresso_iniziale = p_ingresso # Fissiamo il punto per lo SL
                for i, size in enumerate(RESTANTI_LIVELLI):
                    prezzo_livello = p_ingresso * (1 - (ratio_volatilità * (i + 1)) / 100)
                    session.place_order(category="linear", symbol=SYMBOL, side="Buy", 
                                        orderType="Limit", qty=str(size), price=str(round(prezzo_livello, 4)), positionIdx=0)
                
                tp_iniziale = p_ingresso * (1 + ratio_volatilità / 100)
                aggiorna_tp_limit_chirurgico(s_nuova, tp_iniziale)
                ultima_size_tracciata = s_nuova
                print("✅ Ciclo ripartito.")

        time.sleep(3)
    except Exception as e:
        print(f"⚠️ Errore: {e}")
        time.sleep(5)
