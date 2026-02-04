# Gridmaton

Automated Crypto Trading Bot

![Logo](logo.png)

## Introduction

**Gridmaton** is an automated cryptocurrency trading bot designed to execute Grid-based trades on Spot Market.
It monitors price movements of asset and automatically places buy order when price crosses predefined levels and then sells at target profit levels.
Since it works on Spot Market, there is no leverage involved, making it a safer option for traders looking to minimize risk.
All bought assets are held in the exchange account until sold at profit target, so no stop-loss mechanism is implemented and no liquidation risk exists.

## Prerequisites

- **Python 3.x** - The bot is written in Python.
- **Bybit API Account** - You need a Bybit account with API access enabled.
  - Create API keys in account settings.
  - Ensure API keys have permissions for spot trading.

## Supported exchanges

- [Bybit](https://www.bybit.com)

Other exchanges may be supported in future releases.

## Configuration

### Step 1: Install Dependencies

Install required Python packages:

```shell
pip install -r requirements.txt
```

### Step 2: Create .env File

Copy the `.env.example` file to create your `.env` configuration file:

```shell
cp .env.example .env
```

### Step 3: Configure parameters

Edit the `.env` file to set required settings:

| Parameter                | Default   | Description                                    |
| ------------------------ | --------- | ---------------------------------------------- |
| `API_KEY`                | `-`       | Your Bybit API key                             |
| `API_SECRET`             | `-`       | Your Bybit API secret                          |
| `TELEGRAM_NOTIFICATIONS` | `False`   | Set to `True` to enable Telegram notifications |
| `TELEGRAM_TOKEN`         | `-`       | Your Telegram bot token                        |
| `TELEGRAM_CHAT_ID`       | `-`       | Your Telegram chat ID                          |
| `DEMO_MODE`              | `True`    | Set to `False` to trade with real funds        |
| `BASE_COIN`              | `BTC`     | Base coin symbol                               |
| `QUOTE_COIN`             | `USDT`    | Quote coin symbol                              |
| `ORDER_SIZE`             | `10`      | Size of each buy order                         |
| `PROFIT_TARGET`          | `1000`    | Profit target per position                     |
| `LEVEL_STEP`             | `1000`    | Distance between buy levels                    |
| `LEVEL_OFFSET`           | `500`     | Offset adjustment for buy levels               |

## Usage

### Start the Bot

Run the bot with:

```shell
python main.py
```

The bot will start and connect to the exchange with the provided API credentials via WebSocket connection. 
It will then monitor the price of asset and execute trades based on the defined strategy.

### Monitor Bot Activity

The bot will display real-time information in the console:

- Current and previous prices
- Number of active positions
- Next buy/sell price levels
- Trade execution information

### Bot Output Example

```shell
🟢 Бот запущений та готовий до торгівлі BTCUSDT.
🤺 Точність символу BTCUSDT: 6 знаків після коми.
📢 Активні позиції (1 шт.): [{"buy_price": 83888.1, "qty": "0.000119"}]
🔄 Підключення до біржи виконано успішно.
Минула ціна: 83900.00 | Поточна ціна: 83905.00 | Позицій: 1 | Наст.купівля: 82900.00 | Наст.продаж: 84900.00
```

### Stop the Bot

Press `Ctrl+C` in the terminal to stop the bot gracefully. It may takes a few seconds to close active connections.

### View Active Positions

Active trading positions are saved in `positions.json`:

```shell
cat positions.json
```

### View Trade History

Check the `trade.log` file for detailed trading history:

```shell
cat trade.log
```

## Key Features

- **Automatic Price Monitoring** - Continuously monitors asset prices via WebSocket
- **Grid Trading Strategy** - Executes buys at predefined price levels
- **Profit Target Management** - Automatically sells positions when profit target is reached
- **Position Persistence** - Saves active positions to `positions.json` for recovery
- **API Recovery** - Can restore positions from Bybit order history if needed
- **Trade Logging** - Records all trades with timestamps, prices, and profits
- **Demo Mode** - Test trading without real funds
- **Commission Handling** - Accounts for trading fees in position sizing

## Files Overview

- **.env** - API credentials and configuration (create from .env.example)
- **.env.example** - Example environment configuration file
- **.gitignore** - Git ignore file to exclude sensitive files
- **LICENSE** - License information for the project
- **logo.png** - Bot logo image
- **main.py** - Main bot application with trading logic
- **positions.json** - Current active trading positions (auto-managed)
- **README.md** - This documentation
- **requirements.txt** - Python package dependencies
- **trade.log** - Historical record of all executed trades (auto-managed)

## Development

To update `requirements.txt` after code changes with new dependencies, run:

```shell
pip install pipreqs
pipreqs . --force --encoding=utf-8 --mode no-pin
```

## Known Issues

- The issue with connection to exchange:

```
WebSocket Unified V5 (Auth) (wss://stream.bybit.com/v5/public/spot) connection failed. 
Too many connection attempts. pybit will no longer try to reconnect
```

This issue can be fixed by installing or upgrading system certificates:

```shell
python -m pip install --upgrade certifi
python -m pip install --upgrade pip-system-certs
```

## Warning

**⚠️ TRADING INVOLVES SUBSTANTIAL RISK OF LOSS**

1. **Use at Your Own Risk** - This bot is provided as-is without any warranties. Use it entirely at your own risk. Past performance does not guarantee future results.
2. **Real Money Risk** - When `DEMO_MODE` is set to `False`, this bot will execute real trades using real funds. Incorrect configuration or unexpected market conditions can result in significant financial losses.
3. **Not Financial Advice** - This bot is not intended as financial advice. Do not use it to trade with funds you cannot afford to lose.
4. **Test Thoroughly** - Always test the bot extensively in demo mode before using it with real money. Verify API credentials and trading parameters carefully.
5. **API Key Security** - Never share your `.env` file or API credentials. Treat them as sensitive information. Use API keys with restricted trading permissions if possible.
6. **Network Risk** - The bot relies on continuous internet connectivity. Network failures may prevent position closure or trade execution.
7. **Exchange Risk** - The bot depends on exchange availability and API reliability. Exchange outages or API changes may affect operation.
8. **Bugs and Issues** - While efforts have been made to ensure accuracy, bugs may exist. Monitor the bot's activity regularly.
9. **Market Risk** - Volatile market conditions can lead to rapid price movements and unexpected trading outcomes, especially during volatile periods.
10. **Compliance** - Ensure compliance with local regulations and your country's cryptocurrency trading laws before using this bot.

_By using this bot, you acknowledge that you have read this disclaimer and assume full responsibility for any trading losses or outcomes._

## Disclaimer

The software is provided "as is", without warranty of any kind, express or
implied, including but not limited to the warranties of merchantability,
fitness for a particular purpose and noninfringement. in no event shall the
authors or copyright holders be liable for any claim, damages or other
liability, whether in an action of contract, tort or otherwise, arising from,
out of or in connection with the software or the use or other dealings in the
software.
