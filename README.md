# Gridmaton
Automated Crypto Trading Bot

## Goal

Gridmaton is an automated cryptocurrency trading bot designed to execute algorithmic trades on the crypto exchange on Spot market. It monitors price movements of crypto assets (default: BTCUSDT) and automatically places buy orders when prices cross predefined support levels, then sells at target profit levels. The bot implements a grid trading strategy with configurable round levels and profit targets, maintaining active positions in a JSON file for persistence and recovery.

## Prerequisites

- **Python 3.x** - The bot is written in Python
- **Bybit API Account** - You need a Bybit account with API access enabled
  - Create API keys in your Bybit account settings
  - Ensure your API keys have permissions for spot trading
- **Internet Connection** - Required for WebSocket connection to exchange
- **pip** - Python package manager (usually included with Python)

## Supported exchanges

- Bybit (Spot Market)

## Configuration

### Step 1: Create .env File

Copy the `.env.example` file to create your `.env` configuration file:

```bash
cp .env.example .env
```

Or on Windows (PowerShell):

```powershell
Copy-Item .env.example .env
```

### Step 2: Add Your API Credentials

Edit the `.env` file and add your Bybit API credentials:

```
API_KEY=your_api_key
API_SECRET=your_api_secret
```

### Step 3: Install Dependencies

Install required Python packages:

```bash
pip install -r requirements.txt
```

### Step 4: Configure Bot Parameters (Optional)

Edit `main.py` to customize trading parameters:

| Parameter            | Default   | Description                                 |
| -------------------- | --------- | ------------------------------------------- |
| `DEMO_MODE`          | `True`    | Set to `False` to trade with real funds     |
| `SYMBOL`             | `BTCUSDT` | Trading pair (e.g., `ETHUSDT`, `BNBUSDT`)   |
| `ORDER_SIZE_USDT`    | `10`      | Size of each buy order in USDT              |
| `PROFIT_TARGET`      | `1000`    | Profit target per position (in price units) |
| `ROUND_LEVEL_STEP`   | `1000`    | Distance between buy levels                 |
| `ROUND_LEVEL_OFFSET` | `900`     | Offset adjustment for buy levels            |

## Usage

### Start the Bot

Run the bot with:

```bash
python main.py
```

The bot will start and connect to the Bybit exchange. It will then monitor the price of selected coin and execute trades based on the defined strategy.

### Monitor Bot Activity

The bot will display real-time information in the console:
- Current and previous prices
- Number of active positions
- Next buy/sell price level
- Execution acknowledgements

### Bot Output Example

```
🟢 Бот запущений та готовий до торгівлі BTCUSDT.
🤺 Точність символу BTCUSDT: 8 знаків після коми.
📢 Активні позиції (1 шт.): [{"buy_price": 83888.1, "qty": "0.000119"}]
🔄 Підключення до біржи виконано успішно.
Минула ціна: 83900.00 | Поточна ціна: 83905.00 | Позицій: 1 | Наст.купівля: 82900.00 | Наст.продаж: 84900.00
```

### Stop the Bot

Press `Ctrl+C` in the terminal to stop the bot gracefully.

### View Trade History

Check the `trade.log` file for detailed trading history:

```bash
cat trade.log
```

### View Active Positions

Active trading positions are saved in `positions.json`:

```bash
cat positions.json
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

- **main.py** - Main bot application with trading logic
- **positions.json** - Current active trading positions (auto-managed)
- **trade.log** - Historical record of all executed trades
- **.env** - API credentials and configuration (create from .env.example)
- **requirements.txt** - Python package dependencies
- **README.md** - This documentation

## Attention

**⚠️ WARNING: TRADING INVOLVES SUBSTANTIAL RISK OF LOSS**

1. **Use at Your Own Risk** - This bot is provided as-is without any warranties. Use it entirely at your own risk. Past performance does not guarantee future results.

2. **Real Money Risk** - When `DEMO_MODE` is set to `False`, this bot will execute real trades using real funds. Incorrect configuration or unexpected market conditions can result in significant financial losses.

3. **Not Financial Advice** - This bot is not intended as financial advice. Do not use it to trade with funds you cannot afford to lose.

4. **Test Thoroughly** - Always test the bot extensively in demo mode before using it with real money. Verify API credentials and trading parameters carefully.

5. **API Key Security** - Never share your `.env` file or API credentials. Treat them as sensitive information. Use API keys with restricted trading permissions if possible.

6. **Network Risk** - The bot relies on continuous internet connectivity. Network failures may prevent position closure or trade execution.

7. **Exchange Risk** - The bot depends on Bybit exchange availability and API reliability. Exchange outages or API changes may affect operation.

8. **Bugs and Issues** - While efforts have been made to ensure accuracy, bugs may exist. Monitor the bot's activity regularly.

9. **Market Risk** - Volatile market conditions can lead to rapid price movements and unexpected trading outcomes, especially during volatile periods.

10. **Compliance** - Ensure compliance with local regulations and your country's cryptocurrency trading laws before using this bot.

**By using this bot, you acknowledge that you have read this disclaimer and assume full responsibility for any trading losses or outcomes.**
