# -----------------------------
# Enhanced Binance HFT Market Maker Bot with Integrated Test Suite
# -----------------------------

import asyncio
import logging
import logging.handlers
import sys
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict

from binance import AsyncClient, BinanceSocketManager
from binance.enums import *
from binance.exceptions import BinanceAPIException, BinanceRequestException
from binance.helpers import round_step_size
import numpy as np
import pandas as pd

# Replace 'key_file' with your own module or method to securely load API keys
# Ensure this file is secure and not tracked by version control
import key_file as k  # This should contain binance_api_key and binance_api_secret variables

from rich.live import Live
from rich.table import Table
from rich.console import Console
from rich import box

# -----------------------------
# Logging Configuration
# -----------------------------

logger = logging.getLogger("BinanceBot")
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter('%(asctime)s %(levelname)s:%(message)s')

if not logger.hasHandlers():
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    fh = logging.handlers.RotatingFileHandler(
        'bot.log',
        maxBytes=5*1024*1024,
        backupCount=5
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

# -----------------------------
# Data Classes for Configuration
# -----------------------------

@dataclass
class BotConfig:
    symbol: str
    no_of_decimal_places: int
    volume: float
    grid_multiplier: float
    take_profit_percent: float
    stop_loss_percent: float
    num_of_grids: int
    leverage: int = 1
    testnet: bool = False
    risk_percentage: float = 0.01  # 1% risk per trade
    trailing_stop_callback: float = 0.1  # 0.1% trailing stop
    volatility_threshold: float = 0.5  # Threshold for volatility regime detection

# -----------------------------
# BinanceBot Class Definition
# -----------------------------

class BinanceBot:
    def __init__(self, config: BotConfig):
        self.config = config
        self.api_key = k.binance_testnet_api_key   # Ensure your API keys are securely loaded
        self.api_secret = k.binance_testnet_api_secret

        if not self.api_key or not self.api_secret:
            logger.error("Binance API keys are missing.")
            sys.exit(1)
        else:
            logger.info(f"Initialized BinanceBot for {self.config.symbol} with leverage {self.config.leverage}x.")

        self.client: Optional[AsyncClient] = None
        self.tick_size: Optional[float] = None
        self.step_size: Optional[float] = None
        self.active_orders: Dict[int, Dict] = {}
        self.grid_spacing: float = 0.0

        self.console = Console()
        self.table = Table(title=f"Trading Data - {self.config.symbol}", box=box.SIMPLE_HEAVY)
        self.table.add_column("Symbol")
        self.table.add_column("Position")
        self.table.add_column("Entry Price")
        self.table.add_column("Mark Price")
        self.table.add_column("Unrealized PnL")
        self.table.add_column("PnL (%)")
        self.table.add_column("Net PnL")

        # For WebSocket streams
        self.bsm: Optional[BinanceSocketManager] = None
        self.trade_socket = None
        self.depth_socket = None
        self.trade_task = None
        self.depth_task = None

    async def initialize_client(self):
        try:
            self.client = await AsyncClient.create(
                api_key=self.api_key,
                api_secret=self.api_secret,
                testnet=self.config.testnet
            )
            logger.info(f"Initialized Binance client for {self.config.symbol}")

            await self.set_leverage()
            await self.get_symbol_info()
        except Exception as e:
            logger.error(f"Error during client initialization: {e}")
            sys.exit(1)

    async def get_symbol_info(self):
        try:
            exchange_info = await self.client.futures_exchange_info()
            symbol_info = next((s for s in exchange_info['symbols'] if s['symbol'] == self.config.symbol), None)
            if symbol_info:
                for f in symbol_info['filters']:
                    if f['filterType'] == 'PRICE_FILTER':
                        self.tick_size = float(f['tickSize'])
                    if f['filterType'] == 'LOT_SIZE':
                        self.step_size = float(f['stepSize'])
                logger.info(f"Tick size for {self.config.symbol} is {self.tick_size}")
                logger.info(f"Step size for {self.config.symbol} is {self.step_size}")
            else:
                logger.error(f"Symbol {self.config.symbol} not found.")
                sys.exit(1)
        except Exception as e:
            logger.error(f"Error fetching symbol info: {e}")
            sys.exit(1)

    async def set_leverage(self):
        try:
            await self.client.futures_change_leverage(
                symbol=self.config.symbol,
                leverage=self.config.leverage
            )
            logger.info(f"Leverage set to {self.config.leverage}x for {self.config.symbol}")
        except Exception as e:
            logger.error(f"Error setting leverage: {e}")

    async def get_mark_price(self) -> Optional[float]:
        try:
            ticker = await self.client.futures_mark_price(symbol=self.config.symbol)
            price = float(ticker['markPrice'])
            return price
        except Exception as e:
            logger.error(f"Error fetching mark price: {e}")
            return None

    async def calculate_atr(self, period=14) -> float:
        try:
            klines = await self.client.futures_klines(
                symbol=self.config.symbol,
                interval=AsyncClient.KLINE_INTERVAL_1MINUTE,
                limit=period
            )
            df = pd.DataFrame(klines, columns=['open_time', 'open', 'high', 'low', 'close',
                                               'volume', 'close_time', 'quote_asset_volume',
                                               'number_of_trades', 'taker_buy_base_volume',
                                               'taker_buy_quote_volume', 'ignore'])
            df['high'] = df['high'].astype(float)
            df['low'] = df['low'].astype(float)
            df['close'] = df['close'].astype(float)
            df['previous_close'] = df['close'].shift(1)
            df['tr'] = df.apply(
                lambda row: max(
                    row['high'] - row['low'],
                    abs(row['high'] - row['previous_close']),
                    abs(row['low'] - row['previous_close'])
                ), axis=1
            )
            atr = df['tr'].rolling(window=period).mean().iloc[-1]
            return atr
        except Exception as e:
            logger.error(f"Error calculating ATR: {e}")
            return 0.0

    async def adjust_grid(self):
        atr = await self.calculate_atr()
        self.grid_spacing = atr * self.config.grid_multiplier
        logger.info(f"Adjusted grid spacing to {self.grid_spacing} based on ATR.")

    async def draw_adaptive_grid(self):
        await self.adjust_grid()
        current_price = await self.get_mark_price()
        if current_price is None:
            logger.warning("Current price unavailable. Skipping grid drawing.")
            return

        grid_levels = np.arange(-self.config.num_of_grids, self.config.num_of_grids + 1) * self.grid_spacing + current_price

        for price in grid_levels:
            price = round_step_size(price, step_size=self.tick_size)
            side = SIDE_BUY if price < current_price else SIDE_SELL
            quantity = round_step_size(self.config.volume, step_size=self.step_size)
            order = await self.place_limit_order(side, quantity, price)
            if order:
                self.active_orders[order['orderId']] = {'side': side, 'price': price}

    async def place_limit_order(self, side: str, quantity: float, price: float) -> Optional[dict]:
        try:
            order = await self.client.futures_create_order(
                symbol=self.config.symbol,
                side=side,
                type=ORDER_TYPE_LIMIT,
                timeInForce=TIME_IN_FORCE_GTC,
                quantity=quantity,
                price=str(price),
            )
            logger.info(f"{side} limit order placed at {price} for {quantity} {self.config.symbol}")
            return order
        except Exception as e:
            logger.error(f"Error placing {side} order: {e}")
            return None

    async def start_streams(self):
        try:
            self.bsm = BinanceSocketManager(self.client)
            self.depth_socket = self.bsm.futures_depth_socket(self.config.symbol)
            self.trade_socket = self.bsm.futures_symbol_ticker_socket(self.config.symbol)
            self.depth_task = asyncio.create_task(self.handle_depth_socket())
            self.trade_task = asyncio.create_task(self.handle_trade_socket())
        except Exception as e:
            logger.error(f"Error starting streams: {e}")

    async def handle_depth_socket(self):
        async with self.depth_socket as stream:
            while True:
                try:
                    res = await stream.recv()
                    bids = res['b']
                    asks = res['a']
                    imbalance = self.calculate_order_book_imbalance(bids, asks)
                    # Adjust strategy based on imbalance if needed
                except Exception as e:
                    logger.error(f"Error in depth socket: {e}")
                    await asyncio.sleep(1)

    def calculate_order_book_imbalance(self, bids, asks):
        bid_volume = sum(float(bid[1]) for bid in bids)
        ask_volume = sum(float(ask[1]) for ask in asks)
        imbalance = (bid_volume - ask_volume) / (bid_volume + ask_volume)
        return imbalance

    async def handle_trade_socket(self):
        async with self.trade_socket as stream:
            while True:
                try:
                    res = await stream.recv()
                    # Process trade data if needed
                except Exception as e:
                    logger.error(f"Error in trade socket: {e}")
                    await asyncio.sleep(1)

    async def monitor_orders(self):
        while True:
            try:
                open_orders = await self.client.futures_get_open_orders(symbol=self.config.symbol)
                open_order_ids = {order['orderId'] for order in open_orders}

                filled_order_ids = set(self.active_orders.keys()) - open_order_ids

                for order_id in filled_order_ids:
                    order_info = self.active_orders.pop(order_id, None)
                    if order_info:
                        side = order_info['side']
                        price = order_info['price']
                        # Place a new order to maintain the grid
                        if side == SIDE_SELL:
                            new_sell_price = round_step_size(price + self.grid_spacing, step_size=self.tick_size)
                            new_order = await self.place_limit_order(SIDE_SELL, self.config.volume, new_sell_price)
                            if new_order:
                                self.active_orders[new_order['orderId']] = {'side': SIDE_SELL, 'price': new_sell_price}
                        elif side == SIDE_BUY:
                            new_buy_price = round_step_size(price - self.grid_spacing, step_size=self.tick_size)
                            new_order = await self.place_limit_order(SIDE_BUY, self.config.volume, new_buy_price)
                            if new_order:
                                self.active_orders[new_order['orderId']] = {'side': SIDE_BUY, 'price': new_buy_price}

                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Exception in monitor_orders: {e}")
                await asyncio.sleep(1)

    async def monitor_pnl(self):
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
                                break

                    if not position_found:
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
        await self.initialize_client()
        await self.start_streams()
        try:
            await asyncio.gather(
                self.draw_adaptive_grid(),
                self.monitor_orders(),
                self.monitor_pnl()
            )
        except Exception as e:
            logger.error(f"Exception in run: {e}")
        finally:
            if self.client:
                await self.client.close_connection()
                logger.info(f"Closed Binance client for {self.config.symbol}")

# -----------------------------
# Test Suite for BinanceBot
# -----------------------------

import unittest
from unittest.mock import AsyncMock, patch, MagicMock

class TestBinanceBot(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = BotConfig(
            symbol="BTCUSDT",
            no_of_decimal_places=3,
            volume=0.001,
            grid_multiplier=0.1,
            take_profit_percent=0.5,
            stop_loss_percent=0.5,
            num_of_grids=2,
            leverage=10,
            testnet=True
        )
        self.bot = BinanceBot(self.config)
        self.bot.console = MagicMock()

    @patch('binance.AsyncClient.create')
    async def test_initialize_client_success(self, mock_create):
        mock_create.return_value = AsyncMock()
        await self.bot.initialize_client()
        self.assertIsNotNone(self.bot.client)
        mock_create.assert_called_once()

    @patch('binance.AsyncClient.futures_exchange_info')
    async def test_get_symbol_info_success(self, mock_exchange_info):
        mock_exchange_info.return_value = {
            'symbols': [
                {
                    'symbol': 'BTCUSDT',
                    'filters': [
                        {'filterType': 'PRICE_FILTER', 'tickSize': '0.1'},
                        {'filterType': 'LOT_SIZE', 'stepSize': '0.001'}
                    ]
                }
            ]
        }
        self.bot.client = AsyncMock()
        await self.bot.get_symbol_info()
        self.assertEqual(self.bot.tick_size, 0.1)
        self.assertEqual(self.bot.step_size, 0.001)

    @patch('binance.AsyncClient.futures_create_order')
    async def test_place_limit_order_success(self, mock_create_order):
        mock_create_order.return_value = {'orderId': 12345}
        self.bot.client = AsyncMock()
        order = await self.bot.place_limit_order('BUY', 0.001, 50000)
        self.assertIsNotNone(order)
        self.assertEqual(order['orderId'], 12345)

    @patch('binance.AsyncClient.futures_get_open_orders')
    @patch('binance.AsyncClient.futures_cancel_order')
    async def test_cancel_orders(self, mock_cancel_order, mock_get_open_orders):
        mock_get_open_orders.return_value = [{'orderId': 12345, 'side': 'BUY'}]
        self.bot.client = AsyncMock()
        self.bot.active_orders = {12345: {'side': 'BUY', 'price': 50000}}
        await self.bot.cancel_orders()
        mock_get_open_orders.assert_called_once()
        mock_cancel_order.assert_called_once_with(symbol=self.config.symbol, orderId=12345)
        self.assertEqual(self.bot.active_orders, {})

    async def test_calculate_order_book_imbalance(self):
        bids = [['50000', '1'], ['49999', '2']]
        asks = [['50001', '1.5'], ['50002', '1']]
        imbalance = self.bot.calculate_order_book_imbalance(bids, asks)
        expected_imbalance = (3 - 2.5) / (3 + 2.5)
        self.assertAlmostEqual(imbalance, expected_imbalance)

# -----------------------------
# Main Function to Run Bots
# -----------------------------

async def main():
    bot_configs = [
        BotConfig(
            symbol="BTCUSDT",
            no_of_decimal_places=3,
            volume=0.001,
            grid_multiplier=0.1,
            take_profit_percent=0.5,
            stop_loss_percent=0.5,
            num_of_grids=2,
            leverage=10,
            testnet=True
        ),
        BotConfig(
            symbol="ETHUSDT",
            no_of_decimal_places=3,
            volume=0.01,
            grid_multiplier=0.1,
            take_profit_percent=0.5,
            stop_loss_percent=0.5,
            num_of_grids=2,
            leverage=10,
            testnet=True
        )
    ]

    bots = [BinanceBot(config) for config in bot_configs]

    await asyncio.gather(*(bot.run() for bot in bots))

# -----------------------------
# Entry Point
# -----------------------------

if __name__ == "__main__":
    import sys
    if 'test' in sys.argv:
        unittest.main(argv=['first-arg-is-ignored'], exit=False)
    else:
        try:
            logger.info("Starting Binance trading bots...")
            asyncio.run(main())
        except KeyboardInterrupt:
            logger.info("Bot terminated by user.")
        except Exception as e:
            logger.error(f"Unhandled exception: {e}")
