import asyncio
import logging
import logging.handlers
import os
import sys
from dataclasses import dataclass, field
from typing import Optional, Tuple

from binance import AsyncClient
from binance.enums import *
from binance.exceptions import BinanceAPIException, BinanceRequestException
from binance.helpers import round_step_size

import pandas as pd
import key_file as k  # Ensure this file is secure and not tracked by version control

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
            print(f"INFO: Binance client initialized for {self.config.symbol}")

            # Set leverage for the trading symbol
            await self.set_leverage()

            # Retrieve and set tick size
            await self.get_tick_size()
        except BinanceAPIException as e:
            logger.error(f"Binance API Exception during client initialization: {e}")
            print(f"ERROR: Binance API Exception during client initialization: {e}")
            sys.exit(1)
        except BinanceRequestException as e:
            logger.error(f"Binance Request Exception during client initialization: {e}")
            print(f"ERROR: Binance Request Exception during client initialization: {e}")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Unexpected error during client initialization: {e}")
            print(f"ERROR: Unexpected error during client initialization: {e}")
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
                        print(f"INFO: Tick size for {self.config.symbol} is {self.tick_size}")
                        return
            logger.error(f"Could not retrieve tick size for {self.config.symbol}")
            print(f"ERROR: Could not retrieve tick size for {self.config.symbol}")
            sys.exit(1)
        except BinanceAPIException as e:
            logger.error(f"Binance API Error fetching exchange info: {e}")
            print(f"ERROR: Binance API Error fetching exchange info: {e}")
            sys.exit(1)
        except BinanceRequestException as e:
            logger.error(f"Binance Request Error fetching exchange info: {e}")
            print(f"ERROR: Binance Request Error fetching exchange info: {e}")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Unexpected error fetching exchange info: {e}")
            print(f"ERROR: Unexpected error fetching exchange info: {e}")
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
            print(f"INFO: Leverage set to {self.config.leverage}x for {self.config.symbol}")
        except BinanceAPIException as e:
            logger.error(f"Binance API Error setting leverage: {e}")
            print(f"ERROR: Binance API Error setting leverage: {e}")
        except BinanceRequestException as e:
            logger.error(f"Binance Request Error setting leverage: {e}")
            print(f"ERROR: Binance Request Error setting leverage: {e}")
        except Exception as e:
            logger.error(f"Unexpected error setting leverage: {e}")
            print(f"ERROR: Unexpected error setting leverage: {e}")

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
                    print(f"DEBUG: Position for {self.config.symbol}: {position_amt}")
                    if position_amt > 0:
                        print(f"INFO: Current position is LONG for {self.config.symbol}")
                        return "LONG"
                    elif position_amt < 0:
                        print(f"INFO: Current position is SHORT for {self.config.symbol}")
                        return "SHORT"
                    else:
                        print(f"INFO: Current position is FLAT for {self.config.symbol}")
                        return "FLAT"
            print(f"INFO: No matching symbol found in position information for {self.config.symbol}.")
            return "FLAT"
        except BinanceAPIException as e:
            logger.error(f"Binance API Error determining position direction: {e}")
            print(f"ERROR: Binance API Error determining position direction: {e}")
            return "FLAT"
        except BinanceRequestException as e:
            logger.error(f"Binance Request Error determining position direction: {e}")
            print(f"ERROR: Binance Request Error determining position direction: {e}")
            return "FLAT"
        except Exception as e:
            logger.error(f"Error determining position direction: {e}")
            print(f"ERROR: Error determining position direction: {e}")
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
            print(f"DEBUG: Mark price for {self.config.symbol}: {price}")
            return price
        except BinanceAPIException as e:
            logger.error(f"Binance API Error fetching mark price: {e}")
            print(f"ERROR: Binance API Error fetching mark price: {e}")
            return None
        except BinanceRequestException as e:
            logger.error(f"Binance Request Error fetching mark price: {e}")
            print(f"ERROR: Binance Request Error fetching mark price: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching mark price: {e}")
            print(f"ERROR: Error fetching mark price: {e}")
            return None

    async def draw_grid(self):
        """
        Place grid of tight limit buy and sell orders around the current market price.
        """
        current_price = await self.get_mark_price()
        if current_price is None:
            logger.warning("Current price unavailable. Skipping grid drawing.")
            print("WARNING: Current price unavailable. Skipping grid drawing.")
            return

        grid_spacing = self.tick_size  # Set grid spacing to tick size for tight spreads
        print(f"INFO: Drawing grid with {self.config.num_of_grids} levels at tick size intervals ({grid_spacing}).")
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
            print(f"INFO: Placing SELL limit order at {sell_price} and BUY limit order at {buy_price}.")
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
            print(f"INFO: {side} limit order placed: {order}")
            return order
        except BinanceAPIException as e:
            logger.error(f"Binance API Error placing {side} order: {e}")
            print(f"ERROR: Binance API Error placing {side} order: {e}")
        except BinanceRequestException as e:
            logger.error(f"Binance Request Error placing {side} order: {e}")
            print(f"ERROR: Binance Request Error placing {side} order: {e}")
        except Exception as e:
            logger.error(f"Unexpected error placing {side} order: {e}")
            print(f"ERROR: Unexpected error placing {side} order: {e}")
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
                print(f"INFO: Found {len(open_orders)} open {side.upper()} orders to cancel for {self.config.symbol}.")
                logger.info(f"Found {len(open_orders)} open {side.upper()} orders to cancel for {self.config.symbol}.")
            else:
                print(f"INFO: Found {len(open_orders)} open orders to cancel for {self.config.symbol}.")
                logger.info(f"Found {len(open_orders)} open orders to cancel for {self.config.symbol}.")

            for order in open_orders:
                await self.client.futures_cancel_order(symbol=self.config.symbol, orderId=order['orderId'])
                logger.info(f"Canceled order {order['orderId']} for {self.config.symbol}")
                print(f"INFO: Canceled order {order['orderId']} for {self.config.symbol}")
                # Remove from active_orders if present
                self.active_orders.pop(order['orderId'], None)

            if side:
                logger.info(f"All {side} orders canceled for {self.config.symbol}")
                print(f"INFO: All {side} orders canceled for {self.config.symbol}")
            else:
                logger.info(f"All orders canceled for {self.config.symbol}")
                print(f"INFO: All orders canceled for {self.config.symbol}")
        except BinanceAPIException as e:
            logger.error(f"Binance API Error canceling orders: {e}")
            print(f"ERROR: Binance API Error canceling orders: {e}")
        except BinanceRequestException as e:
            logger.error(f"Binance Request Error canceling orders: {e}")
            print(f"ERROR: Binance Request Error canceling orders: {e}")
        except Exception as e:
            logger.error(f"Error canceling orders: {e}")
            print(f"ERROR: Error canceling orders: {e}")

    async def calculate_take_profit_level(self) -> Tuple[Optional[float], Optional[float]]:
        """
        Calculate the take-profit price level based on current open positions.

        Returns:
            Tuple[Optional[float], Optional[float]]: (Take-profit price, Position quantity)
        """
        try:
            positions = await self.client.futures_position_information(symbol=self.config.symbol)
            position = next((p for p in positions if p['symbol'] == self.config.symbol and float(p['positionAmt']) != 0), None)
            if not position:
                logger.info("No open positions to calculate take profit.")
                print("INFO: No open positions to calculate take profit.")
                return None, None

            entry_price = float(position['entryPrice'])  # Entry price of the position
            position_amt = float(position['positionAmt'])  # Amount of the position
            leverage = self.config.leverage  # Use leverage from configuration

            logger.debug(f"Entry Price: {entry_price}, Position Amount: {position_amt}, Leverage: {leverage}")
            print(f"DEBUG: Entry Price: {entry_price}, Position Amount: {position_amt}, Leverage: {leverage}")

            # Calculate margin and desired profit
            margin = (entry_price * abs(position_amt)) / leverage
            profit = margin * (self.config.take_profit_percent / 100)

            # Calculate TP price based on position direction
            if position_amt > 0:  # LONG
                tp_price = entry_price + (profit / position_amt)
                direction = "LONG"
                print(f"INFO: Calculated TP price for LONG position: {tp_price}")
                logger.info(f"Calculated TP price for LONG position: {tp_price}")
            elif position_amt < 0:  # SHORT
                tp_price = entry_price - (profit / abs(position_amt))
                direction = "SHORT"
                print(f"INFO: Calculated TP price for SHORT position: {tp_price}")
                logger.info(f"Calculated TP price for SHORT position: {tp_price}")
            else:
                tp_price = None
                direction = "FLAT"

            if tp_price:
                tp_price = round_step_size(tp_price, step_size=self.tick_size)
                logger.info(f"Calculated TP level: Price={tp_price}, Quantity={abs(position_amt)}")
                print(f"INFO: Calculated TP level: Price={tp_price}, Quantity={abs(position_amt)}")
                return tp_price, abs(position_amt)
            else:
                return None, None
        except BinanceAPIException as e:
            logger.error(f"Binance API Error in calculate_take_profit_level: {e}")
            print(f"ERROR: Binance API Error in calculate_take_profit_level: {e}")
            return None, None
        except BinanceRequestException as e:
            logger.error(f"Binance Request Error in calculate_take_profit_level: {e}")
            print(f"ERROR: Binance Request Error in calculate_take_profit_level: {e}")
            return None, None
        except Exception as e:
            logger.error(f"Exception in calculate_take_profit_level: {e}")
            print(f"ERROR: Exception in calculate_take_profit_level: {e}")
            return None, None

    async def place_take_profit_order(self, price: float, quantity: float, direction: str):
        """
        Place a take-profit order based on the current position direction.

        Args:
            price (float): Take-profit price.
            quantity (float): Amount to sell or buy.
            direction (str): 'LONG' or 'SHORT'.
        """
        side = SIDE_SELL if direction == "LONG" else SIDE_BUY  # Determine side based on position
        print(f"INFO: Placing take-profit order. Side: {side}, Quantity: {quantity}, Price: {price}")
        logger.info(f"Placing take-profit order. Side: {side}, Quantity: {quantity}, Price: {price}")
        order = await self.place_limit_order(side, quantity, price)
        if order:
            logger.info(f"Placed take-profit order: {side} {quantity} at {price} for {self.config.symbol}")
            print(f"INFO: Placed take-profit order: {side} {quantity} at {price} for {self.config.symbol}")
            self.active_orders[order['orderId']] = {'side': side, 'price': price}

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
                print(f"ERROR: Binance API Error in monitor_orders: {e}")
                await asyncio.sleep(1)
            except BinanceRequestException as e:
                logger.error(f"Binance Request Error in monitor_orders: {e}")
                print(f"ERROR: Binance Request Error in monitor_orders: {e}")
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Exception in monitor_orders: {e}")
                print(f"ERROR: Exception in monitor_orders: {e}")
                await asyncio.sleep(1)

    async def monitor_position(self):
        """
        Monitor the position and manage orders accordingly.
        """
        print("INFO: Starting position monitoring.")
        logger.info("Starting position monitoring.")

        while True:
            try:
                direction = await self.get_position_direction()
                if direction != "FLAT":
                    logger.info(f"Position detected: {direction} for {self.config.symbol}")
                    print(f"INFO: Position detected: {direction} for {self.config.symbol}")

                    # Cancel opposing side orders to avoid conflicting orders
                    opposing_side = SIDE_SELL if direction == "LONG" else SIDE_BUY
                    print(f"INFO: Cancelling opposing side orders: {opposing_side}")
                    logger.info(f"Cancelling opposing side orders: {opposing_side}")
                    await self.cancel_orders(side=opposing_side)

                    # Calculate and place take-profit order
                    tp_price, tp_quantity = await self.calculate_take_profit_level()
                    if tp_price and tp_quantity:
                        await self.place_take_profit_order(tp_price, tp_quantity, direction)

                    # Continuously monitor the position to adjust TP orders if needed
                    while direction != "FLAT":
                        new_direction = await self.get_position_direction()
                        if new_direction != direction:
                            logger.info(f"Position direction changed from {direction} to {new_direction}")
                            print(f"INFO: Position direction changed from {direction} to {new_direction}")
                            await self.cancel_orders()
                            break

                        # Recalculate take-profit level
                        new_tp_price, new_tp_quantity = await self.calculate_take_profit_level()
                        if new_tp_price and new_tp_price != tp_price:
                            logger.info("TP level changed. Updating orders...")
                            print("INFO: TP level changed. Updating orders...")
                            await self.cancel_orders()
                            await self.place_take_profit_order(new_tp_price, new_tp_quantity, direction)
                            tp_price, tp_quantity = new_tp_price, new_tp_quantity

                        await asyncio.sleep(1)  # Reduced sleep for higher frequency
                else:
                    logger.info(f"No open positions for {self.config.symbol}. Drawing grid...")
                    print(f"INFO: No open positions for {self.config.symbol}. Drawing grid...")
                    await self.draw_grid()

                await asyncio.sleep(1)  # Reduced sleep for higher frequency
            except BinanceAPIException as e:
                logger.error(f"Binance API Error in monitor_position: {e}")
                print(f"ERROR: Binance API Error in monitor_position: {e}")
                await asyncio.sleep(1)  # Reduced sleep in case of error
            except BinanceRequestException as e:
                logger.error(f"Binance Request Error in monitor_position: {e}")
                print(f"ERROR: Binance Request Error in monitor_position: {e}")
                await asyncio.sleep(1)  # Reduced sleep in case of error
            except Exception as e:
                logger.error(f"Exception in monitor_position: {e}")
                print(f"ERROR: Exception in monitor_position: {e}")
                await asyncio.sleep(1)  # Reduced sleep in case of error

    async def run(self):
        """
        Run the BinanceBot by initializing the client and starting position and order monitoring.
        """
        await self.initialize_client()
        try:
            await asyncio.gather(
                self.monitor_position(),
                self.monitor_orders()  # Start order monitoring concurrently
            )
        except Exception as e:
            logger.error(f"Exception in run: {e}")
            print(f"ERROR: Exception in run: {e}")
        finally:
            if self.client:
                await self.client.close_connection()
                logger.info(f"Closed Binance client for {self.config.symbol}")
                print(f"INFO: Closed Binance client for {self.config.symbol}")

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
            no_of_decimal_places=1,
            volume=0.001,  # Reduced volume for tighter grids and HFT
            proportion=0.1,  # Proportion is now represented by tick size
            take_profit_percent=0.5,  # Adjusted for tighter TP
            num_of_grids=5,  # Fewer grids with tighter spacing
            leverage=10,
            testnet=True
        ),
        BotConfig(
            symbol="ETHUSDT",
            no_of_decimal_places=2,
            volume=0.01,
            proportion=0.1,  # Proportion is now represented by tick size
            take_profit_percent=0.5,  # Adjusted for tighter TP
            num_of_grids=5,  # Fewer grids with tighter spacing
            leverage=10,
            testnet=True
        )
        # Add more BotConfig instances here for additional bots
    ]

    bots = []
    for bot_config in bot_configs:
        bot = BinanceBot(bot_config)
        bots.append(bot.run())  # Collect coroutine objects
        print(f"INFO: Bot for {bot_config.symbol} added to the run queue.")
        logger.info(f"Bot for {bot_config.symbol} added to the run queue.")

    # Run all bots concurrently
    await asyncio.gather(*bots)

# -----------------------------
# Entry Point
# -----------------------------

if __name__ == "__main__":
    try:
        # Start the asyncio event loop and run the main function
        print("INFO: Starting Binance trading bots...")
        logger.info("Starting Binance trading bots...")
        asyncio.run(main())
    except KeyboardInterrupt:
        # Handle user-initiated interruption (e.g., Ctrl+C)
        logger.info("Bot terminated by user.")
        print("INFO: Bot terminated by user.")
    except Exception as e:
        # Handle any unexpected exceptions
        logger.error(f"Unhandled exception: {e}")
        print(f"ERROR: Unhandled exception: {e}")


import unittest
from unittest.mock import AsyncMock, patch, MagicMock
import asyncio

# Import the BinanceHFTMarketMaker class from the module
# Ensure that the module name matches your actual module file
from binance_hft_market_maker import BinanceBot, BotConfig

class TestBinanceHFTMarketMaker(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Define a sample BotConfig for testing
        self.bot_config = BotConfig(
            symbol="BTCUSDT",
            no_of_decimal_places=1,
            volume=0.001,
            proportion=0.1,  # Represented by tick size
            take_profit_percent=0.5,
            num_of_grids=5,
            leverage=10,
            testnet=True
        )
        self.bot = BinanceBot(self.bot_config)

    @patch('binance_hft_market_maker.AsyncClient')
    async def test_initialize_client(self, mock_async_client):
        # Mock the AsyncClient.create method
        mock_client_instance = AsyncMock()
        mock_async_client.create.return_value = mock_client_instance

        # Mock futures_change_leverage response
        mock_client_instance.futures_change_leverage.return_value = {"leverage": self.bot_config.leverage}

        # Mock futures_exchange_info response
        mock_client_instance.futures_exchange_info.return_value = {
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "filters": [
                        {"filterType": "PRICE_FILTER", "tickSize": "0.1"},
                        {"filterType": "LOT_SIZE", "minQty": "0.001"}
                    ]
                }
            ]
        }

        await self.bot.initialize_client()

        # Assertions to ensure methods were called correctly
        mock_async_client.create.assert_awaited_once_with(
            api_key=self.bot.api_key,
            api_secret=self.bot.api_secret,
            tld='com',
            testnet=self.bot_config.testnet
        )
        mock_client_instance.futures_change_leverage.assert_awaited_once_with(
            symbol=self.bot_config.symbol,
            leverage=self.bot_config.leverage
        )
        self.assertEqual(self.bot.tick_size, 0.1)

    @patch('binance_hft_market_maker.AsyncClient')
    async def test_get_position_direction_long(self, mock_async_client):
        # Mock the client and its methods
        mock_client_instance = AsyncMock()
        mock_async_client.create.return_value = mock_client_instance

        # Mock position information indicating a LONG position
        mock_client_instance.futures_position_information.return_value = [
            {"symbol": "BTCUSDT", "positionAmt": "0.5", "entryPrice": "50000"}
        ]

        direction = await self.bot.get_position_direction()
        self.assertEqual(direction, "LONG")

    @patch('binance_hft_market_maker.AsyncClient')
    async def test_get_position_direction_short(self, mock_async_client):
        # Mock the client and its methods
        mock_client_instance = AsyncMock()
        mock_async_client.create.return_value = mock_client_instance

        # Mock position information indicating a SHORT position
        mock_client_instance.futures_position_information.return_value = [
            {"symbol": "BTCUSDT", "positionAmt": "-0.3", "entryPrice": "60000"}
        ]

        direction = await self.bot.get_position_direction()
        self.assertEqual(direction, "SHORT")

    @patch('binance_hft_market_maker.AsyncClient')
    async def test_get_position_direction_flat(self, mock_async_client):
        # Mock the client and its methods
        mock_client_instance = AsyncMock()
        mock_async_client.create.return_value = mock_client_instance

        # Mock position information indicating a FLAT position
        mock_client_instance.futures_position_information.return_value = [
            {"symbol": "BTCUSDT", "positionAmt": "0.0", "entryPrice": "0"}
        ]

        direction = await self.bot.get_position_direction()
        self.assertEqual(direction, "FLAT")

    @patch('binance_hft_market_maker.AsyncClient')
    async def test_get_mark_price(self, mock_async_client):
        # Mock the client and its methods
        mock_client_instance = AsyncMock()
        mock_async_client.create.return_value = mock_client_instance

        # Mock mark price
        mock_client_instance.futures_mark_price.return_value = {"symbol": "BTCUSDT", "markPrice": "50500.5"}

        price = await self.bot.get_mark_price()
        self.assertEqual(price, 50500.5)

    @patch('binance_hft_market_maker.AsyncClient')
    async def test_draw_grid(self, mock_async_client):
        # Initialize client mock
        mock_client_instance = AsyncMock()
        mock_async_client.create.return_value = mock_client_instance
        self.bot.client = mock_client_instance

        # Set tick size
        self.bot.tick_size = 0.1

        # Mock mark price
        mock_client_instance.futures_mark_price.return_value = {"symbol": "BTCUSDT", "markPrice": "50500.5"}

        # Mock order placement
        mock_client_instance.futures_create_order.return_value = {"orderId": 12345, "symbol": "BTCUSDT"}

        await self.bot.draw_grid()

        # Check that futures_create_order was called 10 times (5 sell and 5 buy)
        self.assertEqual(mock_client_instance.futures_create_order.call_count, self.bot_config.num_of_grids * 2)

    @patch('binance_hft_market_maker.AsyncClient')
    async def test_place_limit_order(self, mock_async_client):
        mock_client_instance = AsyncMock()
        mock_async_client.create.return_value = mock_client_instance
        self.bot.client = mock_client_instance

        # Mock successful order placement
        mock_client_instance.futures_create_order.return_value = {
            "orderId": 67890,
            "symbol": "BTCUSDT",
            "status": "NEW"
        }

        order = await self.bot.place_limit_order("BUY", 0.001, 50499.5)
        self.assertIsNotNone(order)
        self.assertEqual(order["orderId"], 67890)
        mock_client_instance.futures_create_order.assert_awaited_with(
            symbol="BTCUSDT",
            side="BUY",
            type="LIMIT",
            timeInForce="GTC",
            quantity=0.001,
            price="50499.5"
        )

    @patch('binance_hft_market_maker.AsyncClient')
    async def test_cancel_orders(self, mock_async_client):
        mock_client_instance = AsyncMock()
        mock_async_client.create.return_value = mock_client_instance
        self.bot.client = mock_client_instance

        # Mock open orders
        mock_client_instance.futures_get_open_orders.return_value = [
            {"orderId": 111, "symbol": "BTCUSDT", "side": "BUY"},
            {"orderId": 222, "symbol": "BTCUSDT", "side": "SELL"},
            {"orderId": 333, "symbol": "BTCUSDT", "side": "BUY"}
        ]

        # Mock cancellation
        mock_client_instance.futures_cancel_order.return_value = {}

        # Cancel only BUY orders
        await self.bot.cancel_orders(side="BUY")

        # Check that futures_cancel_order was called twice
        self.assertEqual(mock_client_instance.futures_cancel_order.call_count, 2)
        mock_client_instance.futures_cancel_order.assert_any_await(symbol="BTCUSDT", orderId=111)
        mock_client_instance.futures_cancel_order.assert_any_await(symbol="BTCUSDT", orderId=333)

    @patch('binance_hft_market_maker.AsyncClient')
    async def test_calculate_take_profit_level_long(self, mock_async_client):
        mock_client_instance = AsyncMock()
        mock_async_client.create.return_value = mock_client_instance
        self.bot.client = mock_client_instance

        # Mock position information for LONG
        mock_client_instance.futures_position_information.return_value = [
            {"symbol": "BTCUSDT", "positionAmt": "0.5", "entryPrice": "50000"}
        ]

        tp_price, tp_quantity = await self.bot.calculate_take_profit_level()
        expected_profit = (50000 * 0.5) / 10 * (0.5 / 100)  # Margin * take_profit_percent
        expected_tp_price = 50000 + (expected_profit / 0.5)

        self.assertAlmostEqual(tp_price, expected_tp_price)
        self.assertEqual(tp_quantity, 0.5)

    @patch('binance_hft_market_maker.AsyncClient')
    async def test_calculate_take_profit_level_short(self, mock_async_client):
        mock_client_instance = AsyncMock()
        mock_async_client.create.return_value = mock_client_instance
        self.bot.client = mock_client_instance

        # Mock position information for SHORT
        mock_client_instance.futures_position_information.return_value = [
            {"symbol": "BTCUSDT", "positionAmt": "-0.3", "entryPrice": "60000"}
        ]

        tp_price, tp_quantity = await self.bot.calculate_take_profit_level()
        expected_profit = (60000 * 0.3) / 10 * (0.5 / 100)  # Margin * take_profit_percent
        expected_tp_price = 60000 - (expected_profit / 0.3)

        self.assertAlmostEqual(tp_price, expected_tp_price)
        self.assertEqual(tp_quantity, 0.3)

    @patch('binance_hft_market_maker.AsyncClient')
    async def test_place_take_profit_order_long(self, mock_async_client):
        mock_client_instance = AsyncMock()
        mock_async_client.create.return_value = mock_client_instance
        self.bot.client = mock_client_instance

        # Mock take-profit order placement
        mock_client_instance.futures_create_order.return_value = {
            "orderId": 44444,
            "symbol": "BTCUSDT",
            "status": "NEW"
        }

        await self.bot.place_take_profit_order(50500.0, 0.5, "LONG")

        # Verify that a SELL order was placed
        mock_client_instance.futures_create_order.assert_awaited_with(
            symbol="BTCUSDT",
            side="SELL",
            type="LIMIT",
            timeInForce="GTC",
            quantity=0.5,
            price="50500.0"
        )
        self.assertIn(44444, self.bot.active_orders)
        self.assertEqual(self.bot.active_orders[44444]['side'], "SELL")
        self.assertEqual(self.bot.active_orders[44444]['price'], 50500.0)

    @patch('binance_hft_market_maker.AsyncClient')
    async def test_monitor_orders(self, mock_async_client):
        mock_client_instance = AsyncMock()
        mock_async_client.create.return_value = mock_client_instance
        self.bot.client = mock_client_instance

        # Setup initial active orders
        self.bot.active_orders = {
            555: {'side': 'BUY', 'price': 50499.5},
            666: {'side': 'SELL', 'price': 50500.5}
        }

        # Mock open orders (only order 555 is still open)
        mock_client_instance.futures_get_open_orders.return_value = [
            {"orderId": 555, "symbol": "BTCUSDT", "side": "BUY", "price": "50499.5"}
        ]

        # Mock order cancellation
        mock_client_instance.futures_cancel_order.return_value = {}

        # Run monitor_orders for one cycle
        async def run_monitor_orders():
            # Run only one iteration for testing
            await self.bot.monitor_orders()
        
        # Modify monitor_orders to exit after one iteration for testing
        original_monitor_orders = self.bot.monitor_orders
        async def modified_monitor_orders():
            await self.bot.monitor_orders()
            raise KeyboardInterrupt  # Exit after one iteration

        self.bot.monitor_orders = modified_monitor_orders

        with self.assertRaises(KeyboardInterrupt):
            await asyncio.wait_for(run_monitor_orders(), timeout=1)

        # Verify that order 666 was identified as filled and a new BUY order was placed
        mock_client_instance.futures_cancel_order.assert_awaited_once_with(symbol="BTCUSDT", orderId=666)
        # Since it's a SELL order, a new SELL order should be placed at price + tick_size
        mock_client_instance.futures_create_order.assert_awaited_once_with(
            symbol="BTCUSDT",
            side="SELL",
            type="LIMIT",
            timeInForce="GTC",
            quantity=self.bot_config.volume,
            price=str(50500.5 + self.bot.tick_size)
        )

    @patch('binance_hft_market_maker.AsyncClient')
    async def test_error_handling_initialize_client(self, mock_async_client):
        # Simulate an API exception during client initialization
        mock_async_client.create.side_effect = Exception("API connection error")

        with self.assertRaises(SystemExit):
            await self.bot.initialize_client()

    @patch('binance_hft_market_maker.AsyncClient')
    async def test_error_handling_place_limit_order(self, mock_async_client):
        mock_client_instance = AsyncMock()
        mock_async_client.create.return_value = mock_client_instance
        self.bot.client = mock_client_instance

        # Simulate an API exception during order placement
        mock_client_instance.futures_create_order.side_effect = Exception("Order placement error")

        order = await self.bot.place_limit_order("BUY", 0.001, 50499.5)
        self.assertIsNone(order)

    # Additional tests can be added here to cover more scenarios

if __name__ == '__main__':
    unittest.main()
