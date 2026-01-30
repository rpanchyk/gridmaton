import time
from datetime import datetime
import math
import json
import os
from dotenv import load_dotenv
from pybit.unified_trading import HTTP, WebSocket

# Завантаження змінних оточення
load_dotenv()

# Конфігурація
API_KEY = os.getenv('API_KEY')
API_SECRET = os.getenv('API_SECRET')

if not API_KEY or not API_SECRET:
    raise ValueError("Ключі API_KEY та API_SECRET мають бути встановлені у файлі .env")

# Статичні налаштування
DEMO_MODE = True
SYMBOL = "BTCUSDT"
ORDER_SIZE_USDT = 10
PROFIT_TARGET = 1000
ROUND_LEVEL_STEP = 1000
ROUND_LEVEL_OFFSET = 900
POSITIONS_FILE = "positions.json"
TRADE_LOG_FILE = "trade.log"

# Ініціалізація сесії та активних позицій
session = HTTP(testnet=False, demo=DEMO_MODE, api_key=API_KEY, api_secret=API_SECRET)
active_positions = []

def get_symbol_precision(symbol):
    info = session.get_instruments_info(category="spot", symbol=symbol)
    if len(info['result']['list']) == 0:
        raise ValueError("Невірний символ або відсутня інформація про нього.")
    res = info['result']['list'][0]['lotSizeFilter']['basePrecision']
    return len(res.split('.')[1]) if '.' in res else 0

def save_positions():
    with open(POSITIONS_FILE, "w") as f:
        json.dump(active_positions, f, indent=4)

def load_positions(precision):
    print("⚓ Відновлення позицій...")
    global active_positions
    if os.path.exists(POSITIONS_FILE):
        print("🔍 Відновлюємо позиції з локального файлу...")
        with open(POSITIONS_FILE, "r") as f:
            active_positions = json.load(f)
        if not active_positions:
            print("⚠️ Позицій для відновлення не знайдено.")
        else:
            return # Успішно завантажено з файлу
    
    print("🔍 Відновлюємо позиції з API...")
    try:
        history = session.get_executions(category="spot", symbol=SYMBOL, limit=100)
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

        if not active_positions:
            print("⚠️ Позицій для відновлення не знайдено.")
        else:
            save_positions()
    except Exception as e:
        print(f"❌ Помилка відновлення: {e}")

def check_and_execute_buy(last_price, current_price, precision):
    global active_positions
    level = ((last_price - ROUND_LEVEL_OFFSET) // ROUND_LEVEL_STEP) * ROUND_LEVEL_STEP + ROUND_LEVEL_OFFSET
    
    # Перевірка умови перетину рівня та відсутності дублікатів
    if last_price > level and current_price <= level:
        if not any(abs(p['buy_price'] - level) < (ROUND_LEVEL_STEP / 2) for p in active_positions):
            try:
                print(f"🛒 Спроба купівлі на рівні {level}...")
                
                # Розміщуємо ринковий ордер
                order = session.place_order(
                    category="spot",
                    symbol=SYMBOL,
                    side="Buy",
                    orderType="Market",
                    qty=str(ORDER_SIZE_USDT) # Для Spot Market Buy вказується сума в USDT
                )

                if order.get('retCode') == 0:
                    order_id = order['result']['orderId']
                    print(f"🚚 Ордер {order_id} розміщено. Очікування виконання...")
                    is_filled = False

                    # Перевірка статусу (до 5 спроб)
                    for _ in range(5):
                        time.sleep(2)
                        
                        # Перевіряємо через історію ордерів (найбільш надійно)
                        check = session.get_order_history(
                            category="spot",
                            symbol=SYMBOL,
                            orderId=order_id
                        )
                        # print(f"Історія ордеру: {check}")
                        
                        if check.get('retCode') == 0 and check['result']['list']:
                            order_data = check['result']['list'][0]
                            status = order_data['orderStatus']
                            
                            if status == "Filled":
                                # Отримуємо реальні дані виконання
                                exec_qty = float(order_data.get('cumExecQty', 0))
                                exec_price = float(order_data.get('avgPrice', current_price))
                                commission = float(order_data.get('cumExecFee', 0))

                                exec_qty = exec_qty - commission  # Віднімаємо комісію в BTC

                                # Округлюємо кількість ВНИЗ до потрібної точності
                                factor = 10 ** precision
                                exec_qty = math.floor(exec_qty * factor) / factor
                                
                                # Додаємо в список активних позицій
                                new_pos = {
                                    "buy_price": exec_price, 
                                    "qty": format(exec_qty, f'.{precision}f')
                                }
                                active_positions.append(new_pos)
                                save_positions()
                                
                                # Записуємо в лог-файл
                                log_trade(new_pos, "BUY", exec_price)
                                
                                print(f"📥 Успішно куплено {exec_qty} {SYMBOL.replace('USDT', '')} по ціні {exec_price} {SYMBOL.replace('BTC', '')}", end="")
                                print(f", що становить {format(float(order_data.get('qty', 0)), '.2f')} {SYMBOL.replace('BTC', '')}", end="")
                                print(f" включно з комісією {format(commission * exec_price, '.2f')} {SYMBOL.replace('BTC', '')}.")
                                is_filled = True
                                break
                            elif status in ["Cancelled", "Rejected"]:
                                print(f"⚠️ Ордер скасовано або відхилено: {status}")
                                break
                        
                    if not is_filled:
                        print(f"⏳ Статус ордера {order_id} не визначено. Позицію не додано.")
                else:
                    print(f"❌ Помилка API: {order.get('retMsg')}")

            except Exception as e:
                print(f"❌ КРИТИЧНА ПОМИЛКА при купівлі: {e}")

def check_and_execute_sell(current_price, precision):
    global active_positions
    for pos in active_positions[:]:
        if current_price >= pos['buy_price'] + PROFIT_TARGET:
            try:
                # Отримуємо назву монети з SYMBOL (наприклад, з "BTCUSDT" робимо "BTC")
                base_coin = SYMBOL.replace("USDT", "")
                balance_info = session.get_wallet_balance(accountType="UNIFIED", coin=base_coin)
                
                if balance_info.get('retCode') == 0:
                    # Шукаємо баланс конкретної монети в результаті
                    coins = balance_info['result']['list'][0]['coin']
                    print(f"Баланс {base_coin}: {coins}")

                    # Округлюємо кількість ВНИЗ до потрібної точності
                    factor = 10 ** precision
                    
                    # Отримуємо доступний баланс (availableToWithdraw або free)
                    available_balance = float(coins[0].get('walletBalance', 0))
                    available_balance = math.floor(available_balance * factor) / factor
                    print(f"Доступний баланс {base_coin}: {available_balance}")
                    
                    # Потрібна кількість для продажу
                    needed_qty = float(pos['qty'])
                    needed_qty = math.floor(needed_qty * factor) / factor
                    print(f"Потрібно продати: {needed_qty} {base_coin}")

                    # Перевіряємо, чи вистачає балансу
                    if available_balance < needed_qty:
                        print(f"⚠️ Недостатньо балансу {base_coin}: Треба {needed_qty}, є {available_balance}")
                        # Тут можна або пропустити, або спробувати продати те, що є:
                        pos['qty'] = available_balance 
                        # continue

                print(f"💰 Спроба продажу по {current_price}...")
                order = session.place_order(
                    category="spot",
                    symbol=SYMBOL,
                    side="Sell",
                    orderType="Market",
                    qty=pos['qty']
                )

                if order.get('retCode') == 0:
                    order_id = order['result']['orderId']
                    print(f"🚚 Ордер {order_id} розміщено. Очікування виконання...")
                    is_filled = False
                    
                    # Перевірка статусу (до 5 спроб)
                    for _ in range(5):
                        time.sleep(2)
                        check = session.get_order_history(
                            category="spot",
                            symbol=SYMBOL,
                            orderId=order_id
                        )
                        # print(f"Історія ордеру: {check}")
                        
                        if check.get('retCode') == 0 and check['result']['list']:
                            order_data = check['result']['list'][0]
                            status = order_data['orderStatus']
                            
                            if status == "Filled":
                                # Отримуємо реальну ціну виконання
                                exec_price = float(order_data.get('avgPrice', current_price))
                                profit = (exec_price - pos['buy_price']) * float(pos['qty'])
                                
                                print(f"✅ Виконано! Ціна: {exec_price}, Прибуток: {profit:.2f} {SYMBOL.replace("BTC", "")}")
                                
                                # Видаляємо позицію зі списку активних та зберігаємо файл
                                active_positions.remove(pos)
                                save_positions()

                                # Записуємо в лог-файл
                                log_trade(pos, "SELL", exec_price, profit=profit)
                                
                                is_filled = True
                                break
                    
                    if not is_filled:
                        print(f"⚠️ Ордер {order_id} розміщено, але статус 'Filled' не отримано.")
                else:
                    print(f"❌ Помилка ордеру: {order.get('retMsg')}")
            
            except Exception as e:
                print(f"❌ КРИТИЧНА ПОМИЛКА при продажі: {e}")

def log_trade(pos, action, exec_price, profit=None):
    """
    Уніфіковане логування операцій купівлі та продажу.
    :param pos: Дані позиції
    :param action: 'BUY' або 'SELL'
    :param exec_price: Ціна виконання
    :param profit: Прибуток (тільки для SELL)
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Формуємо базову частину повідомлення
    log_msg = f"[{timestamp}] {action.upper()}{' ' if action.upper() == 'BUY' else ''} | {SYMBOL} | Price: {exec_price} | Qty: {pos['qty']}"
    
    # Якщо це продаж, додаємо ціну купівлі та профіт
    if action.upper() == "SELL":
        log_msg += f" | BuyPrice: {pos['buy_price']} | Profit: {profit:.4f}"
    
    # Запис у файл
    with open(TRADE_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_msg + "\n")

def handle_message(message):
    global last_price
    try:
        # Обробка повідомлення тікера
        data = message['data']
        current_price = float(data['lastPrice'])
        if current_price == last_price:
            return # Ігноруємо, якщо ціна не змінилася
        
        # Перевірка на купівлю/продаж
        check_and_execute_buy(last_price, current_price, precision)
        check_and_execute_sell(current_price, precision)
        
        # Форматування для виводу
        last_price_str = f"{last_price:.2f}"
        current_price_str = f"{current_price:.2f}"

        # Оновлення останньої ціни
        last_price = current_price
        
        # Розрахунок наступних рівнів для виводу
        next_buy_level = ((last_price - ROUND_LEVEL_OFFSET) // ROUND_LEVEL_STEP) * ROUND_LEVEL_STEP + ROUND_LEVEL_OFFSET
        if any(abs(p['buy_price'] - next_buy_level) < (ROUND_LEVEL_STEP / 2) for p in active_positions):
            next_buy_level -= ROUND_LEVEL_STEP
        next_buy_level_str = f"{next_buy_level:.2f}"
        next_sell_price_str = "немає"
        if active_positions:
            next_sell_price = min(p['buy_price'] + PROFIT_TARGET for p in active_positions)
            next_sell_price_str = f"{next_sell_price:.2f}"

        print(f"Минула ціна: {last_price_str}", end="")
        print(f" | Поточна ціна: {current_price_str}", end="")
        print(f" | Позицій: {len(active_positions)}", end="")
        print(f" | Наст.купівля: {next_buy_level_str}", end="")
        print(f" | Наст.продаж: {next_sell_price_str}", end="")
        print("", flush=True)
    except KeyError:
        pass # Ігноруємо неочікувані повідомлення
    except Exception as e:
        print(f"❌ Помилка в обробці WebSocket повідомлення: {e}")

def main():
    print(f"🟢 Бот запущений та готовий до торгівлі {SYMBOL}.")

    # Отримання точності символу
    global precision
    precision = get_symbol_precision(SYMBOL)
    print(f"🤺 Точність символу {SYMBOL}: {precision} знаків після коми.")
    
    # Завантаження поточних позицій
    global active_positions
    load_positions(precision)
    if len(active_positions) > 0:
        print(f"📢 Активні позиції ({len(active_positions)} шт.): {active_positions}")
    else:
        print("📢 Активних позицій немає.")

    # Ініціалізація останньої ціни
    global last_price
    last_price = float(session.get_tickers(category="spot", symbol=SYMBOL)['result']['list'][0]['lastPrice'])

    # Підписка на стрім тікерів
    try:
        print("🔄 Підключення до біржі ", end="")
        ws = WebSocket(
            testnet=False,
            channel_type="spot",
            api_key=API_KEY,
            api_secret=API_SECRET
        )
        ws.ticker_stream(symbol=SYMBOL, callback=handle_message)
        print("виконано успішно.")
    except Exception as e:
        print(f"❌ завершено з помилкою: {e}")
        return

    # Утримання програми в активному стані
    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        print("🔴 Бот зупинено.")

if __name__ == "__main__":
    main()
