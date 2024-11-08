
# -----------------------------
# Main Binance HFT Market Maker Bot Script
# -----------------------------
import asyncio
import logging
import logging.handlers
import sys
from dataclasses import dataclass
from typing import Optional, Tuple

from binance import AsyncClient
from binance.enums import *
from binance.exceptions import BinanceAPIException, BinanceRequestException
from binance.helpers import round_step_size

import key_file as k  # Ensure this file is secure and not tracked by version control

# New imports for enhanced terminal output
from rich.live import Live
from rich.table import Table
from rich.console import Console
from rich import box

# -----------------------------
# Logging Configuration
# -----------------------------

# Create a logger for the BinanceBot
logger = logging.getLogger("BinanceBot")
logger.setLevel(logging.DEBUG)  # Set the default logging level to DEBUG for more detailed output

# Define the log message format
formatter = logging.Formatter('%(asctime)s %(levelname)s:%(message)s')

# Prevent adding multiple handlers if they already exist
if not logger.hasHandlers():
    # Console Handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.DEBUG)  # Set logging level for console to DEBUG
    ch.setFormatter(formatter)  # Apply the formatter to console handler
    logger.addHandler(ch)  # Add console handler to the logger

    # File Handler with Rotation
    fh = logging.handlers.RotatingFileHandler(
        'bot.log',  # Log file name
        maxBytes=5*1024*1024,  # Maximum size per log file (5 MB)
        backupCount=5  # Number of backup log files to keep
    )
    fh.setLevel(logging.DEBUG)  # Set logging level for file handler to DEBUG
    fh.setFormatter(formatter)  # Apply the formatter to file handler
    logger.addHandler(fh)  # Add file handler to the logger

# -----------------------------
# Data Classes for Configuration
# -----------------------------

@dataclass
class BotConfig:
    """
    Dataclass to store configuration parameters for each trading bot.
    """
    symbol: str
    no_of_decimal_places: int
    volume: float
    proportion: float  # This will be replaced by tick size based spacing
    take_profit_percent: float
    stop_loss_percent: float  # New field for stop-loss percentage
    num_of_grids: int
    leverage: int = 1
    testnet: bool = False

# -----------------------------
# BinanceBot Class Definition
# -----------------------------

class BinanceBot:
    """
    A class representing a Binance trading bot with grid and take-profit strategies.
    """

    def __init__(self, config: BotConfig):
        """
        Initialize the BinanceBot with the given configuration.

        Args:
            config (BotConfig): Configuration parameters for the bot.
        """
        self.config = config
        self.api_key = k.binance_testnet_api_key  # Directly assign the key
        self.api_secret = k.binance_testnet_api_secret  # Directly assign the secret

        # Check if API keys are set
        if not self.api_key or not self.api_secret:
            logger.error("Binance API keys are missing.")
            print("ERROR: Binance API keys are missing.")
            sys.exit(1)  # Exit the program if API keys are missing
        else:
            print(f"Initialized BinanceBot for {self.config.symbol} with leverage {self.config.leverage}x.")

        self.client: Optional[AsyncClient] = None  # Binance AsyncClient will be initialized later
        self.tick_size: Optional[float] = None  # To store tick size
        self.active_orders = {}  # To track active orders

        # Initialize rich console for attractive terminal output
        self.console = Console()
        self.table = Table(title=f"Trading Data - {self.config.symbol}", box=box.SIMPLE_HEAVY)
        self.table.add_column("Symbol")
        self.table.add_column("Position")
        self.table.add_column("Entry Price")
        self.table.add_column("Mark Price")
        self.table.add_column("Unrealized PnL")
        self.table.add_column("PnL (%)")
        self.table.add_column("Net PnL")

    async def initialize_client(self):
        """
        Initialize the Binance AsyncClient and set leverage for the trading symbol.
        """
        try:
            # Create an asynchronous Binance client
            self.client = await AsyncClient.create(
                api_key=self.api_key,
                api_secret=self.api_secret,
                tld='com',  # Top-level domain (change if using a different Binance domain)
                testnet=self.config.testnet  # Use testnet if specified
            )
            logger.info(f"Initialized Binance client for {self.config.symbol}")

            # Set leverage for the trading symbol
            await self.set_leverage()

            # Retrieve and set tick size
            await self.get_tick_size()
        except BinanceAPIException as e:
            logger.error(f"Binance API Exception during client initialization: {e}")
            sys.exit(1)
        except BinanceRequestException as e:
            logger.error(f"Binance Request Exception during client initialization: {e}")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Unexpected error during client initialization: {e}")
            sys.exit(1)  # Exit the program if client initialization fails

    async def get_tick_size(self):
        """
        Retrieve the tick size for the trading symbol from exchange information.
        """
        try:
            exchange_info = await self.client.futures_exchange_info()
            symbol_info = next((s for s in exchange_info['symbols'] if s['symbol'] == self.config.symbol), None)
            if symbol_info:
                for f in symbol_info['filters']:
                    if f['filterType'] == 'PRICE_FILTER':
                        self.tick_size = float(f['tickSize'])
                        logger.info(f"Tick size for {self.config.symbol} is {self.tick_size}")
                        return
            logger.error(f"Could not retrieve tick size for {self.config.symbol}")
            sys.exit(1)
        except BinanceAPIException as e:
            logger.error(f"Binance API Error fetching exchange info: {e}")
            sys.exit(1)
        except BinanceRequestException as e:
            logger.error(f"Binance Request Error fetching exchange info: {e}")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Unexpected error fetching exchange info: {e}")
            sys.exit(1)

    async def set_leverage(self):
        """
        Set the leverage for the specified trading symbol.
        """
        try:
            response = await self.client.futures_change_leverage(
                symbol=self.config.symbol,
                leverage=self.config.leverage
            )
            logger.info(f"Leverage set to {self.config.leverage}x for {self.config.symbol}")
        except BinanceAPIException as e:
            logger.error(f"Binance API Error setting leverage: {e}")
        except BinanceRequestException as e:
            logger.error(f"Binance Request Error setting leverage: {e}")
        except Exception as e:
            logger.error(f"Unexpected error setting leverage: {e}")

    async def get_position_direction(self) -> str:
        """
        Determine the current position direction: LONG, SHORT, or FLAT.

        Returns:
            str: 'LONG', 'SHORT', or 'FLAT'.
        """
        try:
            positions = await self.client.futures_position_information(symbol=self.config.symbol)
            for position in positions:
                if position['symbol'] == self.config.symbol:
                    position_amt = float(position['positionAmt'])
                    logger.debug(f"Position for {self.config.symbol}: {position_amt}")
                    if position_amt > 0:
                        logger.info(f"Current position is LONG for {self.config.symbol}")
                        return "LONG"
                    elif position_amt < 0:
                        logger.info(f"Current position is SHORT for {self.config.symbol}")
                        return "SHORT"
                    else:
                        logger.info(f"Current position is FLAT for {self.config.symbol}")
                        return "FLAT"
            logger.info(f"No matching symbol found in position information for {self.config.symbol}.")
            return "FLAT"
        except BinanceAPIException as e:
            logger.error(f"Binance API Error determining position direction: {e}")
            return "FLAT"
        except BinanceRequestException as e:
            logger.error(f"Binance Request Error determining position direction: {e}")
            return "FLAT"
        except Exception as e:
            logger.error(f"Error determining position direction: {e}")
            return "FLAT"

    async def get_mark_price(self) -> Optional[float]:
        """
        Retrieve the current mark price for the trading symbol.

        Returns:
            Optional[float]: Current mark price if successful, else None.
        """
        try:
            ticker = await self.client.futures_mark_price(symbol=self.config.symbol)
            price = float(ticker['markPrice'])
            logger.debug(f"Mark price for {self.config.symbol}: {price}")
            return price
        except BinanceAPIException as e:
            logger.error(f"Binance API Error fetching mark price: {e}")
            return None
        except BinanceRequestException as e:
            logger.error(f"Binance Request Error fetching mark price: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching mark price: {e}")
            return None

    async def draw_grid(self):
        """
        Place grid of tight limit buy and sell orders around the current market price.
        """
        current_price = await self.get_mark_price()
        if current_price is None:
            logger.warning("Current price unavailable. Skipping grid drawing.")
            return

        grid_spacing = self.tick_size  # Set grid spacing to tick size for tight spreads
        logger.info(f"Drawing grid with {self.config.num_of_grids} levels at tick size intervals ({grid_spacing}).")

        for i in range(1, self.config.num_of_grids + 1):
            sell_price = round_step_size(
                current_price + (grid_spacing * i),
                step_size=self.tick_size
            )
            buy_price = round_step_size(
                current_price - (grid_spacing * i),
                step_size=self.tick_size
            )
            logger.info(f"Placing SELL limit order at {sell_price} and BUY limit order at {buy_price}.")
            sell_volume = round(100 / current_price, self.config.no_of_decimal_places)
            sell_order = await self.place_limit_order(SIDE_SELL, sell_volume, sell_price)
            buy_volume = round(100 / current_price, self.config.no_of_decimal_places)
            buy_order = await self.place_limit_order(SIDE_BUY, buy_volume, buy_price)
            if sell_order:
                self.active_orders[sell_order['orderId']] = {'side': SIDE_SELL, 'price': sell_price}
            if buy_order:
                self.active_orders[buy_order['orderId']] = {'side': SIDE_BUY, 'price': buy_price}

    async def place_limit_order(self, side: str, quantity: float, price: float) -> Optional[dict]:
        """
        Place a limit order on Binance Futures.

        Args:
            side (str): 'BUY' or 'SELL'.
            quantity (float): Quantity to trade.
            price (float): Price at which to place the order.

        Returns:
            Optional[dict]: Response from Binance API if successful, else None.
        """
        try:
            order = await self.client.futures_create_order(
                symbol=self.config.symbol,
                side=side,
                type=ORDER_TYPE_LIMIT,
                timeInForce=TIME_IN_FORCE_GTC,
                quantity=quantity,
                price=str(price),  # Price must be a string
            )
            logger.info(f"{side} limit order placed: {order}")
            return order
        except BinanceAPIException as e:
            logger.error(f"Binance API Error placing {side} order: {e}")
        except BinanceRequestException as e:
            logger.error(f"Binance Request Error placing {side} order: {e}")
        except Exception as e:
            logger.error(f"Unexpected error placing {side} order: {e}")
        return None  # Return None if order placement fails

    async def cancel_orders(self, side: Optional[str] = None):
        """
        Cancel all open orders for the trading symbol, optionally filtering by side.

        Args:
            side (Optional[str]): 'BUY' or 'SELL' to filter orders by side. If None, cancels all orders.
        """
        try:
            open_orders = await self.client.futures_get_open_orders(symbol=self.config.symbol)
            if side:
                open_orders = [order for order in open_orders if order['side'] == side.upper()]
                logger.info(f"Found {len(open_orders)} open {side.upper()} orders to cancel for {self.config.symbol}.")
            else:
                logger.info(f"Found {len(open_orders)} open orders to cancel for {self.config.symbol}.")

            for order in open_orders:
                await self.client.futures_cancel_order(symbol=self.config.symbol, orderId=order['orderId'])
                logger.info(f"Canceled order {order['orderId']} for {self.config.symbol}")
                # Remove from active_orders if present
                self.active_orders.pop(order['orderId'], None)

            if side:
                logger.info(f"All {side} orders canceled for {self.config.symbol}")
            else:
                logger.info(f"All orders canceled for {self.config.symbol}")
        except BinanceAPIException as e:
            logger.error(f"Binance API Error canceling orders: {e}")
        except BinanceRequestException as e:
            logger.error(f"Binance Request Error canceling orders: {e}")
        except Exception as e:
            logger.error(f"Error canceling orders: {e}")

    # Other methods like calculate_take_profit_level, place_take_profit_order, etc.
    # Should also use logger instead of self.console.log

    async def monitor_orders(self):
        """
        Monitor active orders and place new ones immediately after orders are filled.
        """
        while True:
            try:
                # Fetch all active orders from Binance
                open_orders = await self.client.futures_get_open_orders(symbol=self.config.symbol)
                open_order_ids = {order['orderId'] for order in open_orders}

                # Identify filled orders by comparing with tracked active_orders
                filled_order_ids = set(self.active_orders.keys()) - open_order_ids

                for order_id in filled_order_ids:
                    order_info = self.active_orders.pop(order_id, None)
                    if order_info:
                        side = order_info['side']
                        price = order_info['price']
                        # Place a new order to maintain the grid
                        if side == SIDE_SELL:
                            new_sell_price = round_step_size(price + self.tick_size, step_size=self.tick_size)
                            new_order = await self.place_limit_order(SIDE_SELL, self.config.volume, new_sell_price)
                            if new_order:
                                self.active_orders[new_order['orderId']] = {'side': SIDE_SELL, 'price': new_sell_price}
                        elif side == SIDE_BUY:
                            new_buy_price = round_step_size(price - self.tick_size, step_size=self.tick_size)
                            new_order = await self.place_limit_order(SIDE_BUY, self.config.volume, new_buy_price)
                            if new_order:
                                self.active_orders[new_order['orderId']] = {'side': SIDE_BUY, 'price': new_buy_price}

                await asyncio.sleep(0.5)  # Short sleep for high-frequency monitoring
            except BinanceAPIException as e:
                logger.error(f"Binance API Error in monitor_orders: {e}")
                await asyncio.sleep(1)
            except BinanceRequestException as e:
                logger.error(f"Binance Request Error in monitor_orders: {e}")
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Exception in monitor_orders: {e}")
                await asyncio.sleep(1)

    async def monitor_position(self):
        """
        Monitor the position and manage orders accordingly.
        """
        logger.info("Starting position monitoring.")

        while True:
            try:
                direction = await self.get_position_direction()
                if direction != "FLAT":
                    logger.info(f"Position detected: {direction} for {self.config.symbol}")

                    # Cancel opposing side orders to avoid conflicting orders
                    opposing_side = SIDE_SELL if direction == "LONG" else SIDE_BUY
                    logger.info(f"Cancelling opposing side orders: {opposing_side}")
                    await self.cancel_orders(side=opposing_side)

                    # Calculate and place take-profit order
                    # Implement calculate_take_profit_level and place_take_profit_order methods

                    # Continuously monitor the position to adjust TP and SL orders if needed
                    # ... (omitted for brevity)

                else:
                    logger.info(f"No open positions for {self.config.symbol}. Drawing grid...")
                    await self.draw_grid()

                await asyncio.sleep(1)  # Reduced sleep for higher frequency
            except BinanceAPIException as e:
                logger.error(f"Binance API Error in monitor_position: {e}")
                await asyncio.sleep(1)
            except BinanceRequestException as e:
                logger.error(f"Binance Request Error in monitor_position: {e}")
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Exception in monitor_position: {e}")
                await asyncio.sleep(1)

    async def monitor_pnl(self):
        """
        Monitor net PnL and display in real time using rich library.
        """
        with Live(self.table, refresh_per_second=2, console=self.console):
            while True:
                try:
                    positions = await self.client.futures_position_information(symbol=self.config.symbol)
                    position_found = False
                    for position in positions:
                        if position['symbol'] == self.config.symbol:
                            position_amt = float(position['positionAmt'])
                            if position_amt != 0:
                                entry_price = float(position['entryPrice'])
                                mark_price = float(position['markPrice'])
                                unrealized_pnl = float(position['unRealizedProfit'])
                                pnl_percent = (unrealized_pnl / (entry_price * abs(position_amt))) * 100

                                # Update the table
                                self.table.rows = []
                                self.table.add_row(
                                    self.config.symbol,
                                    f"{position_amt}",
                                    f"{entry_price}",
                                    f"{mark_price}",
                                    f"{unrealized_pnl:.4f}",
                                    f"{pnl_percent:.2f}%",
                                    f"{unrealized_pnl:.4f}"
                                )
                                position_found = True
                                break  # Exit the loop since we found the position

                    if not position_found:
                        # No position found for this symbol
                        self.table.rows = []
                        self.table.add_row(
                            self.config.symbol,
                            "0",
                            "-",
                            "-",
                            "-",
                            "-",
                            "-"
                        )

                    await asyncio.sleep(1)
                except Exception as e:
                    logger.error(f"Error in monitor_pnl: {e}")
                    await asyncio.sleep(1)

    async def run(self):
        """
        Run the BinanceBot by initializing the client and starting position and order monitoring.
        """
        await self.initialize_client()
        try:
            await asyncio.gather(
                self.monitor_position(),
                self.monitor_orders(),  # Start order monitoring concurrently
                self.monitor_pnl()  # Start PnL monitoring
            )
        except Exception as e:
            logger.error(f"Exception in run: {e}")
        finally:
            if self.client:
                await self.client.close_connection()
                logger.info(f"Closed Binance client for {self.config.symbol}")

# -----------------------------
# Main Function to Run Bots
# -----------------------------

async def main():
    """
    Main function to initialize and run multiple BinanceBots concurrently based on the configuration.
    """
    # Define the configurations for each bot directly within the script
    bot_configs = [
        BotConfig(
            symbol="BTCUSDT",
            no_of_decimal_places=3,
            volume=0.002,  # Adjusted volume to meet minimum notional value
            proportion=0.1,  # Proportion is now represented by tick size
            take_profit_percent=0.5,  # Adjusted for tighter TP
            stop_loss_percent=0.5,  # New field for stop-loss
            num_of_grids=5,  # Fewer grids with tighter spacing
            leverage=10,
            testnet=True
        ),
        BotConfig(
            symbol="ETHUSDT",
            no_of_decimal_places=3,
            volume=0.05,  # Adjusted volume to meet minimum notional value
            proportion=0.1,  # Proportion is now represented by tick size
            take_profit_percent=0.5,  # Adjusted for tighter TP
            stop_loss_percent=0.5,  # New field for stop-loss
            num_of_grids=5,  # Fewer grids with tighter spacing
            leverage=10,
            testnet=True
        )
        # Add more BotConfig instances here for additional bots
    ]

    bots = [BinanceBot(config) for config in bot_configs]  # Initialize each bot

    # Run all bots concurrently
    await asyncio.gather(*(bot.run() for bot in bots))

# -----------------------------
# Entry Point
# -----------------------------

if __name__ == "__main__":
    try:
        # Start the asyncio event loop and run the main function
        logger.info("Starting Binance trading bots...")
        print("INFO: Starting Binance trading bots...")
        asyncio.run(main())
    except KeyboardInterrupt:
        # Handle user-initiated interruption (e.g., Ctrl+C)
        logger.info("Bot terminated by user.")
        print("INFO: Bot terminated by user.")
    except Exception as e:
        # Handle any unexpected exceptions
        logger.error(f"Unhandled exception: {e}")
        print(f"ERROR: Unhandled exception: {e}")


# -----------------------------
# Test Suite for BinanceBot
# -----------------------------
if __name__ == '__main__' and 'test' in __name__:
    import unittest
    from unittest.mock import AsyncMock, patch, MagicMock
    import asyncio

    # Define the Test Suite here
    import unittest
from unittest.mock import AsyncMock, patch, MagicMock
import asyncio

# Import the BinanceBot and BotConfig classes from your main script
# Adjust the import according to your actual file structure
from binance_hft_market_maker import BinanceBot, BotConfig

class TestBinanceBot(unittest.IsolatedAsyncioTestCase):
    """
    Test suite for the BinanceBot class.
    """

    def setUp(self):
        """
        Set up the test environment before each test.
        """
        # Create a BotConfig instance for testing
        self.config = BotConfig(
            symbol="BTCUSDT",
            no_of_decimal_places=3,
            volume=0.002,
            proportion=0.1,
            take_profit_percent=0.5,
            stop_loss_percent=0.5,
            num_of_grids=5,
            leverage=10,
            testnet=True
        )
        # Instantiate the BinanceBot with the test config
        self.bot = BinanceBot(self.config)
        # Mock the console to prevent actual console output during tests
        self.bot.console = MagicMock()

    @patch('bot.AsyncClient.create')
    async def test_initialize_client_success(self, mock_create):
        """
        Test successful client initialization.
        """
        # Mock the client creation
        mock_create.return_value = AsyncMock()
        await self.bot.initialize_client()
        self.assertIsNotNone(self.bot.client)
        mock_create.assert_called_once()

    @patch('bot.AsyncClient.create', side_effect=Exception('API Error'))
    async def test_initialize_client_failure(self, mock_create):
        """
        Test client initialization failure.
        """
        with self.assertRaises(SystemExit):
            await self.bot.initialize_client()
        mock_create.assert_called_once()

    # Test get_tick_size method
    @patch('bot.AsyncClient.futures_exchange_info')
    async def test_get_tick_size_success(self, mock_exchange_info):
        """
        Test successful retrieval of tick size.
        """
        # Mock the exchange info response
        mock_exchange_info.return_value = {
            'symbols': [
                {
                    'symbol': 'BTCUSDT',
                    'filters': [
                        {'filterType': 'PRICE_FILTER', 'tickSize': '0.1'}
                    ]
                }
            ]
        }
        # Mock the client
        self.bot.client = AsyncMock()
        await self.bot.get_tick_size()
        self.assertEqual(self.bot.tick_size, 0.1)

    @patch('bot.AsyncClient.futures_exchange_info', side_effect=Exception('API Error'))
    async def test_get_tick_size_failure(self, mock_exchange_info):
        """
        Test failure to retrieve tick size.
        """
        # Mock the client
        self.bot.client = AsyncMock()
        with self.assertRaises(SystemExit):
            await self.bot.get_tick_size()

    # Test set_leverage method
    @patch('bot.AsyncClient.futures_change_leverage')
    async def test_set_leverage_success(self, mock_change_leverage):
        """
        Test successful setting of leverage.
        """
        # Mock the response
        mock_change_leverage.return_value = {'leverage': self.config.leverage}
        # Mock the client
        self.bot.client = AsyncMock()
        await self.bot.set_leverage()
        mock_change_leverage.assert_called_once_with(symbol=self.config.symbol, leverage=self.config.leverage)

    @patch('bot.AsyncClient.futures_change_leverage', side_effect=Exception('API Error'))
    async def test_set_leverage_failure(self, mock_change_leverage):
        """
        Test failure to set leverage.
        """
        # Mock the client
        self.bot.client = AsyncMock()
        await self.bot.set_leverage()
        mock_change_leverage.assert_called_once()

    # Test get_position_direction method
    @patch('bot.AsyncClient.futures_position_information')
    async def test_get_position_direction_long(self, mock_position_info):
        """
        Test getting position direction when long.
        """
        mock_position_info.return_value = [{'symbol': 'BTCUSDT', 'positionAmt': '0.01'}]
        # Mock the client
        self.bot.client = AsyncMock()
        direction = await self.bot.get_position_direction()
        self.assertEqual(direction, 'LONG')

    @patch('bot.AsyncClient.futures_position_information')
    async def test_get_position_direction_short(self, mock_position_info):
        """
        Test getting position direction when short.
        """
        mock_position_info.return_value = [{'symbol': 'BTCUSDT', 'positionAmt': '-0.01'}]
        # Mock the client
        self.bot.client = AsyncMock()
        direction = await self.bot.get_position_direction()
        self.assertEqual(direction, 'SHORT')

    @patch('bot.AsyncClient.futures_position_information')
    async def test_get_position_direction_flat(self, mock_position_info):
        """
        Test getting position direction when flat.
        """
        mock_position_info.return_value = [{'symbol': 'BTCUSDT', 'positionAmt': '0'}]
        # Mock the client
        self.bot.client = AsyncMock()
        direction = await self.bot.get_position_direction()
        self.assertEqual(direction, 'FLAT')

    # Test get_mark_price method
    @patch('bot.AsyncClient.futures_mark_price')
    async def test_get_mark_price_success(self, mock_mark_price):
        """
        Test successful retrieval of mark price.
        """
        mock_mark_price.return_value = {'markPrice': '50000'}
        # Mock the client
        self.bot.client = AsyncMock()
        price = await self.bot.get_mark_price()
        self.assertEqual(price, 50000.0)

    @patch('bot.AsyncClient.futures_mark_price', side_effect=Exception('API Error'))
    async def test_get_mark_price_failure(self, mock_mark_price):
        """
        Test failure to retrieve mark price.
        """
        # Mock the client
        self.bot.client = AsyncMock()
        price = await self.bot.get_mark_price()
        self.assertIsNone(price)

    # Test place_limit_order method
    @patch('bot.AsyncClient.futures_create_order')
    async def test_place_limit_order_success(self, mock_create_order):
        """
        Test successful placement of a limit order.
        """
        mock_create_order.return_value = {'orderId': 12345}
        # Mock the client
        self.bot.client = AsyncMock()
        order = await self.bot.place_limit_order('BUY', 0.002, 50000)
        self.assertIsNotNone(order)
        self.assertEqual(order['orderId'], 12345)
        mock_create_order.assert_called_once()

    @patch('bot.AsyncClient.futures_create_order', side_effect=Exception('API Error'))
    async def test_place_limit_order_failure(self, mock_create_order):
        """
        Test failure to place a limit order.
        """
        # Mock the client
        self.bot.client = AsyncMock()
        order = await self.bot.place_limit_order('BUY', 0.002, 50000)
        self.assertIsNone(order)
        mock_create_order.assert_called_once()

    # Test cancel_orders method
    @patch('bot.AsyncClient.futures_get_open_orders')
    @patch('bot.AsyncClient.futures_cancel_order')
    async def test_cancel_orders(self, mock_cancel_order, mock_get_open_orders):
        """
        Test successful cancellation of orders.
        """
        mock_get_open_orders.return_value = [{'orderId': 12345, 'side': 'BUY'}]
        # Mock the client
        self.bot.client = AsyncMock()
        self.bot.active_orders = {12345: {'side': 'BUY', 'price': 50000}}
        await self.bot.cancel_orders()
        mock_get_open_orders.assert_called_once()
        mock_cancel_order.assert_called_once_with(symbol=self.config.symbol, orderId=12345)
        self.assertEqual(self.bot.active_orders, {})

    # Test calculate_take_profit_level method
    @patch('bot.AsyncClient.futures_position_information')
    async def test_calculate_take_profit_level_long(self, mock_position_info):
        """
        Test calculation of take-profit level for a long position.
        """
        mock_position_info.return_value = [{'symbol': 'BTCUSDT', 'positionAmt': '0.002', 'entryPrice': '50000'}]
        # Mock the client
        self.bot.client = AsyncMock()
        self.bot.tick_size = 0.1
        tp_price, tp_quantity = await self.bot.calculate_take_profit_level()
        # Calculate expected tp_price
        entry_price = 50000
        position_amt = 0.002
        leverage = self.config.leverage
        margin = (entry_price * abs(position_amt)) / leverage
        profit = margin * (self.config.take_profit_percent / 100)
        expected_tp_price = entry_price + (profit / position_amt)
        expected_tp_price = round(expected_tp_price / self.bot.tick_size) * self.bot.tick_size
        self.assertEqual(tp_price, expected_tp_price)
        self.assertEqual(tp_quantity, abs(position_amt))

    @patch('bot.AsyncClient.futures_position_information')
    async def test_calculate_take_profit_level_flat(self, mock_position_info):
        """
        Test calculation of take-profit level when no position is open.
        """
        mock_position_info.return_value = [{'symbol': 'BTCUSDT', 'positionAmt': '0', 'entryPrice': '0'}]
        # Mock the client
        self.bot.client = AsyncMock()
        tp_price, tp_quantity = await self.bot.calculate_take_profit_level()
        self.assertIsNone(tp_price)
        self.assertIsNone(tp_quantity)

    # Test monitor_pnl method (simplified)
    @patch('bot.AsyncClient.futures_position_information')
    async def test_monitor_pnl(self, mock_position_info):
        """
        Test monitor_pnl method.
        """
        mock_position_info.return_value = [{
            'symbol': 'BTCUSDT',
            'positionAmt': '0.002',
            'entryPrice': '50000',
            'markPrice': '50100',
            'unRealizedProfit': '200'
        }]
        # Mock the client
        self.bot.client = AsyncMock()
        # Run monitor_pnl for a short duration
        async def run_monitor_pnl():
            await asyncio.wait_for(self.bot.monitor_pnl(), timeout=1)
        with self.assertRaises(asyncio.TimeoutError):
            await run_monitor_pnl()
        # Ensure that table rows have been updated
        self.assertTrue(self.bot.table.rows)

    # Test draw_grid method
    @patch('bot.BinanceBot.get_mark_price', return_value=50000.0)
    @patch('bot.BinanceBot.place_limit_order', return_value={'orderId': 12345})
    async def test_draw_grid(self, mock_place_limit_order, mock_get_mark_price):
        """
        Test the draw_grid method.
        """
        self.bot.tick_size = 0.1
        await self.bot.draw_grid()
        # Check that place_limit_order was called the correct number of times
        expected_calls = (self.config.num_of_grids * 2)  # For BUY and SELL orders
        self.assertEqual(mock_place_limit_order.call_count, expected_calls)
        # Check that active_orders dictionary is populated
        self.assertEqual(len(self.bot.active_orders), expected_calls)

    # Add more tests as necessary...

    # End-to-end test
    async def test_end_to_end(self):
        """
        End-to-end test of the bot's main functionality using mocks.
        """
        with patch('bot.AsyncClient.create') as mock_create_client:
            mock_client = AsyncMock()
            mock_create_client.return_value = mock_client

            # Mock necessary client methods
            mock_client.futures_exchange_info.return_value = {
                'symbols': [
                    {
                        'symbol': 'BTCUSDT',
                        'filters': [
                            {'filterType': 'PRICE_FILTER', 'tickSize': '0.1'}
                        ]
                    }
                ]
            }
            mock_client.futures_change_leverage.return_value = {'leverage': self.config.leverage}
            mock_client.futures_position_information.return_value = [{'symbol': 'BTCUSDT', 'positionAmt': '0.002', 'entryPrice': '50000'}]
            mock_client.futures_mark_price.return_value = {'markPrice': '50100'}
            mock_client.futures_create_order.return_value = {'orderId': 12345}
            mock_client.futures_get_open_orders.return_value = []
            mock_client.futures_cancel_order.return_value = {}

            # Mock the console
            self.bot.console = MagicMock()

            # Run the bot's run method (we need to adjust it to allow testing)
            async def run_bot():
                await asyncio.wait_for(self.bot.run(), timeout=1)
            with self.assertRaises(asyncio.TimeoutError):
                await run_bot()

            # Verify that the client was initialized
            mock_create_client.assert_called_once()
            mock_client.futures_exchange_info.assert_awaited()
            mock_client.futures_change_leverage.assert_awaited()

            # Verify that get_position_direction was called
            self.assertTrue(mock_client.futures_position_information.await_count > 0)

            # Verify that get_mark_price was called
            self.assertTrue(mock_client.futures_mark_price.await_count > 0)

            # Verify that orders were placed
            self.assertTrue(mock_client.futures_create_order.await_count > 0)

            # Add more assertions as necessary...

if __name__ == '__main__':
    unittest.main()


    # Execute the test suite
    unittest.main()
