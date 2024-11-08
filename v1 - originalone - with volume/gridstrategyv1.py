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
logger.setLevel(logging.INFO)  # Set the default logging level to INFO

# Define the log message format
formatter = logging.Formatter('%(asctime)s %(levelname)s:%(message)s')

# Prevent adding multiple handlers if they already exist
if not logger.hasHandlers():
    # Console Handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)  # Set logging level for console
    ch.setFormatter(formatter)  # Apply the formatter to console handler
    logger.addHandler(ch)  # Add console handler to the logger

    # File Handler with Rotation
    fh = logging.handlers.RotatingFileHandler(
        'bot.log',  # Log file name
        maxBytes=5*1024*1024,  # Maximum size per log file (5 MB)
        backupCount=5  # Number of backup log files to keep
    )
    fh.setLevel(logging.INFO)  # Set logging level for file handler
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
    proportion: float
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
            sys.exit(1)  # Exit the program if API keys are missing

        self.client: Optional[AsyncClient] = None  # Binance AsyncClient will be initialized later

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
        except Exception as e:
            logger.error(f"Failed to initialize client: {e}")
            sys.exit(1)  # Exit the program if client initialization fails

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
                    logger.debug(f"Position amount for {self.config.symbol}: {position_amt}")
                    if position_amt > 0:
                        return "LONG"
                    elif position_amt < 0:
                        return "SHORT"
                    else:
                        return "FLAT"
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
        except Exception as e:
            logger.error(f"Error fetching mark price: {e}")
            return None

    async def draw_grid(self):
        """
        Place grid of limit buy and sell orders around the current market price.
        """
        current_price = await self.get_mark_price()
        if current_price is None:
            logger.warning("Current price unavailable. Skipping grid drawing.")
            return

        grid_spacing = self.config.proportion
        for i in range(1, self.config.num_of_grids + 1):
            sell_price = round_step_size(
                current_price * (1 + grid_spacing * i / 100),
                step_size=10**-self.config.no_of_decimal_places
            )
            buy_price = round_step_size(
                current_price * (1 - grid_spacing * i / 100),
                step_size=10**-self.config.no_of_decimal_places
            )
            await self.place_limit_order(SIDE_SELL, self.config.volume, sell_price)
            await self.place_limit_order(SIDE_BUY, self.config.volume, buy_price)
            logger.info(f"Placed grid orders at Sell: {sell_price}, Buy: {buy_price}")

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
            for order in open_orders:
                await self.client.futures_cancel_order(symbol=self.config.symbol, orderId=order['orderId'])
                logger.info(f"Canceled order {order['orderId']} for {self.config.symbol}")
            if side:
                logger.info(f"All {side} orders canceled for {self.config.symbol}")
            else:
                logger.info(f"All orders canceled for {self.config.symbol}")
        except Exception as e:
            logger.error(f"Error canceling orders: {e}")

    async def calculate_take_profit_level(self) -> Tuple[Optional[float], Optional[float]]:
        """
        Calculate the take-profit price level based on current open positions.

        Returns:
            Tuple[Optional[float], Optional[float]]: (Take-profit price, Position amount)
        """
        try:
            positions = await self.client.futures_position_information(symbol=self.config.symbol)
            position = next((p for p in positions if p['symbol'] == self.config.symbol and float(p['positionAmt']) != 0), None)
            if not position:
                logger.info("No open positions to calculate take profit.")
                return None, None

            entry_price = float(position['entryPrice'])  # Entry price of the position
            position_amt = float(position['positionAmt'])  # Amount of the position
            leverage = float(position.get('leverage', 1))  # Leverage used

            # Validate leverage
            if leverage <= 0:
                logger.warning("Invalid leverage found. Defaulting to 1.")
                leverage = 1

            # Calculate margin and desired profit
            margin = (entry_price * abs(position_amt)) / leverage
            profit = margin * (self.config.take_profit_percent / 100)

            # Calculate TP price based on position direction
            if position_amt > 0:  # LONG
                tp_price = entry_price + (profit / position_amt)
            elif position_amt < 0:  # SHORT
                tp_price = entry_price - (profit / abs(position_amt))
            else:
                tp_price = None

            if tp_price:
                tp_price = round_step_size(tp_price, step_size=10**-self.config.no_of_decimal_places)
                logger.info(f"Calculated TP level: Price={tp_price}, Amount={abs(position_amt)}")
                return tp_price, abs(position_amt)
            else:
                return None, None
        except Exception as e:
            logger.error(f"Exception in calculate_take_profit_level: {e}")
            return None, None

    async def place_take_profit_order(self, price: float, amount: float, direction: str):
        """
        Place a take-profit order based on the current position direction.

        Args:
            price (float): Take-profit price.
            amount (float): Amount to sell or buy.
            direction (str): 'LONG' or 'SHORT'.
        """
        side = SIDE_SELL if direction == "LONG" else SIDE_BUY  # Determine side based on position
        order = await self.place_limit_order(side, amount, price)
        if order:
            logger.info(f"Placed take-profit order: {side} {price} for {self.config.symbol}")


    async def monitor_position(self):
        """
        Monitor the position and manage orders accordingly.
        """
        while True:
            try:
                direction = await self.get_position_direction()
                if direction != "FLAT":
                    logger.info(f"Position detected: {direction} for {self.config.symbol}")

                    # Cancel opposing side orders to avoid conflicting orders
                    opposing_side = SIDE_SELL if direction == "LONG" else SIDE_BUY
                    await self.cancel_orders(side=opposing_side)

                    # Calculate and place take-profit order
                    tp_price, tp_amount = await self.calculate_take_profit_level()
                    if tp_price and tp_amount:
                        await self.place_take_profit_order(tp_price, tp_amount, direction)

                    # Continuously monitor the position to adjust TP orders if needed
                    while direction != "FLAT":
                        new_direction = await self.get_position_direction()
                        if new_direction != direction:
                            logger.info(f"Position direction changed from {direction} to {new_direction}")
                            await self.cancel_orders()
                            break

                        # Recalculate take-profit level
                        new_tp_price, new_tp_amount = await self.calculate_take_profit_level()
                        if new_tp_price and new_tp_price != tp_price:
                            logger.info("TP level changed. Updating orders...")
                            await self.cancel_orders()
                            await self.place_take_profit_order(new_tp_price, new_tp_amount, direction)
                            tp_price, tp_amount = new_tp_price, new_tp_amount

                        await asyncio.sleep(5)  # Wait before the next check
                else:
                    logger.info(f"No open positions for {self.config.symbol}. Drawing grid...")
                    await self.draw_grid()

                await asyncio.sleep(10)  # Wait before the next monitoring cycle
            except Exception as e:
                logger.error(f"Exception in monitor_position: {e}")
                await asyncio.sleep(10)  # Wait before retrying in case of error

    async def run(self):
        """
        Run the BinanceBot by initializing the client and starting position monitoring.
        """
        await self.initialize_client()
        await self.monitor_position()

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
            volume=0.01,
            proportion=0.04,
            take_profit_percent=5,
            num_of_grids=10,
            leverage=10,
            testnet=True
        ),
        BotConfig(
            symbol="ETHUSDT",
            no_of_decimal_places=2,
            volume=0.01,
            proportion=0.04,
            take_profit_percent=5,
            num_of_grids=10,
            leverage=10,
            testnet=True
        )
        # Add more BotConfig instances here for additional bots
    ]

    bots = []
    for bot_config in bot_configs:
        bot = BinanceBot(bot_config)
        bots.append(bot.run())  # Ensure 'run' method exists

    # Run all bots concurrently
    await asyncio.gather(*bots)

# -----------------------------
# Entry Point
# -----------------------------

if __name__ == "__main__":
    try:
        # Start the asyncio event loop and run the main function
        asyncio.run(main())
    except KeyboardInterrupt:
        # Handle user-initiated interruption (e.g., Ctrl+C)
        logger.info("Bot terminated by user.")
    except Exception as e:
        # Handle any unexpected exceptions
        logger.error(f"Unhandled exception: {e}")
