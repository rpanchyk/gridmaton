import sys
import time
from datetime import datetime
import math
import json
import os
import queue
import requests
import threading
from dotenv import load_dotenv
from enum import Enum
from pybit.unified_trading import HTTP, WebSocket

# Перелік типів сітки
class GridType(Enum):
    LINEAR = 1
    FIBO = 2

# Завантаження змінних оточення
load_dotenv()

# Конфігурація
API_KEY = os.getenv('API_KEY') # API ключ
API_SECRET = os.getenv('API_SECRET') # API cекрет
TELEGRAM_NOTIFICATIONS = os.getenv("TELEGRAM_NOTIFICATIONS", 'False').lower() in ('true', '1') # Увімкнення повідомлень в Telegram
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN') # Токен бота Telegram
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID') # Ідентифікатор чату Telegram
DEMO_MODE = os.getenv('DEMO_MODE', 'False').lower() in ('true', '1') # Режим демо
BASE_COIN = os.getenv('BASE_COIN', 'BTC') # Базова монета для торгівлі
QUOTE_COIN = os.getenv('QUOTE_COIN', 'USDT') # Котирувальна монета для торгівлі
GRID_TYPE = GridType[os.getenv('GRID_TYPE', 'LINEAR').upper()] # Тип сітки для набору позицій
ORDER_SIZE = float(os.getenv('ORDER_SIZE', '10')) # Сума в котирувальній монеті для покупки
PROFIT_TARGET = float(os.getenv('PROFIT_TARGET', '1000')) # Зміна ціни для продажу
LEVEL_STEP = float(os.getenv('LEVEL_STEP', '1000')) # Крок рівня для купівлі
LEVEL_OFFSET = float(os.getenv('LEVEL_OFFSET', '500')) # Зміщення рівня для купівлі

# Статичні налаштування
SYMBOL = f"{BASE_COIN}{QUOTE_COIN}"
FIBO_NUMBERS = [1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144]
POSITIONS_FILE = "positions.json"
TRADE_LOG_FILE = "trade.log"

# Перевірка наявності ключів API
if not API_KEY or not API_SECRET:
    raise ValueError("Ключі API_KEY та API_SECRET мають бути встановлені у файлі .env")

# Ініціалізація глобальних змінних
data_queue = queue.Queue() # Черга для обробки даних
session = None # Сесія API
precision = 8 # Точність символу (кількість знаків після коми)
active_positions = [] # Список активних позицій
last_price = 0.0 # Остання ціна символу

def get_symbol_precision(symbol):
    """
    Отримання точності символу.
    :param symbol: Символ
    :return: Точність символу
    """
    global session
    info = session.get_instruments_info(category="spot", symbol=symbol)
    if len(info['result']['list']) == 0:
        raise ValueError("Невірний символ або відсутня інформація про нього.")
    value = info['result']['list'][0]['lotSizeFilter']['basePrecision']
    return len(value.split('.')[1]) if '.' in value else 0

def load_positions(precision, force_api=False):
    """
    Завантажує активні позиції з файлу або відновлює їх з API, якщо файл відсутній або порожній.
    :param precision: Кількість знаків після коми для округлення кількості
    """
    global session, active_positions

    # Отримання балансу монети
    balance_info = session.get_wallet_balance(accountType="UNIFIED", coin=BASE_COIN)
    if balance_info.get('retCode') != 0:
        raise ValueError(f"Помилка отримання балансу: {balance_info.get('retMsg')}")
    balance_qty = float(balance_info['result']['list'][0]['coin'][0]['walletBalance'])
    usd_value = float(balance_info['result']['list'][0]['coin'][0]['usdValue'])
    equity_qty = float(balance_info['result']['list'][0]['totalEquity'])
    print(f"💲 Баланс: {format(balance_qty, f'.{precision}f')} {BASE_COIN} (${format(usd_value, '.2f')}) та {format(equity_qty, '.2f')} {QUOTE_COIN}")

    print("⚓ Відновлення позицій...")
    global active_positions
    if os.path.exists(POSITIONS_FILE) and not force_api:
        print("🔍 Відновлюємо позиції з локального файлу...")
        with open(POSITIONS_FILE, "r") as f:
            active_positions = json.load(f)
        if not active_positions:
            print("⚠️ Позицій для відновлення не знайдено.")
        else:
            return # Успішно завантажено з файлу

    print("🔍 Відновлюємо позиції з API...")
    try:
        # Отримання історії ордерів
        history = session.get_order_history(
            category="spot",
            symbol=SYMBOL,
            limit=100,
            status="Filled",
            execType="Trade"
        )
        if history.get('retCode') != 0:
            raise ValueError(f"Помилка отримання історії ордерів: {history.get('retMsg')}")
        trades = history['result']['list']
        buys = [t for t in trades if t['side'] == 'Buy']
        buys.sort(key=lambda x: x['createdTime'], reverse=True)  # Сортуємо за часом створення
        # with open("buys.json", "w") as f:
        #     json.dump(buys, f, indent=4)

        # Відновлення позицій з історії ордерів
        restored = []
        if balance_qty > 0:
            for b in buys:
                fee = float(b['cumFeeDetail'][BASE_COIN]) if BASE_COIN in b['cumFeeDetail'] else 0
                qty = float(b['cumExecQty']) - fee # Віднімаємо комісію в BTC
                if balance_qty >= qty:
                    restored.append({
                        "date": datetime.fromtimestamp(int(b['createdTime'])/1000).strftime("%Y-%m-%d %H:%M:%S"),
                        "side": "Buy",
                        "price": float(b['avgPrice']),
                        "qty": format(qty, f'.{precision+2}f'),
                        "fee": format(fee, f'.{precision+2}f')
                    })
                    balance_qty -= qty
                else:
                    break

        # Оновлення активних позицій
        active_positions = restored

        if not active_positions:
            print("⚠️ Позицій для відновлення не знайдено.")
        
        # Збереження позицій
        save_positions()
    except Exception as e:
        print(f"❌ Помилка відновлення: {e}")

def save_positions():
    """
    Зберігає активні позиції у файлі.
    """
    global active_positions

    # Сортуємо за ціною (від більшої до меншої)
    active_positions.sort(key=lambda x: x['price'], reverse=True)

    # Зберігаємо у файл
    with open(POSITIONS_FILE, "w") as f:
        json.dump(active_positions, f, indent=4)

def handle_message(message):
    """
    Обробка повідомлень з WebSocket стріму тікерів.
    :param message: Повідомлення
    """
    global data_queue
    if 'data' in message:
        data_queue.put(message['data'])

def worker():
    """
    Обробка повідомлень з черги.
    """
    global data_queue
    while True:
        data = data_queue.get()
        if data is None:
            break

        process_data(data)

        data_queue.task_done()

def process_data(data):
    """
    Обробка отриманих даних.
    :param data: Дані повідомлення
    """
    global precision, active_positions, last_price
    try:
        # Отримуємо поточну ціну
        current_price = float(data['lastPrice'])

        # Перевірка останньої (попередньої) отриманої ціни
        global last_price
        if last_price <= 0:
            last_price = current_price
            return # Ігноруємо перше повідомлення, яке встановлює базову ціну

        # Перевірка на зміну ціни
        if current_price == last_price:
            return # Ігноруємо, якщо ціна не змінилася

        # Перевірка на виконання продажу відповідно до поточної ціни
        check_and_execute_sell(current_price)

        # Розрахунок наступних рівнів купівлі
        next_lower_buy_level = get_next_lower_buy_level()
        next_upper_buy_level = get_next_upper_buy_level()

        # Перевірка на виконання купівлі відповідно до поточної ціни
        check_and_execute_buy(current_price, next_lower_buy_level, next_upper_buy_level)

        # Розрахунок наступного рівня продажу
        next_sell_price = min([p['price'] + PROFIT_TARGET for p in active_positions]) if active_positions else None

        # Виведення інформації
        print(f"Минула ціна: {f"{last_price:.2f}"}", end="")
        print(f" | Поточна ціна: {f"{current_price:.2f}"}", end="")
        print(f" | Позицій: {len(active_positions)}", end="")
        print(f" | Наст.купівля знизу: {f"{next_lower_buy_level:.2f}"}", end="")
        print(f" | Наст.купівля зверху: {f"{next_upper_buy_level:.2f}"}", end="")
        print(f" | Наст.продаж: {f"{next_sell_price:.2f}" if next_sell_price else "немає"}", end="")
        print("", flush=True)

        # Оновлення останньої ціни
        last_price = current_price
    except KeyError:
        pass # Ігноруємо неочікувані повідомлення
    except Exception as e:
        print(f"❌ Помилка в обробці WebSocket повідомлення: {e}")

def check_and_execute_sell(current_price):
    """
    Перевіряє активні позиції на досягнення цільового рівня прибутку та виконує продаж.
    :param current_price: Поточна ціна для порівняння з рівнями продажу
    """
    global session, precision, active_positions
    for pos in active_positions:
        sell_price = pos['price'] + PROFIT_TARGET
        if current_price >= sell_price:
            try:
                print(f"👀 Ціна {current_price} досягла рівня продажу {sell_price} для позиції купівлі по {pos['price']}")

                # Округлюємо кількість ВНИЗ до потрібної точності
                factor = 10 ** precision

                # Отримуємо баланс монети
                balance_info = session.get_wallet_balance(accountType="UNIFIED", coin=BASE_COIN)
                if balance_info.get('retCode') != 0:
                    print(f"❌ Помилка отримання балансу: {balance_info.get('retMsg')}")
                    return

                # Отримуємо доступний баланс
                balance_qty = float(balance_info['result']['list'][0]['coin'][0]['walletBalance'])
                balance_qty = math.floor(balance_qty * factor) / factor
                print(f"💲 Баланс {BASE_COIN}: {balance_qty}")
                
                # Потрібна кількість для продажу
                needed_qty = float(pos['qty'])
                needed_qty = math.floor(needed_qty * factor) / factor
                print(f"Потрібно продати: {needed_qty} {BASE_COIN}")

                # Перевіряємо, чи вистачає балансу
                if balance_qty < needed_qty:
                    print(f"⚠️ Недостатньо балансу {BASE_COIN}: Треба {needed_qty}, є {balance_qty}")
                    # Тут можна або пропустити, або спробувати продати те, що є:
                    # continue
                    needed_qty = balance_qty

                print(f"💰 Спроба продажу по {current_price}...")
                order = session.place_order(
                    category="spot",
                    symbol=SYMBOL,
                    side="Sell",
                    orderType="Market",
                    qty=format(needed_qty, f'.{precision}f')
                )
                if order.get('retCode') != 0:
                    print(f"❌ Помилка розміщення ордеру: {order.get('retMsg')}")
                    continue

                order_id = order['result']['orderId']
                print(f"🚚 Ордер {order_id} розміщено. Очікування виконання...")
                is_filled = False

                # Перевірка статусу (до 5 спроб)
                for _ in range(5):
                    time.sleep(1) # Затримка перед перевіркою

                    # Перевіряємо через історію ордерів
                    check = session.get_order_history(
                        category="spot",
                        symbol=SYMBOL,
                        orderId=order_id
                    )
                    if check.get('retCode') != 0:
                        print(f"❌ Помилка отримання історії ордерів: {check.get('retMsg')}")
                        continue
                    # print(f"Історія ордеру: {check}")

                    if check['result']['list']:
                        order_data = check['result']['list'][0]

                        # Перевіряємо статус ордера
                        if order_data['orderStatus'] == "Filled":
                            # Оновлюємо позиції з API, щоб уникнути розбіжностей
                            load_positions(precision, force_api=True)

                            # Отримуємо реальну ціну виконання
                            exec_price = float(order_data.get('avgPrice', current_price))
                            profit = (exec_price - pos['price']) * float(pos['qty'])

                            # Отримуємо час виконання
                            exec_time = order_data.get('execTime', 0)
                            exec_time = datetime.fromtimestamp(int(exec_time)/1000) if exec_time else datetime.now()
                            timedelta = exec_time - datetime.strptime(pos['date'], '%Y-%m-%d %H:%M:%S')

                            message = f"💰 Продано {pos['qty']} {BASE_COIN} по ціні {exec_price} {QUOTE_COIN}"
                            message += f", що становить {format(float(pos['qty']) * exec_price, '.2f')} {QUOTE_COIN}"
                            message += f", прибуток {format(profit, '.2f')} {QUOTE_COIN}."
                            message += f" Ордер був розміщений {pos['date']} та тривав до {exec_time.strftime('%Y-%m-%d %H:%M:%S')},"
                            message += f" загальний час утримання позиції склав {format_timedelta(timedelta)}."
                            print(message)

                            # Записуємо в лог-файл
                            log_trade(pos, "SELL", exec_price, profit=profit)

                            # Оповіщаємо в Telegram
                            send_telegram(message)

                            is_filled = True
                            break

                if not is_filled:
                    print(f"⚠️ Ордер {order_id} розміщено, але статус 'Filled' не отримано.")

            except Exception as e:
                print(f"❌ КРИТИЧНА ПОМИЛКА при продажі: {e}")

def format_timedelta(timedelta):
    """
    Форматує timedelta об'єкт в читабельний формат.
    :param td: timedelta об'єкт
    :return: Рядок з форматованим часом (наприклад, "2 дні, 3 години, 15 хвилин")
    """
    total_seconds = int(timedelta.total_seconds())
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    parts = []
    if days > 0:
        parts.append(f"{days} {'день' if days == 1 else 'дні' if days % 10 in [2, 3, 4] else 'днів'}")
    if hours > 0:
        parts.append(f"{hours} {'година' if hours == 1 else 'години' if hours % 10 in [2, 3, 4] else 'годин'}")
    if minutes > 0:
        parts.append(f"{minutes} {'хвилина' if minutes == 1 else 'хвилини' if minutes % 10 in [2, 3, 4] else 'хвилин'}")
    if seconds > 0 or not parts:
        parts.append(f"{seconds} {'секунда' if seconds == 1 else 'секунди' if seconds % 10 in [2, 3, 4] else 'секунд'}")

    return ", ".join(parts)

def get_next_lower_buy_level():
    """
    Розрахунок наступного нижнього рівня купівлі.
    :return: Розрахований рівень купівлі
    """
    global GRID_TYPE, LEVEL_STEP, LEVEL_OFFSET, FIBO_NUMBERS
    global active_positions, last_price

    # Розрахунок рівня на основі кроку та зсуву для поточної ціни
    level = ((last_price - LEVEL_OFFSET) // LEVEL_STEP) * LEVEL_STEP + LEVEL_OFFSET

    # Якщо немає активних позицій, повертаємо розрахований рівень
    if not active_positions:
        return level

    # Перевірка, чи є активна позиція на цьому рівні, і якщо так, зсув рівня вниз на крок
    for p in active_positions:
        p_level = (p['price'] // LEVEL_STEP) * LEVEL_STEP + LEVEL_OFFSET
        if level == p_level:
            level -= LEVEL_STEP # Зсув рівня вниз
            break

    # Якщо тип сітки лінійний, повертаємо розрахований рівень
    if GRID_TYPE == GridType.LINEAR:
        return level

    # Коригування рівня відповідно до послідовності Фібоначчі
    if GRID_TYPE == GridType.FIBO:
        count = len(active_positions)
        prev_fibo = 0
        for curr_fibo in FIBO_NUMBERS:
            if count < curr_fibo:
                diff = curr_fibo - prev_fibo
                if diff > 1:
                    last_position = min(active_positions, key=lambda x: x['price'])
                    last_position_level = (last_position['price'] // LEVEL_STEP) * LEVEL_STEP + LEVEL_OFFSET
                    level = last_position_level - LEVEL_STEP * diff # Зсув рівня вниз
                break
            prev_fibo = curr_fibo

    return level

def get_next_upper_buy_level():
    """
    Розрахунок наступного верхнього рівня купівлі.
    :return: Розрахований рівень купівлі
    """
    global GRID_TYPE, LEVEL_STEP, LEVEL_OFFSET, FIBO_NUMBERS
    global active_positions, last_price

    max_price = max([p['price'] for p in active_positions]) if active_positions else None
    price = max_price if max_price else last_price
    level = (price // LEVEL_STEP) * LEVEL_STEP + LEVEL_OFFSET + LEVEL_STEP

    return level

def check_and_execute_buy(current_price, lower_buy_level, upper_buy_level):
    """
    Перевіряє ціну та виконує купівлю, якщо ціна перетинає рівень і немає активних позицій на цьому рівні.
    :param current_price: Поточна ціна для порівняння з рівнем купівлі
    :param lower_buy_level: Нижній рівень купівлі
    :param upper_buy_level: Верхній рівень купівлі
    """
    global session, precision, active_positions, last_price

    # Визначення рівня купівлі, який було перетнуто
    level = None
    if last_price > lower_buy_level and current_price <= lower_buy_level:
        print(f"🧃 Перетин нижнього рівня купівлі {lower_buy_level} вниз")
        level = lower_buy_level
    elif last_price < upper_buy_level and current_price >= upper_buy_level:
        print(f"🧃 Перетин верхнього рівня купівлі {upper_buy_level} вверх")
        level = upper_buy_level
    else:
        return # Рівень купівлі не перетнуто

    try:
        print(f"🛒 Спроба купівлі на рівні {level}...")

        # Розміщуємо ринковий ордер
        order = session.place_order(
            category="spot",
            symbol=SYMBOL,
            side="Buy",
            orderType="Market",
            qty=str(ORDER_SIZE) # Для Spot Market Buy вказується сума в USDT
        )

        if order.get('retCode') == 0:
            order_id = order['result']['orderId']
            print(f"🚚 Ордер {order_id} розміщено. Очікування виконання...")
            is_filled = False

            # Перевірка статусу (до 5 спроб)
            for _ in range(5):
                time.sleep(1) # Затримка перед перевіркою

                # Перевіряємо через історію ордерів
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
                        # Оновлюємо позиції з API, щоб уникнути розбіжностей
                        load_positions(precision, force_api=True)

                        # Отримуємо реальні дані виконання
                        pos = active_positions[-1]
                        exec_price = pos['price']
                        exec_qty = float(pos['qty'])
                        commission = float(pos['fee'])

                        message = f"📥 Куплено {exec_qty} {BASE_COIN} по ціні {exec_price} {QUOTE_COIN}"
                        message += f", що становить {format(exec_qty * exec_price, '.2f')} {QUOTE_COIN}"
                        message += f" включно з комісією {format(commission * exec_price, '.2f')} {QUOTE_COIN}."
                        print(message)

                        # Записуємо в лог-файл
                        log_trade(pos, "BUY", exec_price)

                        # Оповіщаємо в Telegram
                        send_telegram(message)

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
        log_msg += f" | BuyPrice: {pos['price']} | Profit: {profit:.4f}"

    # Запис у файл
    with open(TRADE_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_msg + "\n")

def send_telegram(message):
    """
    Відправка повідомлення в Telegram.
    :param message: Текст повідомлення
    """
    global TELEGRAM_NOTIFICATIONS, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

    if not TELEGRAM_NOTIFICATIONS:
        return

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram токен або чат ID не встановлено.")
        return

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
        requests.post(url, data=data)
    except Exception as e:
        print(f"Помилка Telegram: {e}")

def main():
    """
    Головна функція для запуску бота.
    Вона ініціалізує з'єднання та підписується на стрім тікерів.
    """
    print(f"🟢 Бот запущений та готовий до торгівлі {SYMBOL}")

    # Ініціалізація сесії API
    global session
    try:
        print("🔗 Підключення до біржі ", end="")
        session = HTTP(testnet=False, demo=DEMO_MODE, api_key=API_KEY, api_secret=API_SECRET)
        print("виконано успішно")
    except Exception as e:
        print(f"❌ завершено з помилкою: {e}")
        return

    # Отримання точності символу
    global precision
    precision = get_symbol_precision(SYMBOL)
    print(f"🤺 Точність символу {SYMBOL}: {precision} знаків після коми")

    # Завантаження поточних позицій
    global active_positions
    load_positions(precision)
    if active_positions:
        print(f"📢 Активні позиції ({len(active_positions)} шт.): {active_positions}")
    else:
        print("📢 Активних позицій немає")

    # Запуск робочого потоку для обробки повідомлень
    threading.Thread(target=worker, daemon=True).start()
    print("⚙️ Робочий потік запущено")

    # Ініціалізація веб-сокета для отримання тікерів
    try:
        print("🔄 Підписка на стрім тікерів ", end="")
        ws = WebSocket(testnet=False, channel_type="spot", api_key=API_KEY, api_secret=API_SECRET)
        ws.ticker_stream(symbol=SYMBOL, callback=handle_message)
        print("виконано успішно")
    except Exception as e:
        print(f"❌ завершено з помилкою: {e}")
        return

    # Утримання програми в активному стані
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("🔴 Бот зупинено")

# Точка входу
if __name__ == "__main__":
    main()
