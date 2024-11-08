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
