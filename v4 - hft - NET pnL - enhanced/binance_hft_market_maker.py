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
            sell_order = await self.place_limit_order(SIDE_SELL, self.config.volume, sell_price)
            buy_order = await self.place_limit_order(SIDE_BUY, self.config.volume, buy_price)
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
