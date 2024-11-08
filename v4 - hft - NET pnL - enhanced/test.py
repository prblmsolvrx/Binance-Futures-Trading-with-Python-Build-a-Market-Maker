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
