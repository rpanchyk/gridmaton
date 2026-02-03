import time
from datetime import datetime
import math
import json
import os
import requests
from dotenv import load_dotenv
from pybit.unified_trading import HTTP, WebSocket

# Завантаження змінних оточення
load_dotenv()

# Конфігурація
API_KEY = os.getenv('API_KEY')
API_SECRET = os.getenv('API_SECRET')
TELEGRAM_NOTIFICATIONS = os.getenv("TELEGRAM_NOTIFICATIONS", 'False').lower() in ('true', '1')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# Перевірка наявності ключів API
if not API_KEY or not API_SECRET:
    raise ValueError("Ключі API_KEY та API_SECRET мають бути встановлені у файлі .env")

# Статичні налаштування
DEMO_MODE = True
SYMBOL = "BTCUSDT"
ORDER_SIZE_USDT = 10
PROFIT_TARGET = 1000
ROUND_LEVEL_STEP = 1000
ROUND_LEVEL_OFFSET = 500
POSITIONS_FILE = "positions.json"
TRADE_LOG_FILE = "trade.log"

# Ініціалізація сесії та активних позицій
session = HTTP(testnet=False, demo=DEMO_MODE, api_key=API_KEY, api_secret=API_SECRET)
active_positions = []

def get_symbol_precision(symbol):
    """
    Отримання точності символу.
    :param symbol: Символ
    :return: Точність символу
    """
    info = session.get_instruments_info(category="spot", symbol=symbol)
    if len(info['result']['list']) == 0:
        raise ValueError("Невірний символ або відсутня інформація про нього.")
    res = info['result']['list'][0]['lotSizeFilter']['basePrecision']
    return len(res.split('.')[1]) if '.' in res else 0

def save_positions():
    """
    Зберігає активні позиції у файлі.
    """
    global active_positions
    with open(POSITIONS_FILE, "w") as f:
        json.dump(active_positions, f, indent=4)

def load_positions(precision):
    """
    Завантажує активні позиції з файлу або відновлює їх з API, якщо файл відсутній або порожній.
    :param precision: Кількість знаків після коми для округлення кількості
    """
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
        # Отримання балансу монети
        base_coin = SYMBOL.replace("USDT", "")
        balance_info = session.get_wallet_balance(accountType="UNIFIED", coin=base_coin)
        if balance_info.get('retCode') != 0:
            raise ValueError(f"Помилка отримання балансу: {balance_info.get('retMsg')}")
        holding_qty = float(balance_info['result']['list'][0]['coin'][0]['walletBalance'])
        print(f"Баланс: {holding_qty} {base_coin}")

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
        # history_json = json.dumps(buys, indent=4)
        # with open('history.json', "w", encoding="utf-8") as f:
        #     f.write(history_json)

        # Відновлення позицій з історії ордерів
        restored = []
        if holding_qty > 0:
            for b in buys:
                qty = float(b['cumExecQty'])
                if holding_qty >= qty:
                    restored.append({
                        "date": datetime.fromtimestamp(int(b['createdTime'])/1000).strftime("%Y-%m-%d %H:%M:%S"),
                        "buy_price": float(b['avgPrice']),
                        "qty": format(qty, f'.{precision}f')
                    })
                    holding_qty -= qty

        # Оновлення активних позицій
        active_positions = restored
        active_positions.sort(key=lambda x: x['date'])  # Сортуємо за датою

        if not active_positions:
            print("⚠️ Позицій для відновлення не знайдено.")
        else:
            save_positions()
    except Exception as e:
        print(f"❌ Помилка відновлення: {e}")

def check_and_execute_buy(last_price, current_price, precision):
    """
    Перевіряє ціну та виконує купівлю, якщо ціна перетинає рівень і немає активних позицій на цьому рівні.
    :param last_price: Остання ціна для визначення рівня
    :param current_price: Поточна ціна для порівняння з рівнем
    :param precision: Кількість знаків після коми для округлення кількості
    """
    global active_positions
    level = ((last_price - ROUND_LEVEL_OFFSET) // ROUND_LEVEL_STEP) * ROUND_LEVEL_STEP + ROUND_LEVEL_OFFSET

    # Перевірка умови перетину рівня та відсутності дублікатів
    if (last_price > level and current_price <= level) or (last_price < level and current_price >= level):
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
                                    "date": datetime.fromtimestamp(int(order_data['createdTime'])/1000).strftime("%Y-%m-%d %H:%M:%S"),
                                    "buy_price": exec_price,
                                    "qty": format(exec_qty, f'.{precision}f')
                                }
                                active_positions.append(new_pos)
                                active_positions.sort(key=lambda x: x['date'])  # Сортуємо за датою
                                save_positions()

                                message = f"📥 Куплено {exec_qty} {SYMBOL.replace('USDT', '')} по ціні {exec_price} {SYMBOL.replace('BTC', '')}"
                                message += f", що становить {format(float(order_data.get('qty', 0)), '.2f')} {SYMBOL.replace('BTC', '')}"
                                message += f" включно з комісією {format(commission * exec_price, '.2f')} {SYMBOL.replace('BTC', '')}."
                                print(message)

                                # Записуємо в лог-файл
                                log_trade(new_pos, "BUY", exec_price)

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

def check_and_execute_sell(current_price, precision):
    """
    Перевіряє активні позиції на досягнення цільового рівня прибутку та виконує продаж.
    :param current_price: Поточна ціна для порівняння з рівнями продажу
    :param precision: Кількість знаків після коми для округлення
    """
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
                                # Видаляємо позицію зі списку активних та зберігаємо файл
                                active_positions.remove(pos)
                                save_positions()

                                # Отримуємо реальну ціну виконання
                                exec_price = float(order_data.get('avgPrice', current_price))
                                profit = (exec_price - pos['buy_price']) * float(pos['qty'])

                                # Отримуємо час виконання
                                exec_time = order_data.get('execTime', 0)
                                exec_time = datetime.fromtimestamp(int(exec_time)/1000) if exec_time else datetime.now()
                                timedelta = exec_time - datetime.strptime(pos['date'], '%Y-%m-%d %H:%M:%S')

                                message = f"💰 Продано {pos['qty']} {SYMBOL.replace('USDT', '')} по ціні {exec_price} {SYMBOL.replace('BTC', '')}"
                                message += f", що становить {format(float(pos['qty']) * exec_price, '.2f')} {SYMBOL.replace('BTC', '')}"
                                message += f", прибуток {format(profit, '.2f')} {SYMBOL.replace('BTC', '')}."
                                message += f" Ордер був розміщений {pos['date']} і тривав до {exec_time.strftime('%Y-%m-%d %H:%M:%S')},"
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
                else:
                    print(f"❌ Помилка ордеру: {order.get('retMsg')}")

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

def handle_message(message):
    """
    Обробка повідомлень з WebSocket стріму тікерів.
    :param message: Дані повідомлення
    """
    global precision, active_positions, last_price
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
    """
    Головна функція для запуску бота.
    Вона ініціалізує з'єднання, завантажує позиції та підписується на стрім тікерів.
    """
    print(f"🟢 Бот запущений та готовий до торгівлі {SYMBOL}.")

    # Отримання точності символу
    global precision
    precision = get_symbol_precision(SYMBOL)
    print(f"🤺 Точність символу {SYMBOL}: {precision} знаків після коми.")

    # Завантаження поточних позицій
    global active_positions
    load_positions(precision)
    if active_positions:
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

# Точка входу
if __name__ == "__main__":
    main()
