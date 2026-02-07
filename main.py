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

# Сумісні іконки для консолі:
# ☔☕♈♉♊♋♌♍♎♏♐♑♒♓⚓⚡⚪⚫⚽⚾⛄⛅⛎⛔⛲⛳⛵⛺⛽✅✊✋✨❌❎❓❔❕❗➕➖➗➰➿⚙️⚠️

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
SYMBOL = os.getenv('SYMBOL', 'BTCUSDT') # Торгова пара
GRID_TYPE = GridType[os.getenv('GRID_TYPE', 'LINEAR').upper()] # Тип сітки для набору позицій
ORDER_SIZE = float(os.getenv('ORDER_SIZE', '10')) # Сума в котирувальній монеті для покупки
PROFIT_TARGET = float(os.getenv('PROFIT_TARGET', '1000')) # Зміна ціни для продажу
LEVEL_STEP = float(os.getenv('LEVEL_STEP', '1000')) # Крок рівня для купівлі
LEVEL_OFFSET = float(os.getenv('LEVEL_OFFSET', '500')) # Зміщення рівня для купівлі

# Статичні налаштування
FIBO_NUMBERS = [1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144]
POSITIONS_FILE = "positions.json"
TRADE_LOG_FILE = "trade.log"
WORK_LOG_FILE = "work.log"
RETRY_NUMBER = 5
RETRY_DELAY = 2

# Перевірка наявності ключів API
if not API_KEY or not API_SECRET:
    raise ValueError("Ключі API_KEY та API_SECRET мають бути встановлені у файлі .env")

# Ініціалізація глобальних змінних
data_queue = queue.Queue(maxsize=1000) # Черга для обробки даних
active_positions_lock = threading.Lock() # Блокування для активних позицій
session = None # Сесія API
base_coin = None # Базова монета для торгівлі
quote_coin = None # Котирувальна монета для торгівлі
base_precision = 8 # Точність символу (кількість знаків після коми)
quote_precision = 2 # Точність котирувальної монети (кількість знаків після коми)
active_positions = [] # Список активних позицій
last_price = 0 # Остання ціна символу
accept_messages = True # Флаг для прийому повідомлень з WebSocket

def load_instruments_info():
    """
    Отримання інформації про символ.
    """
    global base_coin, quote_coin, base_precision, quote_precision

    # Отримання інформації про символ
    instrument_info = session.get_instruments_info(category="spot", symbol=SYMBOL)
    if not instrument_info['result']['list']:
        raise ValueError("Невірний символ або відсутня інформація про нього.")

    info = instrument_info['result']['list'][0]

    # Базова монета
    base_coin = info['baseCoin']

    # Котирувальна монета
    quote_coin = info['quoteCoin']

    # Отримання точності базової монети
    base_precision = info['lotSizeFilter']['basePrecision']
    base_precision = len(base_precision.split('.')[1]) if '.' in base_precision else 0

    # Отримання точності котирувальна монети
    quote_precision = info['lotSizeFilter']['quotePrecision']
    quote_precision = len(quote_precision.split('.')[1]) if '.' in quote_precision else 0

    # Виведення інформації про символ
    message = f"➗ Інструмент: {SYMBOL}"
    message += f", базова монета: {base_coin} (точність: {base_precision} знаків після коми)"
    message += f", котирувальна монета: {quote_coin} (точність: {quote_precision} знаків після коми)"
    log(message)

def load_positions(force_api=True):
    """
    Завантажує активні позиції з файлу або відновлює їх з API, якщо файл відсутній або порожній.
    """
    global active_positions

    # Блокування для уникнення конфліктів при оновленні активних позицій
    with active_positions_lock:
        log("⚡ Відновлення позицій...")

        if not force_api:
            if os.path.exists(POSITIONS_FILE):
                log("⚡ Відновлення позицій з файлу...")
                try:
                    with open(POSITIONS_FILE, "r") as f:
                        active_positions = json.load(f)
                    log(f"✨ Отримано {len(active_positions)} ордерів з файлу")
                except Exception as e:
                    log(f"❌ Помилка відновлення: {e}")

        if force_api or not active_positions:
            log("⚡ Відновлення позицій з API...")
            try:
                # Отримання балансу гаманця
                balance_qty, _, _ = get_wallet_balance(log_output=False)

                log("⛽ Отримання історії ордерів...")
                history = session.get_order_history(
                    category="spot",
                    symbol=SYMBOL,
                    limit=50,
                    status="Filled",
                    execType="Trade"
                )
                if history.get('retCode') != 0:
                    raise ValueError(f"❌ Помилка отримання історії ордерів: {history.get('retMsg')}")
                trades = history['result']['list']
                log(f"✨ Отримано {len(trades)} ордерів з історії")

                # Фільтрація та сортування купівельних ордерів
                buys = [t for t in trades if t['side'] == 'Buy']
                buys.sort(key=lambda x: x['createdTime'], reverse=True)  # Сортуємо за часом створення
                # with open("buys.json", "w") as f:
                #     json.dump(buys, f, indent=4)

                # Відновлення позицій з історії ордерів
                restored = []
                if balance_qty > 0:
                    for b in buys:
                        fee = float(b['cumFeeDetail'][base_coin]) if base_coin in b['cumFeeDetail'] else 0
                        qty = float(b['cumExecQty']) - fee # Віднімаємо комісію в BTC
                        if balance_qty >= qty:
                            restored.append({
                                "order_id": b['orderId'],
                                "date": datetime.fromtimestamp(int(b['createdTime'])/1000).strftime("%Y-%m-%d %H:%M:%S"),
                                "side": "Buy",
                                "price": b['avgPrice'],
                                "qty": format(qty, f'.{base_precision+2}f'),
                                "fee": format(fee, f'.{base_precision+2}f')
                            })
                            balance_qty -= qty
                        else:
                            break

                # Сортуємо за ціною (від більшої до меншої)
                restored.sort(key=lambda x: float(x['price']), reverse=True)

                # Оновлення активних позицій
                active_positions = restored

                # Збереження позицій у файл
                with open(POSITIONS_FILE, "w") as f:
                    json.dump(active_positions, f, indent=4)
            except Exception as e:
                log(f"❌ Помилка відновлення: {e}")

        if active_positions:
            log(f"✨ Активні позиції ({len(active_positions)} шт.): {active_positions}")
        else:
            log("⚠️ Позицій для відновлення не знайдено")

def get_wallet_balance(log_output=True):
    """
    Отримання балансу гаманця для вказаної монети.
    :return: Баланс монети (кількість, USD вартість, загальна вартість)
    """
    if log_output:
        log("⛳ Отримання балансу гаманця...")

    balance_info = session.get_wallet_balance(accountType="UNIFIED", coin=base_coin)
    if balance_info.get('retCode') != 0:
        raise ValueError(f"❌ Помилка отримання балансу: {balance_info.get('retMsg')}")

    balance_qty = float(balance_info['result']['list'][0]['coin'][0]['walletBalance'])
    usd_value = float(balance_info['result']['list'][0]['coin'][0]['usdValue'])
    total_equity = float(balance_info['result']['list'][0]['totalEquity'])

    if log_output:
        message = f"⛳ Баланс: {format(balance_qty, f'.{base_precision+2}f')} {base_coin}"
        message += f" (${format(usd_value, '.2f')})"
        message += f", загальна еквіті: {format(total_equity, '.2f')} {quote_coin}"
        log(message)

    return balance_qty, usd_value, total_equity

def handle_message(message):
    """
    Обробка повідомлень з WebSocket стріму тікерів.
    :param message: Повідомлення
    """
    # Ігноруємо повідомлення, якщо прийом вимкнено
    if not accept_messages:
        # log("⚠️ Прийом повідомлень тимчасово вимкнено")
        return

    # Додаємо повідомлення у чергу для обробки
    if 'data' in message:
        data_queue.put(message['data'])

def worker(stop_event):
    """
    Обробка повідомлень з черги.
    """
    global accept_messages

    # Очікуємо нове повідомлення в черзі
    while not stop_event.is_set():
        data = data_queue.get()
        if data is None:
            log("⚙️ Робочий потік зупинено")
            break

        try:
            accept_messages = False # Блокування прийому нових повідомлень під час обробки
            process_data(data)
        except Exception as e:
            log(f"❌ Помилка обробки даних: {e}")
        finally:
            accept_messages = True # Розблокування прийому повідомлень після обробки
            data_queue.task_done()

def process_data(data):
    """
    Обробка отриманих даних.
    :param data: Дані повідомлення
    """
    global last_price

    try:
        # Отримуємо поточну ціну
        current_price = float(data['lastPrice'])

        # Перевірка останньої (попередньої) отриманої ціни
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
        next_sell_price = min([float(p['price']) + PROFIT_TARGET for p in active_positions]) if active_positions else None

        # Виведення інформації
        message = f"Минула ціна: {f"{last_price:.2f}"}"
        message += f" | Поточна ціна: {f"{current_price:.2f}"}"
        message += f" | Позицій: {len(active_positions)}"
        message += f" | Наст.купівля знизу: {f"{next_lower_buy_level:.2f}"}"
        message += f" | Наст.купівля зверху: {f"{next_upper_buy_level:.2f}"}"
        message += f" | Наст.продаж: {f"{next_sell_price:.2f}" if next_sell_price else "немає"}"
        log(message, file_output=False)

        # Періодично логуєм в файл
        if int(datetime.now().timestamp()) % 60 == 0:
            log(message, console_output=False)

        # Оновлення останньої ціни
        last_price = current_price
    except KeyError:
        pass # Ігноруємо неочікувані повідомлення
    except Exception as e:
        log(f"❌ Помилка в обробці WebSocket повідомлення: {e}")

def check_and_execute_sell(current_price):
    """
    Перевіряє активні позиції на досягнення цільового рівня прибутку та виконує продаж.
    :param current_price: Поточна ціна для порівняння з рівнями продажу
    """
    global last_price

    for pos in active_positions:
        sell_price = float(pos['price']) + PROFIT_TARGET
        if current_price >= sell_price:
            try:
                log(f"⚾ Ціна {current_price:.2f} досягла рівня продажу {sell_price:.2f} для позиції купівлі по {pos['price']}")

                # Отримання балансу гаманця
                balance_qty, _, _ = get_wallet_balance()

                # Округлюємо кількість ВНИЗ до потрібної точності
                factor = 10 ** base_precision

                # Доступний баланс
                balance_qty = math.floor(balance_qty * factor) / factor

                # Потрібна кількість для продажу
                needed_qty = float(pos['qty'])
                needed_qty = math.floor(needed_qty * factor) / factor
                log(f"✊ Потрібно продати: {format(needed_qty, f'.{base_precision+2}f'):} {base_coin}")

                # Перевіряємо, чи вистачає балансу
                if balance_qty < needed_qty:
                    log(f"⚠️ Недостатньо балансу {base_coin}: Треба {format(needed_qty, f'.{base_precision+2}f')}, є {format(balance_qty, f'.{base_precision+2}f')}")
                    # Тут можна або пропустити, або спробувати продати те, що є:
                    # continue
                    needed_qty = balance_qty

                if needed_qty <= 0:
                    log(f"❌ Потрібна кількість {base_coin} для продажу недостатня")
                    # Оновлюємо позиції з API, щоб уникнути розбіжностей
                    load_positions()
                    break

                log(f"⚽ Спроба продажу по {current_price}...")
                order = session.place_order(
                    category="spot",
                    symbol=SYMBOL,
                    side="Sell",
                    orderType="Market",
                    qty=format(needed_qty, f'.{base_precision}f')
                )
                if order.get('retCode') != 0:
                    log(f"❌ Помилка розміщення ордеру: {order.get('retMsg')}")
                    continue

                order_id = order['result']['orderId']
                log(f"⛵ Ордер {order_id} розміщено. Очікування виконання...")
                is_filled = False

                # Перевірка статусу
                for _ in range(RETRY_NUMBER):
                    time.sleep(RETRY_DELAY) # Затримка перед перевіркою

                    log("⛽ Отримання історії ордерів...")
                    history = session.get_order_history(
                        category="spot",
                        symbol=SYMBOL,
                        orderId=order_id
                    )
                    if history.get('retCode') != 0:
                        log(f"❌ Помилка отримання історії ордерів: {history.get('retMsg')}")
                        continue
                    # log(f"Історія ордеру: {check}")

                    # Отримуємо інформацію про ордер з історії
                    trades = history['result']['list']
                    if not trades:
                        log(f"⚠️ Ордер {order_id} не знайдено в історії ордерів")
                        continue

                    order_data = trades[0]
                    log(f"⛎ Ордер {order_data['orderId']} отримано з історії")

                    # Перевіряємо статус ордера
                    status = order_data['orderStatus']
                    if status == "Filled":
                        log(f"✅ Ордер {order_data['orderId']} виконано")

                        # Оновлюємо позиції з API, щоб уникнути розбіжностей
                        load_positions()

                        # Отримуємо реальну ціну виконання
                        exec_price = float(order_data.get('avgPrice', current_price))
                        profit = (exec_price - float(pos['price'])) * float(pos['qty'])

                        # Отримуємо час виконання
                        exec_time = order_data.get('execTime', 0)
                        exec_time = datetime.fromtimestamp(int(exec_time)/1000) if exec_time else datetime.now()
                        timedelta = exec_time - datetime.strptime(pos['date'], '%Y-%m-%d %H:%M:%S')

                        message = f"⚽ Продано {pos['qty']} {base_coin} по ціні {exec_price} {quote_coin}"
                        message += f", що становить {format(float(pos['qty']) * exec_price, '.2f')} {quote_coin}"
                        message += f", прибуток {format(profit, '.2f')} {quote_coin}."
                        message += f" Ордер був розміщений {pos['date']} та тривав до {exec_time.strftime('%Y-%m-%d %H:%M:%S')},"
                        message += f" загальний час утримання позиції склав {format_timedelta(timedelta)}."
                        log(message)

                        # Записуємо в лог-файл
                        log_trade(pos, "SELL", exec_price, profit=profit)

                        # Оповіщаємо в Telegram
                        send_telegram(message)

                        # Скидаємо останню ціну
                        last_price = 0

                        is_filled = True
                        break
                    elif status in ["Cancelled", "Rejected"]:
                        log(f"❎ Ордер {order_data['orderId']} скасовано або відхилено, статус: {status}")
                        break
                    else:
                        log(f"❎ Ордер {order_data['orderId']} не виконано, статус: {status}")
                        continue

                if not is_filled:
                    log(f"❎ Ордер {order_data['orderId']} розміщено, але статус 'Filled' не отримано.")

            except Exception as e:
                log(f"❌ КРИТИЧНА ПОМИЛКА при продажі: {e}")

def format_timedelta(timedelta):
    """
    Форматує timedelta об'єкт в читабельний формат.
    :param timedelta: timedelta об'єкт
    :return: Рядок з форматованим часом (наприклад, "2д 3год 15хв 25сек")
    """
    total_seconds = int(timedelta.total_seconds())
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    parts = []
    if days > 0:
        parts.append(f"{days}{'д'}")
    if hours > 0:
        parts.append(f"{hours}{'год'}")
    if minutes > 0:
        parts.append(f"{minutes}{'хв'}")
    if seconds > 0 or not parts:
        parts.append(f"{seconds}{'сек'}")

    return " ".join(parts)

def get_next_lower_buy_level():
    """
    Розрахунок наступного нижнього рівня купівлі.
    :return: Розрахований рівень купівлі
    """
    # Розрахунок рівня на основі кроку та зсуву для поточної ціни
    level = ((last_price - LEVEL_OFFSET) // LEVEL_STEP) * LEVEL_STEP + LEVEL_OFFSET

    # Якщо немає активних позицій, повертаємо розрахований рівень
    if not active_positions:
        return level

    # Якщо тип сітки лінійний, повертаємо розрахований рівень
    # if GRID_TYPE == GridType.LINEAR:
    #     return level

    # Коригування рівня відповідно до послідовності Фібоначчі
    if GRID_TYPE == GridType.FIBO:
        count = len(active_positions)
        prev_fibo = 0
        for curr_fibo in FIBO_NUMBERS:
            if count < curr_fibo:
                diff = curr_fibo - prev_fibo
                if diff > 1:
                    last_position = min(active_positions, key=lambda x: float(x['price'])) # Отримуємо позицію з найменшою ціною
                    last_position_level = (float(last_position['price']) // LEVEL_STEP) * LEVEL_STEP + LEVEL_OFFSET
                    level = last_position_level - LEVEL_STEP * diff # Зсув рівня вниз
                break
            prev_fibo = curr_fibo

    # Перевірка, чи є активна позиція на цьому рівні, і якщо так, зсув рівня вниз на крок
    for p in active_positions:
        p_level = (float(p['price']) // LEVEL_STEP) * LEVEL_STEP + LEVEL_OFFSET
        if abs(level - p_level) < (LEVEL_STEP / 2):
            level -= LEVEL_STEP # Зсув рівня вниз
            # log(f"Позиція з ордером {p['order_id']} по ціні {p['price']} на рівні {p_level} вже була відкрита, зсув рівня до {level}")
            break

    return level

def get_next_upper_buy_level():
    """
    Розрахунок наступного верхнього рівня купівлі.
    :return: Розрахований рівень купівлі
    """
    max_price = max([float(p['price']) for p in active_positions]) if active_positions else None
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
    global last_price

    # Визначення рівня купівлі, який було перетнуто
    level = None
    if last_price > lower_buy_level and current_price <= lower_buy_level:
        log(f"✋ Перетин нижнього рівня купівлі {lower_buy_level} вниз: остання ціна {last_price}, поточна ціна {current_price}")
        level = lower_buy_level
    elif last_price < upper_buy_level and current_price >= upper_buy_level:
        log(f"✋ Перетин верхнього рівня купівлі {upper_buy_level} вверх: остання ціна {last_price}, поточна ціна {current_price}")
        level = upper_buy_level
    else:
        return # Рівень купівлі не перетнуто

    try:
        log(f"⚽ Спроба купівлі на рівні {level}...")
        order = session.place_order(
            category="spot",
            symbol=SYMBOL,
            side="Buy",
            orderType="Market",
            qty=str(ORDER_SIZE) # Для Spot Market Buy вказується сума в USDT
        )
        if order.get('retCode') != 0:
            log(f"❌ Помилка розміщення ордеру: {order.get('retMsg')}")
            return

        order_id = order['result']['orderId']
        log(f"⛵ Ордер {order_id} розміщено. Очікування виконання...")
        is_filled = False

        # Перевірка статусу
        for _ in range(RETRY_NUMBER):
            time.sleep(RETRY_DELAY) # Затримка перед перевіркою

            log("⛽ Отримання історії ордерів...")
            history = session.get_order_history(
                category="spot",
                symbol=SYMBOL,
                orderId=order_id
            )
            if history.get('retCode') != 0:
                log(f"❌ Помилка отримання історії ордерів: {history.get('retMsg')}")
                continue
            # log(f"Історія ордерів: {history}")

            # Отримуємо інформацію про ордер з історії
            trades = history['result']['list']
            if not trades:
                log(f"⚠️ Ордер {order_id} не знайдено в історії ордерів")
                continue
            
            order_data = trades[0]
            log(f"⛎ Ордер {order_data['orderId']} отримано з історії")

            # Перевіряємо статус ордера
            status = order_data['orderStatus']
            if status == "Filled":
                log(f"✅ Ордер {order_data['orderId']} виконано")

                # Оновлюємо позиції з API, щоб уникнути розбіжностей
                load_positions()

                # Отримуємо реальні дані виконання
                pos = next((p for p in active_positions if p['order_id'] == order_data['orderId']), None)
                if not pos:
                    log(f"❌ Виконаний ордер {order_data['orderId']} не знайдено серед активних позицій")
                    continue

                exec_price = float(pos['price'])
                exec_qty = float(pos['qty'])
                commission = float(pos['fee'])

                message = f"⛺ Куплено {exec_qty} {base_coin} по ціні {format(exec_price, '.2f')} {quote_coin}"
                message += f", що становить {format(exec_qty * exec_price, '.2f')} {quote_coin}"
                message += f" включно з комісією {format(commission * exec_price, '.2f')} {quote_coin}."
                log(message)

                # Записуємо в лог-файл
                log_trade(pos, "BUY", exec_price)

                # Оповіщаємо в Telegram
                send_telegram(message)

                # Скидаємо останню ціну
                last_price = 0

                is_filled = True
                break
            elif status in ["Cancelled", "Rejected"]:
                log(f"❎ Ордер {order_data['orderId']} скасовано або відхилено, статус: {status}")
                break
            else:
                log(f"❎ Ордер {order_data['orderId']} не виконано, статус: {status}")
                continue

        if not is_filled:
            log(f"❎ Ордер {order_data['orderId']} розміщено, але статус 'Filled' не отримано.")

    except Exception as e:
        log(f"❌ КРИТИЧНА ПОМИЛКА при купівлі: {e}")

def log(message="", end="\n", flush=False, empty_line=False, datetime_prefix=True, console_output=True, file_output=True):
    """
    Логування роботи бота.
    :param message: Текст логування
    """
    # Формування тексту для логування
    if not empty_line and datetime_prefix:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message = f"[{timestamp}] {message}"

    # Вивід в консоль
    if console_output:
        print(message, end=end, flush=flush)

    # Вивід в файл
    if file_output:
        with open(WORK_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(message + end)
            if flush:
                f.flush()

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
    message = f"[{timestamp}] {action.upper()}{' ' if action.upper() == 'BUY' else ''} | {SYMBOL} | Price: {exec_price:.2f} | Qty: {pos['qty']}"

    # Якщо це продаж, додаємо ціну купівлі та профіт
    if action.upper() == "SELL":
        message += f" | BuyPrice: {pos['price']} | Profit: {profit:.4f}"

    # Запис у файл
    with open(TRADE_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(message + "\n")

def send_telegram(message):
    """
    Відправка повідомлення в Telegram.
    :param message: Текст повідомлення
    """
    if not TELEGRAM_NOTIFICATIONS:
        return

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log("❌ Telegram токен або чат ID не встановлено.")
        return

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
        requests.post(url, data=data)
    except Exception as e:
        log(f"❌ Помилка Telegram: {e}")

def main():
    """
    Головна функція для запуску бота.
    Вона ініціалізує з'єднання та підписується на стрім тікерів.
    """
    global session

    log(empty_line=True)
    log(f"⚪ Бот запущений та готовий до торгівлі {SYMBOL}")

    # Ініціалізація сесії API
    try:
        log("⛅ Підключення до біржі ", end="")
        session = HTTP(testnet=False, demo=DEMO_MODE, api_key=API_KEY, api_secret=API_SECRET)
        log("виконано успішно", datetime_prefix=False)
    except Exception as e:
        log(f"❌ завершено з помилкою: {e}")
        return

    # Отримання точності символу
    load_instruments_info()

    # Завантаження поточних позицій
    load_positions()

    # Запуск робочого потоку для обробки черги повідомлень з веб-сокета
    worker_stop_event = threading.Event()
    worker_thread = threading.Thread(target=worker, args=(worker_stop_event,), daemon=True)
    worker_thread.start()
    log("⚙️ Робочий потік запущено")

    # Ініціалізація веб-сокета для отримання тікерів
    try:
        log("⛅ Підписка на стрім тікерів ", end="")
        ws = WebSocket(testnet=False, channel_type="spot", api_key=API_KEY, api_secret=API_SECRET)
        ws.ticker_stream(symbol=SYMBOL, callback=handle_message)
        log("виконано успішно", datetime_prefix=False)
    except Exception as e:
        log(f"❌ завершено з помилкою: {e}")
        return

    # Утримання програми в активному стані
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        worker_stop_event.set()
        worker_thread.join()
        log("⚫ Бот зупинено")

# Точка входу
if __name__ == "__main__":
    main()
