import time
import math
import requests
import json
import os
from dotenv import load_dotenv
from pybit.unified_trading import HTTP

load_dotenv()

# --- КОНФІГУРАЦІЯ ---
API_KEY = os.getenv('API_KEY')
API_SECRET = os.getenv('API_SECRET')
# TELEGRAM_TOKEN = 'твій_токен'
# TELEGRAM_CHAT_ID = 'твій_ід'

if not API_KEY or not API_SECRET:
    raise ValueError("Ключі API_KEY та API_SECRET мають бути встановлені у файлі .env")

SYMBOL = "BTCUSDT"
ORDER_SIZE_USDT = 10
PROFIT_TARGET = 1000
ROUND_LEVEL_STEP = 1000
ROUND_LEVEL_OFFSET = 800
DATA_FILE = "positions.json"

session = HTTP(testnet=False, demo=True, api_key=API_KEY, api_secret=API_SECRET)
active_positions = []

# def send_telegram(message):
#     try:
#         url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
#         requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"})
#     except: pass

def get_symbol_precision(symbol):
    info = session.get_instruments_info(category="spot", symbol=symbol)
    if len(info['result']['list']) == 0:
        raise ValueError("Invalid symbol or no data returned.")
    res = info['result']['list'][0]['lotSizeFilter']['basePrecision']
    return len(res.split('.')[1]) if '.' in res else 0

def save_positions():
    with open(DATA_FILE, "w") as f:
        json.dump(active_positions, f)

def load_positions_hybrid(precision):
    global active_positions
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            active_positions = json.load(f)
        print(f"📂 Завантажено з файлу: {len(active_positions)} угод.")
        if len(active_positions) > 0:
            print("✅ Позиції завантажено з локального файлу.")
            return
        else:
            print("⚠️ Локальний файл порожній, спробуємо відновити з API.")
    
    print("🔍 Відновлюємо дані з API Bybit.")
    try:
        history = session.get_executions(category="spot", symbol=SYMBOL, limit=50)
        trades = history['result']['list']
        
        buys = [t for t in trades if t['side'] == 'Buy']
        sells_qty = sum(float(t['execQty']) for t in trades if t['side'] == 'Sell')

        restored = []
        for b in buys:
            qty = float(b['execQty'])
            if sells_qty >= qty:
                sells_qty -= qty
            else:
                remaining = qty - sells_qty
                sells_qty = 0
                if remaining > 0.0001:
                    safe_qty = math.floor((remaining * 0.999) * (10**precision)) / (10**precision)
                    restored.append({
                        "buy_price": float(b['execPrice']),
                        "qty": format(safe_qty, f'.{precision}f')
                    })
        
        active_positions = restored
        print(f"✅ Відновлено позиції: {len(active_positions)}")
        save_positions()
    except Exception as e:
        print(f"❌ Помилка відновлення: {e}")

def check_and_execute_buy(last_price, current_price, precision):
    global active_positions
    level = ((last_price - ROUND_LEVEL_OFFSET) // ROUND_LEVEL_STEP) * ROUND_LEVEL_STEP + ROUND_LEVEL_OFFSET
    if last_price > level and current_price <= level:
        if not any(abs(p['buy_price'] - level) < (ROUND_LEVEL_STEP / 2) for p in active_positions):
            try:
                print(f"🛒 Купуємо на рівні {level}")
                order = session.place_order(
                    category="spot",
                    symbol=SYMBOL,
                    side="Buy",
                    orderType="Market",
                    qty=str(ORDER_SIZE_USDT)
                )
                time.sleep(3) # Час на розміщення ордеру

                if order.get('retCode') == 0 and order.get('result', {}).get('orderId'):
                    order_id = order['result']['orderId']
                    print(f"✅ Ордер на купівлю {order_id} розміщено.")
                    time.sleep(5) # Час на виконання ордеру

                    exec_history = session.get_executions(category="spot", symbol=SYMBOL, orderId=order_id, limit=1)

                    if exec_history and exec_history.get('result', {}).get('list'):
                        execs = exec_history['result']['list'][0]
                        q = math.floor((float(execs['execQty']) * 0.999) * (10**precision)) / (10**precision)
                        active_positions.append({"buy_price": float(execs['execPrice']), "qty": format(q, f'.{precision}f')})
                        save_positions()
                        print(f"📥 Куплено {q} {SYMBOL.replace('USDT','')} по {execs['execPrice']}")
                    else:
                        print(f"⚠️ Не вдалося отримати дані про виконання для ордеру {order_id}.")
                else:
                    print(f"❌ Помилка розміщення ордеру на купівлю: {order.get('retMsg', 'Невідома помилка')}")

            except Exception as e:
                print(f"❌ КРИТИЧНА ПОМИЛКА при купівлі: {e}")

def check_and_execute_sell(current_price):
    global active_positions
    for pos in active_positions[:]:
        if current_price >= pos['buy_price'] + PROFIT_TARGET:
            try:
                print(f"💰 Продаж по {current_price}, позиція: {pos}")
                order = session.place_order(
                    category="spot",
                    symbol=SYMBOL,
                    side="Sell",
                    orderType="Market",
                    qty=pos['qty']
                )

                if order.get('retCode') == 0:
                    order_id = order['result']['orderId']
                    print(f"✅ Ордер на продаж {order_id} успішно розміщено.")
                    active_positions.remove(pos)
                    save_positions()
                    print("✅ Позицію видалено з активних.")
                else:
                    print(f"❌ Помилка розміщення ордеру на продаж: {order.get('retMsg', 'Невідома помилка')}")
            
            except Exception as e:
                print(f"❌ КРИТИЧНА ПОМИЛКА при продажі: {e}")

def main():
    precision = get_symbol_precision(SYMBOL)
    load_positions_hybrid(precision)
    
    last_price = float(session.get_tickers(category="spot", symbol=SYMBOL)['result']['list'][0]['lastPrice'])
    # send_telegram("✅ Бот запущений та готовий до торгівлі.")

    while True:
        try:
            current_price = float(session.get_tickers(category="spot", symbol=SYMBOL)['result']['list'][0]['lastPrice'])
            
            check_and_execute_buy(last_price, current_price, precision)
            check_and_execute_sell(current_price)

            last_price = current_price

            # Розрахунок наступних рівнів для виводу
            next_buy_level = ((current_price - ROUND_LEVEL_OFFSET) // ROUND_LEVEL_STEP) * ROUND_LEVEL_STEP + ROUND_LEVEL_OFFSET
            
            next_sell_price_str = "немає"
            if active_positions:
                next_sell_price = min(p['buy_price'] + PROFIT_TARGET for p in active_positions)
                next_sell_price_str = f"{next_sell_price:.2f}"

            print(f"Поточна: {current_price:.2f} | Позицій: {len(active_positions)} | Наст. купівля: {next_buy_level:.2f} | Наст. продаж: {next_sell_price_str}")
            time.sleep(5)
        except Exception as e:
            print(f"Помилка: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
