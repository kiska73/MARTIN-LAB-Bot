import os
import time
from pybit.unified_trading import HTTP

# =====================================================================
# CONFIGURAZIONE
# =====================================================================
API_KEY = os.environ.get("BYBIT_API_KEY")
API_SECRET = os.environ.get("BYBIT_API_SECRET")
SYMBOL = "LABUSDT"
TP_LINK_ID = "TP_ORDER_MASTER"
SOGLIA_SL = -0.16 # Stop Loss fisso a -16%

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
            orderLinkId=TP_LINK_ID, positionIdx=0, reduceOnly=True
        )

# =====================================================================
# CICLO PRINCIPALE
# =====================================================================

ultima_size_tracciata = -1.0 
print("🚀 BOT ATTIVO: Protezione SL -16% abilitata.")

while True:
    try:
        size_attuale, prezzo_medio = recupera_stato_posizione()
        
        if size_attuale > 0:
            # 1. CONTROLLO STOP LOSS (-16%)
            ticker = session.get_tickers(category="linear", symbol=SYMBOL)
            prezzo_attuale = float(ticker["result"]["list"][0]["lastPrice"])
            pnl_perc = (prezzo_attuale / prezzo_medio) - 1
            
            if pnl_perc <= SOGLIA_SL:
                print(f"🚨 STOP LOSS RAGGIUNTO ({pnl_perc:.2%})! Chiusura immediata.")
                session.place_order(category="linear", symbol=SYMBOL, side="Sell", 
                                    orderType="Market", qty=str(size_attuale), positionIdx=0, reduceOnly=True)
                time.sleep(10) # Pausa per resettare tutto
                ultima_size_tracciata = -1.0
                continue

            # 2. Aggiornamento dinamico TP
            if size_attuale != ultima_size_tracciata:
                nuovo_tp = prezzo_medio * (1 + ratio_volatilità / 100)
                aggiorna_tp_limit_chirurgico(size_attuale, nuovo_tp)
                ultima_size_tracciata = size_attuale
            
        # 3. Reset e avvio nuovo ciclo
        elif size_attuale == 0 and ultima_size_tracciata != 0:
            print("🧹 Reset ciclo: piazzamento massivo...")
            try: session.cancel_all_orders(category="linear", symbol=SYMBOL)
            except: pass
            
            session.place_order(category="linear", symbol=SYMBOL, side="Buy", 
                                orderType="Market", qty=str(SIZE_LIVELLO_1), positionIdx=0)
            time.sleep(3)
            
            s_nuova, p_ingresso = recupera_stato_posizione()
            if s_nuova > 0:
                for i, size in enumerate(RESTANTI_LIVELLI):
                    prezzo_livello = p_ingresso * (1 - (ratio_volatilità * (i + 1)) / 100)
                    session.place_order(category="linear", symbol=SYMBOL, side="Buy", 
                                        orderType="Limit", qty=str(size), price=str(round(prezzo_livello, 4)), positionIdx=0)
                
                aggiorna_tp_limit_chirurgico(s_nuova, p_ingresso * (1 + ratio_volatilità / 100))
                ultima_size_tracciata = s_nuova

        time.sleep(3)
    except Exception as e:
        print(f"⚠️ Errore: {e}")
        time.sleep(5)
