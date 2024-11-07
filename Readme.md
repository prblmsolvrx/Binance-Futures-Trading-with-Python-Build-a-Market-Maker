# Binance Futures Grid Trading Bot

This repository contains a Python script to execute a grid trading bot on Binance Futures. The bot uses multiple grids of limit orders to automate buy and sell trades based on predefined parameters, leveraging Binance's API to manage orders and monitor positions in real-time.

## Features

- **Grid Trading**: Automatically places limit orders in a grid around the current market price.
- **Leverage Configuration**: Set leverage for each symbol.
- **Take-Profit Levels**: Calculates and places take-profit orders based on open positions.
- **Threaded Execution**: Runs multiple trading bots concurrently for different symbols.
- **Real-Time Monitoring**: Continuously checks positions and adjusts orders to maintain the grid strategy.

## Prerequisites

- Python 3.x
- Binance Futures account with API access
- Binance API keys with Futures permissions

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/yourrepo.git
   cd yourrepo
   ```

2. Install the required libraries:
   ```bash
   pip install pandas binance python-dotenv
   ```

3. **Add your Binance API keys**:
   - Create a `key_file.py` in the project directory:
     ```python
     binance_testnet_api_key = 'YOUR_BINANCE_TESTNET_API_KEY'
     binance_testnet_api_secret = 'YOUR_BINANCE_TESTNET_API_SECRET'
     ```

4. **Set up logging** (optional):
   - The script is configured to log to the console with `INFO` level. Adjust `logging.basicConfig` if you need to change the format or logging level.

## Usage

### 1. Initialize and Configure the Bot

You can initialize the bot with custom parameters for each trading symbol. For example:

```python
bot1 = initialize_bot(
    symbol="BTCUSDT",
    no_of_decimal_places=1,
    volume=0.01,
    proportion=0.04,
    take_profit_percent=5,
    num_of_grids=10,
    leverage=10,
    testnet=True
)
```

### 2. Start the Bots

Each bot runs in a separate thread for parallel execution. Here's how to start two bots concurrently:

```python
# Initialize bots with specified parameters
bot1 = initialize_bot("BTCUSDT", 1, 0.01, 0.04, 5, 10, leverage=10, testnet=True)
bot2 = initialize_bot("ETHUSDT", 2, 0.01, 0.04, 5, 10, leverage=10, testnet=True)

# Start bots in separate threads
t1 = Thread(target=run_bot, args=(bot1,))
t2 = Thread(target=run_bot, args=(bot2,))

t1.start()
t2.start()

# Join threads to ensure both bots complete
t1.join()
t2.join()
```

### 3. Main Bot Functions

#### `initialize_bot()`
Initializes the bot configuration with leverage and grid settings for the specified symbol.

#### `get_balance()`
Retrieves and logs the account balance.

#### `place_limit_order()`
Places a limit order on Binance Futures.

#### `cancel_orders()`
Cancels open orders for the symbol, optionally filtering by side.

#### `get_position_direction()`
Returns the current position direction (Long, Short, or FLAT).

#### `get_mark_price()`
Retrieves the current mark price for the symbol.

#### `draw_grid()`
Draws a grid of buy and sell limit orders around the current price.

#### `calculate_take_profit_level()`
Calculates the take-profit price level for the current position.

#### `place_take_profit_order()`
Places a take-profit order for the open position.

#### `run_bot()`
The main loop to run the trading bot, manage orders, and track the position.

## Example Workflow

The bot:
1. Checks for open orders and places new grid orders if none are found.
2. Monitors open positions and cancels opposing orders if a position is detected.
3. Calculates a take-profit level and places a take-profit order.
4. Continuously monitors the position, adjusting orders as needed.

## Configuration

You can adjust the following parameters in `initialize_bot()`:

- `symbol`: Trading pair, e.g., `"BTCUSDT"`.
- `no_of_decimal_places`: Number of decimal places for rounding prices.
- `volume`: Amount of cryptocurrency to trade per order.
- `proportion`: Grid proportion, adjusting the distance between orders.
- `take_profit_percent`: Target percentage for take-profit orders.
- `num_of_grids`: Number of grid levels to create above and below the market price.
- `leverage`: Leverage level for the symbol.
- `testnet`: Set to `True` to use Binance Testnet.

## Troubleshooting

1. **Error in Leveraging**: Ensure leverage is configured in your Binance Futures account.
2. **API Connection Issues**: Verify API keys in `key_file.py` and ensure permissions.
3. **Error Logs**: Review `logging` output to debug.

## License

MIT License.

## Disclaimer

**Trading cryptocurrencies carries a high level of risk.** Use this bot at your own discretion. The creators are not responsible for any financial loss.
```

This `README.md` file explains each function, usage, configuration options, and troubleshooting steps for your trading bot. Let me know if you want to add more specific details!